"""Tests for DICOMweb module — QIDO-RS, WADO-RS, STOW-RS (mocked client)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from healthcarecli.dicom.web import (
    DICOMWebError,
    DICOMWebProfile,
    DICOMWebProfileNotFoundError,
    StowResult,
    _normalise_qido,
    qido_search,
    stow_store,
    wado_retrieve,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    import healthcarecli.config.manager as mgr
    monkeypatch.setattr(mgr, "config_dir", lambda: tmp_path)


def _make_profile(**kwargs) -> DICOMWebProfile:
    defaults = dict(name="test", url="http://localhost:8042/dicom-web")
    defaults.update(kwargs)
    return DICOMWebProfile(**defaults)


def _write_minimal_dcm(path: Path) -> Path:
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = "1.2.3.4.5"
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = "1.2.3.4.5"
    ds.PatientID = "P001"
    pydicom.dcmwrite(str(path), ds)
    return path


# ── Profile CRUD ──────────────────────────────────────────────────────────────

def test_profile_save_and_load():
    p = _make_profile(name="orthanc", url="http://orthanc:8042/dicom-web")
    p.save()
    loaded = DICOMWebProfile.load("orthanc")
    assert loaded.url == "http://orthanc:8042/dicom-web"
    assert loaded.auth_type == "none"


def test_profile_load_missing_raises():
    with pytest.raises(DICOMWebProfileNotFoundError):
        DICOMWebProfile.load("ghost")


def test_profile_list_all():
    _make_profile(name="a", url="http://a").save()
    _make_profile(name="b", url="http://b").save()
    names = {p.name for p in DICOMWebProfile.list_all()}
    assert names == {"a", "b"}


def test_profile_delete():
    _make_profile(name="temp").save()
    DICOMWebProfile.load("temp").delete()
    with pytest.raises(DICOMWebProfileNotFoundError):
        DICOMWebProfile.load("temp")


def test_profile_with_basic_auth_builds_session():
    p = _make_profile(auth_type="basic", username="user", password="pass")
    client = p.client()
    # DICOMwebClient stores session internally; check it was passed
    assert client is not None


def test_profile_with_bearer_token_builds_session():
    p = _make_profile(auth_type="bearer", token="mytoken")
    client = p.client()
    assert client is not None


# ── _normalise_qido ───────────────────────────────────────────────────────────

def test_normalise_qido_scalar():
    raw = [{"00100020": {"vr": "LO", "Value": ["P001"]}}]
    result = _normalise_qido(raw)
    assert result[0]["PatientID"] == "P001"


def test_normalise_qido_person_name():
    raw = [{"00100010": {"vr": "PN", "Value": [{"Alphabetic": "Smith^John"}]}}]
    result = _normalise_qido(raw)
    assert result[0]["PatientName"] == "Smith^John"


def test_normalise_qido_empty_value():
    raw = [{"00100020": {"vr": "LO", "Value": []}}]
    result = _normalise_qido(raw)
    assert result[0]["PatientID"] == ""


def test_normalise_qido_multi_value():
    raw = [{"00080061": {"vr": "CS", "Value": ["CT", "MR"]}}]
    result = _normalise_qido(raw)
    assert result[0]["ModalitiesInStudy"] == ["CT", "MR"]


def test_normalise_qido_unknown_tag():
    raw = [{"DEADBEEF": {"vr": "LO", "Value": ["x"]}}]
    result = _normalise_qido(raw)
    # Unknown tag kept as-is
    assert "DEADBEEF" in result[0]


# ── QIDO-RS ───────────────────────────────────────────────────────────────────

def _mock_client(search_return=None):
    client = MagicMock()
    client.search_for_studies.return_value = search_return or []
    client.search_for_series.return_value = search_return or []
    client.search_for_instances.return_value = search_return or []
    return client


@patch("healthcarecli.dicom.web.DICOMwebClient")
def test_qido_search_studies(mock_cls):
    raw = [{"00100020": {"vr": "LO", "Value": ["P001"]},
            "0020000D": {"vr": "UI", "Value": ["1.2.3"]}}]
    mock_cls.return_value = _mock_client(raw)

    results = qido_search(_make_profile(), level="studies", filters={"PatientID": "P001"})

    assert len(results) == 1
    assert results[0]["PatientID"] == "P001"


@patch("healthcarecli.dicom.web.DICOMwebClient")
def test_qido_search_series(mock_cls):
    mock_cls.return_value = _mock_client([{"00200011": {"vr": "IS", "Value": ["1"]}}])
    results = qido_search(_make_profile(), level="series", study_uid="1.2.3")
    assert len(results) == 1


@patch("healthcarecli.dicom.web.DICOMwebClient")
def test_qido_search_instances(mock_cls):
    mock_cls.return_value = _mock_client([{"00080018": {"vr": "UI", "Value": ["1.2.3.4"]}}])
    results = qido_search(_make_profile(), level="instances",
                          study_uid="1.2.3", series_uid="1.2.3.4")
    assert len(results) == 1


@patch("healthcarecli.dicom.web.DICOMwebClient")
def test_qido_invalid_level_raises(mock_cls):
    mock_cls.return_value = _mock_client()
    with pytest.raises(ValueError, match="Invalid QIDO level"):
        qido_search(_make_profile(), level="patients")


@patch("healthcarecli.dicom.web.DICOMwebClient")
def test_qido_http_error_raises_dicomweb_error(mock_cls):
    client = MagicMock()
    client.search_for_studies.side_effect = Exception("HTTP 403")
    mock_cls.return_value = client

    with pytest.raises(DICOMWebError, match="QIDO-RS failed"):
        qido_search(_make_profile(), level="studies")


# ── WADO-RS ───────────────────────────────────────────────────────────────────

def _make_dataset(sop_uid: str = "1.2.3.4.5") -> pydicom.Dataset:
    """Return a minimal FileDataset (with file_meta) for WADO mock responses."""
    from pydicom.dataset import FileDataset, FileMetaDataset
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset("", {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = sop_uid
    return ds


@patch("healthcarecli.dicom.web.DICOMwebClient")
def test_wado_retrieve_study(mock_cls, tmp_path):
    ds = _make_dataset("1.2.3.4.5")
    client = MagicMock()
    client.retrieve_study.return_value = [ds]
    mock_cls.return_value = client

    saved = wado_retrieve(_make_profile(), study_uid="1.2.3", output_dir=tmp_path)

    assert len(saved) == 1
    assert saved[0].suffix == ".dcm"
    client.retrieve_study.assert_called_once_with(study_instance_uid="1.2.3")


@patch("healthcarecli.dicom.web.DICOMwebClient")
def test_wado_retrieve_series(mock_cls, tmp_path):
    client = MagicMock()
    client.retrieve_series.return_value = [_make_dataset("1.1"), _make_dataset("1.2")]
    mock_cls.return_value = client

    saved = wado_retrieve(_make_profile(), study_uid="1.2.3",
                          series_uid="1.2.3.4", output_dir=tmp_path)

    assert len(saved) == 2


@patch("healthcarecli.dicom.web.DICOMwebClient")
def test_wado_retrieve_instance(mock_cls, tmp_path):
    client = MagicMock()
    client.retrieve_instance.return_value = _make_dataset("1.2.3.4.5")
    mock_cls.return_value = client

    saved = wado_retrieve(_make_profile(), study_uid="1.2.3",
                          series_uid="1.2.3.4", instance_uid="1.2.3.4.5",
                          output_dir=tmp_path)

    assert len(saved) == 1


@patch("healthcarecli.dicom.web.DICOMwebClient")
def test_wado_error_raises(mock_cls, tmp_path):
    client = MagicMock()
    client.retrieve_study.side_effect = Exception("HTTP 404")
    mock_cls.return_value = client

    with pytest.raises(DICOMWebError, match="WADO-RS failed"):
        wado_retrieve(_make_profile(), study_uid="9.9.9", output_dir=tmp_path)


# ── STOW-RS ───────────────────────────────────────────────────────────────────

@patch("healthcarecli.dicom.web.DICOMwebClient")
def test_stow_store_success(mock_cls, tmp_path):
    dcm = _write_minimal_dcm(tmp_path / "test.dcm")
    client = MagicMock()
    mock_cls.return_value = client

    result = stow_store(_make_profile(), [dcm])

    assert result.stored == 1
    assert result.failed == 0
    client.store_instances.assert_called_once()


@patch("healthcarecli.dicom.web.DICOMwebClient")
def test_stow_store_bad_file(mock_cls, tmp_path):
    bad = tmp_path / "bad.dcm"
    bad.write_bytes(b"not dicom")
    client = MagicMock()
    mock_cls.return_value = client

    result = stow_store(_make_profile(), [bad])

    assert result.stored == 0
    assert result.failed == 1
    # store_instances should not be called if no valid datasets
    client.store_instances.assert_not_called()


@patch("healthcarecli.dicom.web.DICOMwebClient")
def test_stow_empty_paths(mock_cls, tmp_path):
    result = stow_store(_make_profile(), [])
    assert result.stored == 0
    assert result.failed == 0


@patch("healthcarecli.dicom.web.DICOMwebClient")
def test_stow_http_error_raises(mock_cls, tmp_path):
    dcm = _write_minimal_dcm(tmp_path / "test.dcm")
    client = MagicMock()
    client.store_instances.side_effect = Exception("HTTP 500")
    mock_cls.return_value = client

    with pytest.raises(DICOMWebError, match="STOW-RS failed"):
        stow_store(_make_profile(), [dcm])
