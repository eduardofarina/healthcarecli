"""DICOM C-FIND SCU — query a PACS for studies, series, and instances."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from pydicom import Dataset
from pynetdicom import AE
from pynetdicom.sop_class import (
    PatientRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelFind,
)
from pynetdicom.status import code_to_category

from healthcarecli.dicom.connections import AEProfile

# Uncomment for verbose pynetdicom wire-level logging:
# debug_logger()

QueryLevel = str  # "PATIENT" | "STUDY" | "SERIES" | "IMAGE"


@dataclass
class QueryParams:
    """C-FIND query parameters.  All fields are optional match criteria."""

    query_level: QueryLevel = "STUDY"

    # Patient level
    patient_id: str = ""
    patient_name: str = ""
    birth_date: str = ""  # YYYYMMDD or YYYYMMDD-YYYYMMDD range

    # Study level
    study_date: str = ""  # YYYYMMDD or range
    study_instance_uid: str = ""
    accession_number: str = ""
    modalities_in_study: str = ""  # e.g. "CT" or "CT\\MR"

    # Series level
    series_instance_uid: str = ""
    modality: str = ""
    series_number: str = ""

    # Instance level
    sop_instance_uid: str = ""

    # Return tags requested from PACS (added automatically per level)
    extra_return_tags: list[str] = field(default_factory=list)

    def to_dataset(self) -> Dataset:
        ds = Dataset()
        ds.QueryRetrieveLevel = self.query_level

        # Always-requested return fields per level
        _RETURN_TAGS: dict[str, list[str]] = {
            "PATIENT": [
                "PatientID",
                "PatientName",
                "PatientBirthDate",
                "PatientSex",
                "NumberOfPatientRelatedStudies",
            ],
            "STUDY": [
                "PatientID",
                "PatientName",
                "PatientBirthDate",
                "StudyInstanceUID",
                "StudyDate",
                "StudyTime",
                "StudyDescription",
                "AccessionNumber",
                "ModalitiesInStudy",
                "NumberOfStudyRelatedSeries",
                "NumberOfStudyRelatedInstances",
            ],
            "SERIES": [
                "StudyInstanceUID",
                "SeriesInstanceUID",
                "SeriesDate",
                "SeriesTime",
                "SeriesDescription",
                "Modality",
                "SeriesNumber",
                "NumberOfSeriesRelatedInstances",
            ],
            "IMAGE": [
                "StudyInstanceUID",
                "SeriesInstanceUID",
                "SOPInstanceUID",
                "InstanceNumber",
                "SOPClassUID",
            ],
        }
        for tag in _RETURN_TAGS.get(self.query_level, []):
            setattr(ds, tag, "")

        # Set match criteria (non-empty values)
        _FIELD_MAP = {
            "PatientID": self.patient_id,
            "PatientName": self.patient_name,
            "PatientBirthDate": self.birth_date,
            "StudyDate": self.study_date,
            "StudyInstanceUID": self.study_instance_uid,
            "AccessionNumber": self.accession_number,
            "ModalitiesInStudy": self.modalities_in_study,
            "SeriesInstanceUID": self.series_instance_uid,
            "Modality": self.modality,
            "SeriesNumber": self.series_number,
            "SOPInstanceUID": self.sop_instance_uid,
        }
        for tag, value in _FIELD_MAP.items():
            if value:
                setattr(ds, tag, value)

        for tag in self.extra_return_tags:
            if not hasattr(ds, tag):
                setattr(ds, tag, "")

        return ds


@dataclass
class QueryResult:
    """A single C-FIND result converted to a plain dictionary."""

    data: dict[str, Any]

    @classmethod
    def from_dataset(cls, ds: Dataset) -> QueryResult:
        data: dict[str, Any] = {}
        for elem in ds:
            if elem.keyword:
                try:
                    data[elem.keyword] = str(elem.value) if elem.value is not None else ""
                except Exception:
                    data[elem.keyword] = ""
        return cls(data=data)


class DicomQueryError(RuntimeError):
    pass


def cfind(
    profile: AEProfile,
    params: QueryParams,
    *,
    model: str = "STUDY",
) -> Iterator[QueryResult]:
    """Run a C-FIND against the given AE profile.

    Args:
        profile: PACS connection profile.
        params:  Query criteria and return tags.
        model:   "STUDY" (default) or "PATIENT" root query model.

    Yields:
        QueryResult for each pending response from the SCP.

    Raises:
        DicomQueryError: on association failure or non-Success/Pending status.
    """
    ae = AE(ae_title=profile.calling_ae)

    sop_class = (
        StudyRootQueryRetrieveInformationModelFind
        if model.upper() == "STUDY"
        else PatientRootQueryRetrieveInformationModelFind
    )
    ae.add_requested_context(sop_class)

    assoc = ae.associate(
        profile.host,
        profile.port,
        ae_title=profile.ae_title,
    )
    if not assoc.is_established:
        raise DicomQueryError(
            f"Could not associate with {profile.ae_title}@{profile.host}:{profile.port}"
        )

    try:
        identifier = params.to_dataset()
        responses = assoc.send_c_find(identifier, sop_class)

        for status, dataset in responses:
            if status is None:
                raise DicomQueryError("Connection timed out or lost during C-FIND")

            category = code_to_category(status.Status)
            if category == "Failure":
                raise DicomQueryError(f"C-FIND failed — status 0x{status.Status:04X}")
            if category == "Pending" and dataset is not None:
                yield QueryResult.from_dataset(dataset)
            # "Success" (0x0000) is the final empty response — stop iteration
    finally:
        assoc.release()
