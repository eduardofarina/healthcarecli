"""Tests for C-FIND query building and SCU logic (mocked association)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydicom import Dataset

from healthcarecli.dicom.connections import AEProfile
from healthcarecli.dicom.query import (
    DicomQueryError,
    QueryParams,
    QueryResult,
    cfind,
)


def _make_profile(**kwargs):
    defaults = dict(name="test", host="127.0.0.1", port=4242, ae_title="TEST")
    defaults.update(kwargs)
    return AEProfile(**defaults)


# ── QueryParams.to_dataset ────────────────────────────────────────────────────

def test_query_params_defaults():
    ds = QueryParams().to_dataset()
    assert ds.QueryRetrieveLevel == "STUDY"
    assert hasattr(ds, "StudyInstanceUID")
    assert hasattr(ds, "PatientID")


def test_query_params_sets_match_criteria():
    ds = QueryParams(patient_id="12345", study_date="20240101").to_dataset()
    assert ds.PatientID == "12345"
    assert ds.StudyDate == "20240101"


def test_query_params_series_level():
    ds = QueryParams(query_level="SERIES", modality="CT").to_dataset()
    assert ds.QueryRetrieveLevel == "SERIES"
    assert ds.Modality == "CT"


def test_query_params_empty_fields_not_set_as_match():
    # Empty string fields should be present (wildcard) but not as a real match value
    ds = QueryParams(patient_id="").to_dataset()
    # PatientID is a return tag — present but empty (wildcard)
    assert ds.PatientID == ""


# ── QueryResult.from_dataset ──────────────────────────────────────────────────

def test_query_result_from_dataset():
    ds = Dataset()
    ds.PatientID = "P001"
    ds.StudyDate = "20240315"
    ds.StudyInstanceUID = "1.2.3"

    result = QueryResult.from_dataset(ds)
    assert result.data["PatientID"] == "P001"
    assert result.data["StudyDate"] == "20240315"


# ── cfind (mocked) ────────────────────────────────────────────────────────────

def _make_pending_dataset(patient_id: str = "P001") -> Dataset:
    ds = Dataset()
    ds.PatientID = patient_id
    ds.StudyInstanceUID = "1.2.3.4"
    ds.StudyDate = "20240101"
    return ds


def _status(code: int):
    s = Dataset()
    s.Status = code
    return s


def _mock_assoc(responses):
    assoc = MagicMock()
    assoc.is_established = True
    assoc.send_c_find.return_value = iter(responses)
    return assoc


@patch("healthcarecli.dicom.query.AE")
def test_cfind_yields_pending_results(mock_ae_cls):
    pending_ds = _make_pending_dataset()
    mock_ae_cls.return_value.associate.return_value = _mock_assoc([
        (_status(0xFF00), pending_ds),  # Pending
        (_status(0x0000), None),         # Success / done
    ])

    profile = _make_profile()
    results = list(cfind(profile, QueryParams()))

    assert len(results) == 1
    assert results[0].data["PatientID"] == "P001"


@patch("healthcarecli.dicom.query.AE")
def test_cfind_raises_on_association_failure(mock_ae_cls):
    assoc = MagicMock()
    assoc.is_established = False
    mock_ae_cls.return_value.associate.return_value = assoc

    with pytest.raises(DicomQueryError, match="Could not associate"):
        list(cfind(_make_profile(), QueryParams()))


@patch("healthcarecli.dicom.query.AE")
def test_cfind_raises_on_failure_status(mock_ae_cls):
    mock_ae_cls.return_value.associate.return_value = _mock_assoc([
        (_status(0xA700), None),  # Refused: Out of Resources
    ])

    with pytest.raises(DicomQueryError, match="C-FIND failed"):
        list(cfind(_make_profile(), QueryParams()))


@patch("healthcarecli.dicom.query.AE")
def test_cfind_raises_on_none_status(mock_ae_cls):
    mock_ae_cls.return_value.associate.return_value = _mock_assoc([
        (None, None),
    ])

    with pytest.raises(DicomQueryError, match="timed out"):
        list(cfind(_make_profile(), QueryParams()))


@patch("healthcarecli.dicom.query.AE")
def test_cfind_releases_association(mock_ae_cls):
    assoc = _mock_assoc([(_status(0x0000), None)])
    mock_ae_cls.return_value.associate.return_value = assoc

    list(cfind(_make_profile(), QueryParams()))
    assoc.release.assert_called_once()
