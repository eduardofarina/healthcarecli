"""Tests for dataset export and manifest generation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from healthcarecli.config import manager as mgr
from healthcarecli.dataset.export import (
    STRUCTURES,
    DatasetExportError,
    ExportRecord,
    dataset_stats,
    export_dataset,
    write_manifest,
)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(mgr, "config_dir", lambda: tmp_path)


def _write_dcm(path: Path, **tags) -> Path:
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = tags.get("SOPInstanceUID", "1.2.3.4.5")
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = tags.get("SOPInstanceUID", "1.2.3.4.5")
    ds.StudyInstanceUID = tags.get("StudyInstanceUID", "1.2.3.100")
    ds.SeriesInstanceUID = tags.get("SeriesInstanceUID", "1.2.3.200")
    ds.PatientID = tags.get("PatientID", "PAT001")
    ds.PatientName = tags.get("PatientName", "Doe^John")
    ds.StudyDate = tags.get("StudyDate", "20240101")
    ds.Modality = tags.get("Modality", "CT")
    ds.SeriesDescription = tags.get("SeriesDescription", "Chest CT")
    ds.BodyPartExamined = tags.get("BodyPartExamined", "CHEST")
    ds.Rows = int(tags.get("Rows", 512))
    ds.Columns = int(tags.get("Columns", 512))

    for k, v in tags.items():
        if not hasattr(ds, k):
            setattr(ds, k, v)

    pydicom.dcmwrite(str(path), ds)
    return path


# ── export_dataset ───────────────────────────────────────────────────────────


class TestExportDataset:
    def test_flat_structure(self, tmp_path):
        src = _write_dcm(tmp_path / "test.dcm")
        out = tmp_path / "dataset"

        result = export_dataset([src], out, structure="flat")

        assert result.exported == 1
        assert result.failed == 0
        assert (out / "test.dcm").exists()

    def test_patient_study_structure(self, tmp_path):
        src = _write_dcm(tmp_path / "test.dcm", PatientID="P001", StudyInstanceUID="1.2.3")
        out = tmp_path / "dataset"

        result = export_dataset([src], out, structure="patient-study")

        assert result.exported == 1
        assert (out / "P001" / "1.2.3" / "test.dcm").exists()

    def test_modality_patient_structure(self, tmp_path):
        src = _write_dcm(tmp_path / "test.dcm", Modality="MR", PatientID="P002")
        out = tmp_path / "dataset"

        result = export_dataset([src], out, structure="modality-patient")

        assert result.exported == 1
        assert (out / "MR" / "P002" / "test.dcm").exists()

    def test_study_series_structure(self, tmp_path):
        src = _write_dcm(
            tmp_path / "test.dcm", StudyInstanceUID="1.2.3", SeriesInstanceUID="1.2.4"
        )
        out = tmp_path / "dataset"

        result = export_dataset([src], out, structure="study-series")

        assert result.exported == 1
        assert (out / "1.2.3" / "1.2.4" / "test.dcm").exists()

    def test_directory_input(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        _write_dcm(src_dir / "a.dcm")
        _write_dcm(src_dir / "b.dcm")
        out = tmp_path / "dataset"

        result = export_dataset([src_dir], out, structure="flat")

        assert result.exported == 2
        assert result.total_files == 2

    def test_invalid_file_counted_as_failed(self, tmp_path):
        bad = tmp_path / "bad.dcm"
        bad.write_text("not dicom")
        out = tmp_path / "dataset"

        result = export_dataset([bad], out, structure="flat")

        assert result.failed == 1
        assert result.exported == 0

    def test_unknown_structure_raises(self, tmp_path):
        src = _write_dcm(tmp_path / "test.dcm")
        out = tmp_path / "dataset"

        with pytest.raises(DatasetExportError, match="Unknown structure"):
            export_dataset([src], out, structure="nonexistent")

    def test_progress_callback(self, tmp_path):
        src = _write_dcm(tmp_path / "test.dcm")
        out = tmp_path / "dataset"
        calls = []

        export_dataset([src], out, structure="flat", on_progress=calls.append)

        assert len(calls) == 1
        assert calls[0].modality == "CT"

    def test_symlink_mode(self, tmp_path):
        src = _write_dcm(tmp_path / "test.dcm")
        out = tmp_path / "dataset"

        result = export_dataset([src], out, structure="flat", copy=False)

        out_file = out / "test.dcm"
        assert result.exported == 1
        assert out_file.is_symlink()

    def test_metadata_extraction(self, tmp_path):
        src = _write_dcm(
            tmp_path / "test.dcm",
            PatientID="P100",
            Modality="MR",
            StudyDate="20240315",
            BodyPartExamined="BRAIN",
        )
        out = tmp_path / "dataset"

        result = export_dataset([src], out, structure="flat")

        rec = result.records[0]
        assert rec.patient_id == "P100"
        assert rec.modality == "MR"
        assert rec.study_date == "20240315"
        assert rec.body_part == "BRAIN"


# ── write_manifest ───────────────────────────────────────────────────────────


class TestWriteManifest:
    def test_csv_manifest(self, tmp_path):
        records = [
            ExportRecord(
                source_path="/src/a.dcm",
                output_path="/out/a.dcm",
                patient_id="P001",
                modality="CT",
                study_date="20240101",
            )
        ]
        out = tmp_path / "manifest.csv"

        write_manifest(records, out, fmt="csv")

        assert out.exists()
        with out.open() as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["patient_id"] == "P001"
        assert rows[0]["modality"] == "CT"

    def test_json_manifest(self, tmp_path):
        records = [
            ExportRecord(
                source_path="/src/a.dcm",
                output_path="/out/a.dcm",
                patient_id="P001",
                modality="CT",
            )
        ]
        out = tmp_path / "manifest.json"

        write_manifest(records, out, fmt="json")

        assert out.exists()
        data = json.loads(out.read_text())
        assert len(data) == 1
        assert data[0]["patient_id"] == "P001"

    def test_empty_records_csv(self, tmp_path):
        out = tmp_path / "manifest.csv"
        write_manifest([], out, fmt="csv")
        # Should not create file for empty records
        assert not out.exists()


# ── dataset_stats ────────────────────────────────────────────────────────────


class TestDatasetStats:
    def test_basic_stats(self):
        records = [
            ExportRecord(
                source_path="/a.dcm",
                output_path="/out/a.dcm",
                patient_id="P001",
                study_instance_uid="1.2.3",
                series_instance_uid="1.2.4",
                modality="CT",
                study_date="20240101",
                rows=512,
                columns=512,
            ),
            ExportRecord(
                source_path="/b.dcm",
                output_path="/out/b.dcm",
                patient_id="P002",
                study_instance_uid="1.2.5",
                series_instance_uid="1.2.6",
                modality="MR",
                study_date="20240315",
                rows=256,
                columns=256,
            ),
        ]

        stats = dataset_stats(records)

        assert stats["total_files"] == 2
        assert stats["patients"] == 2
        assert stats["studies"] == 2
        assert stats["modalities"] == {"CT": 1, "MR": 1}
        assert stats["date_range"]["earliest"] == "20240101"
        assert stats["date_range"]["latest"] == "20240315"
        assert stats["resolutions"] == {"512x512": 1, "256x256": 1}

    def test_empty_records(self):
        stats = dataset_stats([])
        assert stats["total_files"] == 0
        assert stats["patients"] == 0
