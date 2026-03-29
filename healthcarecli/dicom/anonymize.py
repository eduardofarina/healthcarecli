"""DICOM de-identification — remove or replace PHI tags from DICOM files.

Implements profiles based on DICOM PS3.15 Annex E (Basic Application Level
Confidentiality Profile) and HIPAA Safe Harbor.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pydicom
from pydicom import Dataset

# ── Tag lists ────────────────────────────────────────────────────────────────

# Tags that always contain direct PHI identifiers (Safe Harbor minimum).
_SAFE_HARBOR_REMOVE: list[int] = [
    0x00080050,  # AccessionNumber
    0x00080080,  # InstitutionName
    0x00080081,  # InstitutionAddress
    0x00080090,  # ReferringPhysicianName
    0x00080092,  # ReferringPhysicianAddress
    0x00080094,  # ReferringPhysicianTelephoneNumbers
    0x00081048,  # PhysiciansOfRecord
    0x00081049,  # PhysiciansOfRecordIdentificationSequence
    0x00081050,  # PerformingPhysicianName
    0x00081060,  # NameOfPhysiciansReadingStudy
    0x00081070,  # OperatorsName
    0x00100010,  # PatientName
    0x00100020,  # PatientID
    0x00100030,  # PatientBirthDate
    0x00100032,  # PatientBirthTime
    0x00100040,  # PatientSex
    0x00100050,  # PatientInsurancePlanCodeSequence
    0x00101000,  # OtherPatientIDs
    0x00101001,  # OtherPatientNames
    0x00101040,  # PatientAddress
    0x00101060,  # PatientMotherBirthName
    0x00102160,  # EthnicGroup
    0x00104000,  # PatientComments
    0x00200010,  # StudyID
    0x00321032,  # RequestingPhysician
    0x00321033,  # RequestingService
    0x00380010,  # AdmissionID
    0x00380020,  # AdmittingDate
    0x00380500,  # PatientState
    0x00400006,  # ScheduledPerformingPhysicianName
    0x00400244,  # PerformedProcedureStepStartDate
    0x00400253,  # PerformedProcedureStepID
    0x00400275,  # RequestAttributesSequence
    0x40000010,  # Arbitrary
    0x40004000,  # TextComments
]

# Tags to keep empty (useful for ML — preserves tag existence).
_SAFE_HARBOR_EMPTY: list[int] = [
    0x00080020,  # StudyDate
    0x00080030,  # StudyTime
    0x00080021,  # SeriesDate
    0x00080031,  # SeriesTime
]

# Tags commonly needed for ML research that can be preserved.
_ML_SAFE_TAGS: set[str] = {
    "Modality",
    "SeriesDescription",
    "StudyDescription",
    "BodyPartExamined",
    "ViewPosition",
    "ImageType",
    "Rows",
    "Columns",
    "BitsAllocated",
    "BitsStored",
    "PixelSpacing",
    "SliceThickness",
    "SpacingBetweenSlices",
    "ImageOrientationPatient",
    "ImagePositionPatient",
    "PhotometricInterpretation",
    "RescaleIntercept",
    "RescaleSlope",
    "WindowCenter",
    "WindowWidth",
    "PixelData",
    "SamplesPerPixel",
    "NumberOfFrames",
    "ConvolutionKernel",
    "KVP",
    "ExposureTime",
    "XRayTubeCurrent",
    "MagneticFieldStrength",
    "EchoTime",
    "RepetitionTime",
    "FlipAngle",
    "SequenceName",
}

PROFILES: dict[str, str] = {
    "safe-harbor": "HIPAA Safe Harbor — removes all 18 PHI identifiers",
    "basic": "Minimal — removes patient name, ID, and birth date only",
    "keep-dates": "Safe Harbor but preserves study/series dates (shifts not implemented)",
}


# ── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class AnonymizeResult:
    """Result of anonymizing a single DICOM file."""

    input_path: Path
    output_path: Path | None = None
    success: bool = True
    message: str = "OK"
    tags_removed: int = 0
    tags_emptied: int = 0


class AnonymizeError(RuntimeError):
    pass


# ── Core logic ───────────────────────────────────────────────────────────────


def _uid_remap(original_uid: str, salt: str) -> str:
    """Deterministic UID remapping — same input always produces same output."""
    h = hashlib.sha256(f"{salt}:{original_uid}".encode()).hexdigest()[:32]
    # Build a valid UID: 2.25.<decimal from hex>
    decimal_val = int(h, 16)
    new_uid = f"2.25.{decimal_val}"
    # DICOM UIDs max 64 chars
    return new_uid[:64]


def anonymize_dataset(
    ds: Dataset,
    *,
    profile: str = "safe-harbor",
    keep_tags: set[str] | None = None,
    salt: str = "",
) -> tuple[Dataset, int, int]:
    """Anonymize a DICOM dataset in-place.

    Args:
        ds: pydicom Dataset to anonymize.
        profile: Anonymization profile name.
        keep_tags: Additional tag keywords to preserve.
        salt: Salt for deterministic UID remapping (empty = random).

    Returns:
        Tuple of (dataset, tags_removed, tags_emptied).
    """
    if profile not in PROFILES:
        raise AnonymizeError(f"Unknown profile '{profile}'. Available: {list(PROFILES.keys())}")

    keep = _ML_SAFE_TAGS.copy()
    if keep_tags:
        keep.update(keep_tags)

    uid_salt = salt or uuid.uuid4().hex
    removed = 0
    emptied = 0

    if profile == "basic":
        # Minimal: just patient name, ID, birth date
        for tag in [0x00100010, 0x00100020, 0x00100030]:
            if tag in ds:
                del ds[tag]
                removed += 1
        return ds, removed, emptied

    # safe-harbor or keep-dates
    for tag in _SAFE_HARBOR_REMOVE:
        if tag in ds:
            elem = ds[tag]
            if elem.keyword in keep:
                continue
            del ds[tag]
            removed += 1

    # Empty date/time tags (or skip for keep-dates profile)
    if profile != "keep-dates":
        for tag in _SAFE_HARBOR_EMPTY:
            if tag in ds:
                elem = ds[tag]
                if elem.keyword in keep:
                    continue
                ds[tag].value = ""
                emptied += 1

    # Remap UIDs for consistency across a study
    for uid_tag in ["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"]:
        if hasattr(ds, uid_tag):
            original = str(getattr(ds, uid_tag))
            if original:
                setattr(ds, uid_tag, _uid_remap(original, uid_salt))

    # Update file_meta SOPInstanceUID if present
    if hasattr(ds, "file_meta") and hasattr(ds.file_meta, "MediaStorageSOPInstanceUID"):
        original = str(ds.file_meta.MediaStorageSOPInstanceUID)
        if original:
            ds.file_meta.MediaStorageSOPInstanceUID = _uid_remap(original, uid_salt)

    return ds, removed, emptied


def anonymize_file(
    input_path: Path,
    output_dir: Path,
    *,
    profile: str = "safe-harbor",
    keep_tags: set[str] | None = None,
    salt: str = "",
) -> AnonymizeResult:
    """Anonymize a single DICOM file and write to output directory.

    Args:
        input_path: Path to source DICOM file.
        output_dir: Directory for anonymized output.
        profile: Anonymization profile.
        keep_tags: Tag keywords to preserve.
        salt: Salt for UID remapping.

    Returns:
        AnonymizeResult with details.
    """
    try:
        ds = pydicom.dcmread(str(input_path))
    except Exception as exc:
        return AnonymizeResult(
            input_path=input_path,
            success=False,
            message=f"Read error: {exc}",
        )

    try:
        ds, removed, emptied = anonymize_dataset(
            ds, profile=profile, keep_tags=keep_tags, salt=salt
        )
    except AnonymizeError as exc:
        return AnonymizeResult(
            input_path=input_path,
            success=False,
            message=str(exc),
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / input_path.name
    try:
        ds.save_as(str(out_path), write_like_original=False)
    except Exception as exc:
        return AnonymizeResult(
            input_path=input_path,
            success=False,
            message=f"Write error: {exc}",
        )

    return AnonymizeResult(
        input_path=input_path,
        output_path=out_path,
        success=True,
        tags_removed=removed,
        tags_emptied=emptied,
    )


def anonymize_files(
    paths: list[Path],
    output_dir: Path,
    *,
    profile: str = "safe-harbor",
    keep_tags: set[str] | None = None,
    salt: str = "",
    on_progress: Callable[[AnonymizeResult], None] | None = None,
) -> list[AnonymizeResult]:
    """Anonymize multiple DICOM files or directories.

    Args:
        paths: DICOM files or directories (recursed for *.dcm).
        output_dir: Directory for anonymized output.
        profile: Anonymization profile.
        keep_tags: Tag keywords to preserve.
        salt: Salt for deterministic UID remapping.
        on_progress: Optional callback per file.

    Returns:
        List of AnonymizeResult.
    """
    files = _collect_dicom_files(paths)
    if not files:
        return []

    # Use consistent salt across all files so UIDs are linked
    run_salt = salt or uuid.uuid4().hex

    results: list[AnonymizeResult] = []
    for fpath in files:
        result = anonymize_file(
            fpath, output_dir, profile=profile, keep_tags=keep_tags, salt=run_salt
        )
        results.append(result)
        if on_progress:
            on_progress(result)

    return results


def _collect_dicom_files(paths: list[Path]) -> list[Path]:
    """Collect DICOM files from paths (expand directories recursively)."""
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("*.dcm")))
        elif p.is_file():
            files.append(p)
    return files
