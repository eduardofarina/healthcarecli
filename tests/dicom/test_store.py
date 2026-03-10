"""Tests for C-STORE SCU logic (mocked association)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pydicom
import pytest
from pydicom import Dataset
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from healthcarecli.dicom.connections import AEProfile
from healthcarecli.dicom.store import DicomStoreError, StoreResult, _collect_files, csend


def _make_profile(**kwargs):
    defaults = dict(name="test", host="127.0.0.1", port=11112, ae_title="TEST")
    defaults.update(kwargs)
    return AEProfile(**defaults)


def _status(code: int):
    s = Dataset()
    s.Status = code
    return s


def _mock_assoc(status_code: int = 0x0000):
    assoc = MagicMock()
    assoc.is_established = True
    assoc.send_c_store.return_value = _status(status_code)
    return assoc


def _write_minimal_dcm(path: Path) -> Path:
    """Write a minimal valid DICOM file for testing (pydicom v2.4+ compatible)."""
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = "1.2.3.4.5"
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = "1.2.3.4.5"
    ds.PatientName = "Test^Patient"
    ds.PatientID = "TEST001"
    pydicom.dcmwrite(str(path), ds)
    return path


# ── _collect_files ────────────────────────────────────────────────────────────

def test_collect_files_single(tmp_path):
    f = tmp_path / "img.dcm"
    f.touch()
    assert _collect_files([f]) == [f]


def test_collect_files_directory(tmp_path):
    (tmp_path / "a.dcm").touch()
    (tmp_path / "b.dcm").touch()
    (tmp_path / "notes.txt").touch()

    result = _collect_files([tmp_path])
    assert len(result) == 2
    assert all(p.suffix == ".dcm" for p in result)


def test_collect_files_empty_list():
    assert _collect_files([]) == []


# ── csend ─────────────────────────────────────────────────────────────────────

@patch("healthcarecli.dicom.store.AE")
def test_csend_success(mock_ae_cls, tmp_path):
    dcm = _write_minimal_dcm(tmp_path / "test.dcm")
    assoc = _mock_assoc(0x0000)
    mock_ae_cls.return_value.associate.return_value = assoc

    results = csend(_make_profile(), [dcm])

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].status_code == 0x0000


@patch("healthcarecli.dicom.store.AE")
def test_csend_failure_status(mock_ae_cls, tmp_path):
    dcm = _write_minimal_dcm(tmp_path / "test.dcm")
    assoc = _mock_assoc(0xA700)  # Refused: Out of Resources
    mock_ae_cls.return_value.associate.return_value = assoc

    results = csend(_make_profile(), [dcm])

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].status_code == 0xA700


@patch("healthcarecli.dicom.store.AE")
def test_csend_raises_on_no_association(mock_ae_cls, tmp_path):
    # File must exist so _collect_files includes it; association check comes after
    dummy = tmp_path / "dummy.dcm"
    dummy.touch()
    assoc = MagicMock()
    assoc.is_established = False
    mock_ae_cls.return_value.associate.return_value = assoc

    with pytest.raises(DicomStoreError, match="Could not associate"):
        csend(_make_profile(), [dummy])


@patch("healthcarecli.dicom.store.AE")
def test_csend_bad_file_returns_error_result(mock_ae_cls, tmp_path):
    bad = tmp_path / "bad.dcm"
    bad.write_bytes(b"not dicom")
    assoc = _mock_assoc()
    mock_ae_cls.return_value.associate.return_value = assoc

    results = csend(_make_profile(), [bad])
    assert results[0].success is False
    assert "Read error" in results[0].message


@patch("healthcarecli.dicom.store.AE")
def test_csend_progress_callback(mock_ae_cls, tmp_path):
    dcm = _write_minimal_dcm(tmp_path / "test.dcm")
    assoc = _mock_assoc(0x0000)
    mock_ae_cls.return_value.associate.return_value = assoc

    received: list[StoreResult] = []
    csend(_make_profile(), [dcm], on_progress=received.append)

    assert len(received) == 1
    assert received[0].success is True


@patch("healthcarecli.dicom.store.AE")
def test_csend_releases_association(mock_ae_cls, tmp_path):
    dcm = _write_minimal_dcm(tmp_path / "test.dcm")
    assoc = _mock_assoc()
    mock_ae_cls.return_value.associate.return_value = assoc

    csend(_make_profile(), [dcm])
    assoc.release.assert_called_once()
