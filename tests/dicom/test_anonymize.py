"""Tests for DICOM anonymization."""

from __future__ import annotations

from pathlib import Path

import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from healthcarecli.config import manager as mgr
from healthcarecli.dicom.anonymize import (
    PROFILES,
    AnonymizeError,
    AnonymizeResult,
    anonymize_dataset,
    anonymize_file,
    anonymize_files,
)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(mgr, "config_dir", lambda: tmp_path)


def _write_dcm(path: Path, **tags) -> Path:
    """Write a minimal DICOM file with optional extra tags."""
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = "1.2.3.4.5"
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = "1.2.3.4.5"
    ds.StudyInstanceUID = "1.2.3.100"
    ds.SeriesInstanceUID = "1.2.3.200"

    # Default PHI tags
    ds.PatientName = "Doe^John"
    ds.PatientID = "PAT001"
    ds.PatientBirthDate = "19800101"
    ds.PatientSex = "M"
    ds.InstitutionName = "Hospital Test"
    ds.ReferringPhysicianName = "Dr. Smith"
    ds.StudyDate = "20240101"
    ds.StudyTime = "120000"
    ds.Modality = "CT"
    ds.SeriesDescription = "Chest CT"

    for k, v in tags.items():
        setattr(ds, k, v)

    pydicom.dcmwrite(str(path), ds)
    return path


# ── anonymize_dataset ────────────────────────────────────────────────────────


class TestAnonymizeDataset:
    def test_safe_harbor_removes_patient_name(self, tmp_path):
        path = _write_dcm(tmp_path / "test.dcm")
        ds = pydicom.dcmread(str(path))

        ds, removed, emptied = anonymize_dataset(ds, profile="safe-harbor", salt="test")

        assert not hasattr(ds, "PatientName")
        assert not hasattr(ds, "PatientID")
        assert not hasattr(ds, "PatientBirthDate")
        assert removed > 0

    def test_safe_harbor_empties_dates(self, tmp_path):
        path = _write_dcm(tmp_path / "test.dcm")
        ds = pydicom.dcmread(str(path))

        ds, _, emptied = anonymize_dataset(ds, profile="safe-harbor", salt="test")

        assert emptied > 0

    def test_basic_profile_only_removes_minimal(self, tmp_path):
        path = _write_dcm(tmp_path / "test.dcm")
        ds = pydicom.dcmread(str(path))

        ds, removed, _ = anonymize_dataset(ds, profile="basic", salt="test")

        assert not hasattr(ds, "PatientName")
        assert not hasattr(ds, "PatientID")
        # Institution should still be there with basic profile
        assert hasattr(ds, "InstitutionName")
        assert removed == 3

    def test_keep_dates_preserves_study_date(self, tmp_path):
        path = _write_dcm(tmp_path / "test.dcm")
        ds = pydicom.dcmread(str(path))

        ds, _, emptied = anonymize_dataset(ds, profile="keep-dates", salt="test")

        # Dates should NOT be emptied
        assert emptied == 0
        assert ds.StudyDate == "20240101"

    def test_uid_remapping_is_deterministic(self, tmp_path):
        path = _write_dcm(tmp_path / "test.dcm")

        ds1 = pydicom.dcmread(str(path))
        ds1, _, _ = anonymize_dataset(ds1, profile="safe-harbor", salt="fixed")

        ds2 = pydicom.dcmread(str(path))
        ds2, _, _ = anonymize_dataset(ds2, profile="safe-harbor", salt="fixed")

        assert ds1.StudyInstanceUID == ds2.StudyInstanceUID
        assert ds1.SeriesInstanceUID == ds2.SeriesInstanceUID
        assert ds1.SOPInstanceUID == ds2.SOPInstanceUID

    def test_uid_remapping_changes_uids(self, tmp_path):
        path = _write_dcm(tmp_path / "test.dcm")
        ds = pydicom.dcmread(str(path))
        original_uid = str(ds.StudyInstanceUID)

        ds, _, _ = anonymize_dataset(ds, profile="safe-harbor", salt="test")

        assert str(ds.StudyInstanceUID) != original_uid

    def test_preserves_ml_safe_tags(self, tmp_path):
        path = _write_dcm(tmp_path / "test.dcm")
        ds = pydicom.dcmread(str(path))

        ds, _, _ = anonymize_dataset(ds, profile="safe-harbor", salt="test")

        assert ds.Modality == "CT"
        assert ds.SeriesDescription == "Chest CT"

    def test_keep_tags_option(self, tmp_path):
        path = _write_dcm(tmp_path / "test.dcm")
        ds = pydicom.dcmread(str(path))

        ds, _, _ = anonymize_dataset(
            ds, profile="safe-harbor", keep_tags={"InstitutionName"}, salt="test"
        )

        assert ds.InstitutionName == "Hospital Test"

    def test_unknown_profile_raises(self, tmp_path):
        path = _write_dcm(tmp_path / "test.dcm")
        ds = pydicom.dcmread(str(path))

        with pytest.raises(AnonymizeError, match="Unknown profile"):
            anonymize_dataset(ds, profile="nonexistent")


# ── anonymize_file ───────────────────────────────────────────────────────────


class TestAnonymizeFile:
    def test_writes_output_file(self, tmp_path):
        src = _write_dcm(tmp_path / "input.dcm")
        out_dir = tmp_path / "output"

        result = anonymize_file(src, out_dir, profile="safe-harbor", salt="test")

        assert result.success
        assert result.output_path is not None
        assert result.output_path.exists()

    def test_output_is_anonymized(self, tmp_path):
        src = _write_dcm(tmp_path / "input.dcm")
        out_dir = tmp_path / "output"

        result = anonymize_file(src, out_dir, profile="safe-harbor", salt="test")

        ds = pydicom.dcmread(str(result.output_path))
        assert not hasattr(ds, "PatientName")

    def test_invalid_file_returns_failure(self, tmp_path):
        bad = tmp_path / "bad.dcm"
        bad.write_text("not a dicom file")
        out_dir = tmp_path / "output"

        result = anonymize_file(bad, out_dir, profile="safe-harbor")

        assert not result.success
        assert "Read error" in result.message


# ── anonymize_files ──────────────────────────────────────────────────────────


class TestAnonymizeFiles:
    def test_processes_directory(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        _write_dcm(src_dir / "a.dcm")
        _write_dcm(src_dir / "b.dcm")
        out_dir = tmp_path / "output"

        results = anonymize_files([src_dir], out_dir, profile="safe-harbor", salt="test")

        assert len(results) == 2
        assert all(r.success for r in results)

    def test_progress_callback(self, tmp_path):
        src = _write_dcm(tmp_path / "test.dcm")
        out_dir = tmp_path / "output"
        calls = []

        anonymize_files([src], out_dir, profile="safe-harbor", salt="test",
                        on_progress=calls.append)

        assert len(calls) == 1
        assert calls[0].success

    def test_consistent_uid_across_files(self, tmp_path):
        """Files in the same run should use the same salt for UID remapping."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        # Two files with the same StudyInstanceUID
        _write_dcm(src_dir / "a.dcm")
        _write_dcm(src_dir / "b.dcm")
        out_dir = tmp_path / "output"

        results = anonymize_files([src_dir], out_dir, profile="safe-harbor", salt="test")

        ds_a = pydicom.dcmread(str(results[0].output_path))
        ds_b = pydicom.dcmread(str(results[1].output_path))
        # Same original StudyInstanceUID → same remapped UID
        assert ds_a.StudyInstanceUID == ds_b.StudyInstanceUID
