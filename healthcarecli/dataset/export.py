"""Dataset export — organize DICOM files into ML-ready directory structures with manifests."""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pydicom

# ── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class ExportRecord:
    """Metadata extracted from a single DICOM file."""

    source_path: str
    output_path: str
    patient_id: str = ""
    study_instance_uid: str = ""
    series_instance_uid: str = ""
    sop_instance_uid: str = ""
    study_date: str = ""
    modality: str = ""
    series_description: str = ""
    study_description: str = ""
    body_part: str = ""
    rows: int = 0
    columns: int = 0
    slice_thickness: str = ""
    pixel_spacing: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "output_path": self.output_path,
            "patient_id": self.patient_id,
            "study_instance_uid": self.study_instance_uid,
            "series_instance_uid": self.series_instance_uid,
            "sop_instance_uid": self.sop_instance_uid,
            "study_date": self.study_date,
            "modality": self.modality,
            "series_description": self.series_description,
            "study_description": self.study_description,
            "body_part": self.body_part,
            "rows": self.rows,
            "columns": self.columns,
            "slice_thickness": self.slice_thickness,
            "pixel_spacing": self.pixel_spacing,
        }


@dataclass
class ExportResult:
    """Summary of a dataset export operation."""

    total_files: int = 0
    exported: int = 0
    failed: int = 0
    records: list[ExportRecord] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


class DatasetExportError(RuntimeError):
    pass


# ── Organization strategies ──────────────────────────────────────────────────

STRUCTURES: dict[str, str] = {
    "flat": "All files in output directory",
    "patient-study": "PatientID/StudyInstanceUID/file.dcm",
    "modality-patient": "Modality/PatientID/file.dcm",
    "study-series": "StudyInstanceUID/SeriesInstanceUID/file.dcm",
}


def _get_tag(ds: pydicom.Dataset, keyword: str, default: str = "") -> str:
    """Safely extract a DICOM tag value as string."""
    val = getattr(ds, keyword, None)
    if val is None:
        return default
    return str(val).strip()


def _build_output_path(
    ds: pydicom.Dataset,
    output_dir: Path,
    structure: str,
    original_name: str,
) -> Path:
    """Determine output file path based on organization structure."""
    if structure == "patient-study":
        pid = _get_tag(ds, "PatientID", "UNKNOWN")
        suid = _get_tag(ds, "StudyInstanceUID", "UNKNOWN")
        return output_dir / pid / suid / original_name

    if structure == "modality-patient":
        mod = _get_tag(ds, "Modality", "UNKNOWN")
        pid = _get_tag(ds, "PatientID", "UNKNOWN")
        return output_dir / mod / pid / original_name

    if structure == "study-series":
        suid = _get_tag(ds, "StudyInstanceUID", "UNKNOWN")
        seuid = _get_tag(ds, "SeriesInstanceUID", "UNKNOWN")
        return output_dir / suid / seuid / original_name

    # flat
    return output_dir / original_name


def _extract_record(ds: pydicom.Dataset, source: Path, output: Path) -> ExportRecord:
    """Extract metadata from a DICOM dataset into an ExportRecord."""
    pixel_spacing = _get_tag(ds, "PixelSpacing")
    if pixel_spacing and pixel_spacing.startswith("["):
        # Clean pydicom list representation
        pixel_spacing = pixel_spacing.strip("[]").replace("'", "")

    return ExportRecord(
        source_path=str(source),
        output_path=str(output),
        patient_id=_get_tag(ds, "PatientID"),
        study_instance_uid=_get_tag(ds, "StudyInstanceUID"),
        series_instance_uid=_get_tag(ds, "SeriesInstanceUID"),
        sop_instance_uid=_get_tag(ds, "SOPInstanceUID"),
        study_date=_get_tag(ds, "StudyDate"),
        modality=_get_tag(ds, "Modality"),
        series_description=_get_tag(ds, "SeriesDescription"),
        study_description=_get_tag(ds, "StudyDescription"),
        body_part=_get_tag(ds, "BodyPartExamined"),
        rows=int(_get_tag(ds, "Rows", "0") or "0"),
        columns=int(_get_tag(ds, "Columns", "0") or "0"),
        slice_thickness=_get_tag(ds, "SliceThickness"),
        pixel_spacing=pixel_spacing,
    )


