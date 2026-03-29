"""Bulk DICOM operations — batch queries and parallel file transfers."""

from __future__ import annotations

import csv
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from healthcarecli.dicom.connections import AEProfile
from healthcarecli.dicom.query import DicomQueryError, QueryParams, cfind
from healthcarecli.dicom.store import DicomStoreError, StoreResult, csend

# ── Batch Query ──────────────────────────────────────────────────────────────


@dataclass
class BatchQueryRow:
    """A single row from a batch query input file."""

    line: int
    params: QueryParams
    raw: dict[str, str]


@dataclass
class BatchQueryResult:
    """Results of a batch query operation."""

    total_queries: int = 0
    successful: int = 0
    failed: int = 0
    total_results: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


class BulkOperationError(RuntimeError):
    pass


# Column name → QueryParams field mapping
_CSV_FIELD_MAP: dict[str, str] = {
    "patient_id": "patient_id",
    "PatientID": "patient_id",
    "patient_name": "patient_name",
    "PatientName": "patient_name",
    "study_date": "study_date",
    "StudyDate": "study_date",
    "accession": "accession_number",
    "AccessionNumber": "accession_number",
    "modality": "modalities_in_study",
    "Modality": "modalities_in_study",
    "study_uid": "study_instance_uid",
    "StudyInstanceUID": "study_instance_uid",
    "series_uid": "series_instance_uid",
    "SeriesInstanceUID": "series_instance_uid",
    "level": "query_level",
    "QueryRetrieveLevel": "query_level",
}


def parse_batch_file(path: Path) -> list[BatchQueryRow]:
    """Parse a CSV/TSV file into BatchQueryRow objects.

    Expected columns match DICOM tag names or snake_case equivalents.
    """
    rows: list[BatchQueryRow] = []

    with path.open("r", encoding="utf-8") as fh:
        # Auto-detect delimiter
        sample = fh.read(4096)
        fh.seek(0)
        delimiter = "\t" if "\t" in sample else ","

        reader = csv.DictReader(fh, delimiter=delimiter)
        for i, row in enumerate(reader, start=2):  # line 1 = header
            kwargs: dict[str, str] = {}
            for col, val in row.items():
                if col and col.strip() in _CSV_FIELD_MAP and val and val.strip():
                    kwargs[_CSV_FIELD_MAP[col.strip()]] = val.strip()

            params = QueryParams(**kwargs) if kwargs else QueryParams()
            rows.append(BatchQueryRow(line=i, params=params, raw=dict(row)))

    return rows


def batch_query(
    profile: AEProfile,
    rows: list[BatchQueryRow],
    *,
    model: str = "STUDY",
    limit_per_query: int | None = None,
    on_progress: Callable[[int, int, int], None] | None = None,
) -> BatchQueryResult:
    """Execute multiple C-FIND queries from a batch file.

    Args:
        profile: PACS connection profile.
        rows: List of BatchQueryRow from parse_batch_file().
        model: Query model (STUDY or PATIENT).
        limit_per_query: Max results per individual query.
        on_progress: Callback(query_index, total_queries, results_so_far).

    Returns:
        BatchQueryResult with all results.
    """
    result = BatchQueryResult(total_queries=len(rows))

    for idx, row in enumerate(rows):
        try:
            query_results: list[dict[str, Any]] = []
            for i, qr in enumerate(cfind(profile, row.params, model=model)):
                query_results.append(qr.data)
                if limit_per_query and i + 1 >= limit_per_query:
                    break

            # Tag each result with the query line number
            for r in query_results:
                r["_query_line"] = row.line

            result.results.extend(query_results)
            result.total_results += len(query_results)
            result.successful += 1

        except DicomQueryError as exc:
            result.failed += 1
            result.errors.append({"line": str(row.line), "error": str(exc)})

        if on_progress:
            on_progress(idx + 1, len(rows), result.total_results)

    return result


# ── Parallel Send ────────────────────────────────────────────────────────────


@dataclass
class ParallelSendResult:
    """Results of a parallel send operation."""

    total_files: int = 0
    successful: int = 0
    failed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)


def parallel_send(
    profile: AEProfile,
    paths: list[Path],
    *,
    workers: int = 4,
    on_progress: Callable[[StoreResult], None] | None = None,
) -> ParallelSendResult:
    """Send DICOM files to a PACS using multiple parallel associations.

    Each worker opens its own DICOM association and sends a subset of files.

    Args:
        profile: PACS connection profile.
        paths: DICOM files or directories.
        workers: Number of parallel workers.
        on_progress: Optional callback per file.

    Returns:
        ParallelSendResult.
    """
    files = _collect_files(paths)
    if not files:
        return ParallelSendResult()

    # Split files into chunks for each worker
    chunks = [files[i::workers] for i in range(workers)]
    # Remove empty chunks
    chunks = [c for c in chunks if c]

    result = ParallelSendResult(total_files=len(files))

    def _send_chunk(chunk: list[Path]) -> list[StoreResult]:
        return csend(profile, chunk)

    with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
        futures = {executor.submit(_send_chunk, chunk): chunk for chunk in chunks}

        for future in as_completed(futures):
            try:
                chunk_results = future.result()
                for sr in chunk_results:
                    entry = {
                        "file": str(sr.path),
                        "success": sr.success,
                        "status": sr.status_code,
                        "message": sr.message,
                    }
                    result.results.append(entry)
                    if sr.success:
                        result.successful += 1
                    else:
                        result.failed += 1
                    if on_progress:
                        on_progress(sr)
            except DicomStoreError as exc:
                # Entire chunk failed (association error)
                for fpath in futures[future]:
                    result.failed += 1
                    result.results.append(
                        {"file": str(fpath), "success": False, "status": None, "message": str(exc)}
                    )

    return result


def _collect_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("*.dcm")))
        elif p.is_file():
            files.append(p)
    return files
