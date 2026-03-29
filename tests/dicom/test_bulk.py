"""Tests for bulk DICOM operations — batch query and parallel send."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pydicom
import pytest
from pydicom import Dataset
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from healthcarecli.config import manager as mgr
from healthcarecli.dicom.bulk import (
    BatchQueryResult,
    BatchQueryRow,
    ParallelSendResult,
    batch_query,
    parallel_send,
    parse_batch_file,
)
from healthcarecli.dicom.connections import AEProfile
from healthcarecli.dicom.query import QueryParams, QueryResult


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(mgr, "config_dir", lambda: tmp_path)


def _make_profile(**kwargs):
    defaults = dict(name="test", host="127.0.0.1", port=4242, ae_title="TEST")
    defaults.update(kwargs)
    return AEProfile(**defaults)


def _write_dcm(path: Path) -> Path:
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


# ── parse_batch_file ─────────────────────────────────────────────────────────


class TestParseBatchFile:
    def test_csv_with_patient_id(self, tmp_path):
        csv_file = tmp_path / "queries.csv"
        csv_file.write_text("patient_id,modality\nPAT001,CT\nPAT002,MR\n")

        rows = parse_batch_file(csv_file)

        assert len(rows) == 2
        assert rows[0].params.patient_id == "PAT001"
        assert rows[0].params.modalities_in_study == "CT"
        assert rows[1].params.patient_id == "PAT002"
        assert rows[1].line == 3

    def test_csv_with_dicom_tag_names(self, tmp_path):
        csv_file = tmp_path / "queries.csv"
        csv_file.write_text("PatientID,StudyDate\nP001,20240101\nP002,20240315\n")

        rows = parse_batch_file(csv_file)

        assert len(rows) == 2
        assert rows[0].params.patient_id == "P001"
        assert rows[0].params.study_date == "20240101"

    def test_tsv_file(self, tmp_path):
        tsv_file = tmp_path / "queries.tsv"
        tsv_file.write_text("patient_id\tmodality\nPAT001\tCT\n")

        rows = parse_batch_file(tsv_file)

        assert len(rows) == 1
        assert rows[0].params.patient_id == "PAT001"

    def test_empty_values_ignored(self, tmp_path):
        csv_file = tmp_path / "queries.csv"
        csv_file.write_text("patient_id,modality\nPAT001,\n")

        rows = parse_batch_file(csv_file)

        assert rows[0].params.patient_id == "PAT001"
        assert rows[0].params.modalities_in_study == ""

    def test_level_column(self, tmp_path):
        csv_file = tmp_path / "queries.csv"
        csv_file.write_text("patient_id,level\nPAT001,SERIES\n")

        rows = parse_batch_file(csv_file)

        assert rows[0].params.query_level == "SERIES"


# ── batch_query ──────────────────────────────────────────────────────────────


class TestBatchQuery:
    @patch("healthcarecli.dicom.bulk.cfind")
    def test_successful_batch(self, mock_cfind):
        mock_cfind.side_effect = [
            iter([QueryResult(data={"PatientID": "P001", "Modality": "CT"})]),
            iter([QueryResult(data={"PatientID": "P002", "Modality": "MR"})]),
        ]

        profile = _make_profile()
        rows = [
            BatchQueryRow(line=2, params=QueryParams(patient_id="P001"), raw={}),
            BatchQueryRow(line=3, params=QueryParams(patient_id="P002"), raw={}),
        ]

        result = batch_query(profile, rows)

        assert result.total_queries == 2
        assert result.successful == 2
        assert result.total_results == 2

    @patch("healthcarecli.dicom.bulk.cfind")
    def test_failed_query_counted(self, mock_cfind):
        from healthcarecli.dicom.query import DicomQueryError

        mock_cfind.side_effect = DicomQueryError("Connection failed")

        profile = _make_profile()
        rows = [BatchQueryRow(line=2, params=QueryParams(patient_id="P001"), raw={})]

        result = batch_query(profile, rows)

        assert result.failed == 1
        assert result.successful == 0
        assert len(result.errors) == 1

    @patch("healthcarecli.dicom.bulk.cfind")
    def test_limit_per_query(self, mock_cfind):
        mock_cfind.return_value = iter([
            QueryResult(data={"PatientID": "P001"}),
            QueryResult(data={"PatientID": "P002"}),
            QueryResult(data={"PatientID": "P003"}),
        ])

        profile = _make_profile()
        rows = [BatchQueryRow(line=2, params=QueryParams(), raw={})]

        result = batch_query(profile, rows, limit_per_query=2)

        assert result.total_results == 2

    @patch("healthcarecli.dicom.bulk.cfind")
    def test_progress_callback(self, mock_cfind):
        mock_cfind.return_value = iter([])
        calls = []

        profile = _make_profile()
        rows = [BatchQueryRow(line=2, params=QueryParams(), raw={})]

        batch_query(profile, rows, on_progress=lambda c, t, r: calls.append((c, t, r)))

        assert len(calls) == 1
        assert calls[0] == (1, 1, 0)

    @patch("healthcarecli.dicom.bulk.cfind")
    def test_results_tagged_with_query_line(self, mock_cfind):
        mock_cfind.return_value = iter([
            QueryResult(data={"PatientID": "P001"}),
        ])

        profile = _make_profile()
        rows = [BatchQueryRow(line=5, params=QueryParams(patient_id="P001"), raw={})]

        result = batch_query(profile, rows)

        assert result.results[0]["_query_line"] == 5


# ── parallel_send ────────────────────────────────────────────────────────────


class TestParallelSend:
    @patch("healthcarecli.dicom.bulk.csend")
    def test_parallel_send_splits_work(self, mock_csend, tmp_path):
        from healthcarecli.dicom.store import StoreResult

        # Mock csend to return success for each file
        def mock_send(profile, paths):
            return [
                StoreResult(path=p, success=True, status_code=0, message="OK") for p in paths
            ]

        mock_csend.side_effect = mock_send

        # Create test files
        for i in range(4):
            _write_dcm(tmp_path / f"file{i}.dcm")

        profile = _make_profile()
        result = parallel_send(profile, [tmp_path], workers=2)

        assert result.total_files == 4
        assert result.successful == 4
        assert result.failed == 0

    @patch("healthcarecli.dicom.bulk.csend")
    def test_empty_input(self, mock_csend, tmp_path):
        profile = _make_profile()
        result = parallel_send(profile, [tmp_path / "empty"], workers=2)

        assert result.total_files == 0
        mock_csend.assert_not_called()

    @patch("healthcarecli.dicom.bulk.csend")
    def test_progress_callback(self, mock_csend, tmp_path):
        from healthcarecli.dicom.store import StoreResult

        mock_csend.return_value = [
            StoreResult(path=tmp_path / "test.dcm", success=True, status_code=0, message="OK")
        ]
        _write_dcm(tmp_path / "test.dcm")

        calls = []
        profile = _make_profile()
        parallel_send(profile, [tmp_path], workers=1, on_progress=calls.append)

        assert len(calls) == 1