# ── Core export ──────────────────────────────────────────────────────────────


def export_dataset(
    paths: list[Path],
    output_dir: Path,
    *,
    structure: str = "flat",
    copy: bool = True,
    on_progress: Callable[[ExportRecord], None] | None = None,
) -> ExportResult:
    """Export DICOM files to an organized directory with metadata extraction.

    Args:
        paths: DICOM files or directories to export.
        output_dir: Destination directory.
        structure: Organization strategy (flat, patient-study, modality-patient, study-series).
        copy: If True, copy files; if False, create symlinks.
        on_progress: Optional callback per file.

    Returns:
        ExportResult with records and summary.
    """
    if structure not in STRUCTURES:
        raise DatasetExportError(
            f"Unknown structure '{structure}'. Available: {list(STRUCTURES.keys())}"
        )

    files = _collect_dicom_files(paths)
    result = ExportResult(total_files=len(files))

    for fpath in files:
        try:
            ds = pydicom.dcmread(str(fpath), stop_before_pixels=True)
        except Exception as exc:
            result.failed += 1
            result.errors.append({"file": str(fpath), "error": str(exc)})
            continue

        out_path = _build_output_path(ds, output_dir, structure, fpath.name)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if copy:
                shutil.copy2(str(fpath), str(out_path))
            else:
                if out_path.exists():
                    out_path.unlink()
                out_path.symlink_to(fpath.resolve())
        except Exception as exc:
            result.failed += 1
            result.errors.append({"file": str(fpath), "error": f"Copy error: {exc}"})
            continue

        record = _extract_record(ds, fpath, out_path)
        result.records.append(record)
        result.exported += 1

        if on_progress:
            on_progress(record)

    return result


def write_manifest(
    records: list[ExportRecord],
    output_path: Path,
    fmt: str = "csv",
) -> None:
    """Write a manifest file from export records.

    Args:
        records: List of ExportRecord from a dataset export.
        output_path: Path to write manifest.
        fmt: Format — "csv" or "json".
    """
    if fmt == "json":
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump([r.to_dict() for r in records], fh, indent=2)
    else:
        if not records:
            return
        fieldnames = list(records[0].to_dict().keys())
        with output_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for r in records:
                writer.writerow(r.to_dict())


def dataset_stats(records: list[ExportRecord]) -> dict[str, Any]:
    """Compute summary statistics from export records.

    Returns:
        Dict with counts by modality, date range, resolution distribution, etc.
    """
    stats: dict[str, Any] = {
        "total_files": len(records),
        "patients": len({r.patient_id for r in records if r.patient_id}),
        "studies": len({r.study_instance_uid for r in records if r.study_instance_uid}),
        "series": len({r.series_instance_uid for r in records if r.series_instance_uid}),
        "modalities": {},
        "body_parts": {},
        "date_range": {"earliest": "", "latest": ""},
        "resolutions": {},
    }

    dates: list[str] = []
    for r in records:
        # Count modalities
        if r.modality:
            stats["modalities"][r.modality] = stats["modalities"].get(r.modality, 0) + 1
        # Count body parts
        if r.body_part:
            stats["body_parts"][r.body_part] = stats["body_parts"].get(r.body_part, 0) + 1
        # Collect dates
        if r.study_date:
            dates.append(r.study_date)
        # Count resolutions
        if r.rows and r.columns:
            res_key = f"{r.rows}x{r.columns}"
            stats["resolutions"][res_key] = stats["resolutions"].get(res_key, 0) + 1

    if dates:
        dates.sort()
        stats["date_range"]["earliest"] = dates[0]
        stats["date_range"]["latest"] = dates[-1]

    return stats


def _collect_dicom_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("*.dcm")))
        elif p.is_file():
            files.append(p)
    return files
