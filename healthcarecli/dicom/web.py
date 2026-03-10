"""DICOMweb client — QIDO-RS (search), WADO-RS (retrieve), STOW-RS (store).

Supports any DICOMweb-compliant server: Orthanc, DCM4CHEE, Google Cloud
Healthcare API, AWS HealthImaging, etc.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pydicom
import pydicom.datadict
import requests
from dicomweb_client.api import DICOMwebClient

from healthcarecli.config.manager import (
    delete_profile,
    get_profile,
    list_profiles,
    save_profile,
)

SECTION = "dicomweb"


# ── Profile ───────────────────────────────────────────────────────────────────

@dataclass
class DICOMWebProfile:
    """Connection profile for a DICOMweb server."""

    name: str
    url: str                # Base URL, e.g. http://localhost:8042/dicom-web
    qido_prefix: str = ""   # Override QIDO path (leave empty for same base URL)
    wado_prefix: str = ""
    stow_prefix: str = ""
    auth_type: str = "none" # "none" | "basic" | "bearer"
    username: str = ""
    password: str = ""      # stored in plain text; keyring support is future work
    token: str = ""

    # ── persistence ───────────────────────────────────────────────────────

    def save(self) -> None:
        data = asdict(self)
        data.pop("name")
        save_profile(SECTION, self.name, data)

    @classmethod
    def load(cls, name: str) -> "DICOMWebProfile":
        data = get_profile(SECTION, name)
        if data is None:
            raise DICOMWebProfileNotFoundError(name)
        return cls(name=name, **data)

    @classmethod
    def list_all(cls) -> list["DICOMWebProfile"]:
        return [cls(name=n, **v) for n, v in list_profiles(SECTION).items()]

    def delete(self) -> None:
        if not delete_profile(SECTION, self.name):
            raise DICOMWebProfileNotFoundError(self.name)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    # ── client factory ────────────────────────────────────────────────────

    def client(self) -> DICOMwebClient:
        session = requests.Session()
        if self.auth_type == "basic" and self.username:
            session.auth = (self.username, self.password)
        elif self.auth_type == "bearer" and self.token:
            session.headers.update({"Authorization": f"Bearer {self.token}"})

        kwargs: dict[str, Any] = {"url": self.url, "session": session}
        if self.qido_prefix:
            kwargs["qido_url_prefix"] = self.qido_prefix
        if self.wado_prefix:
            kwargs["wado_url_prefix"] = self.wado_prefix
        if self.stow_prefix:
            kwargs["stow_url_prefix"] = self.stow_prefix

        return DICOMwebClient(**kwargs)


class DICOMWebProfileNotFoundError(KeyError):
    def __init__(self, name: str) -> None:
        super().__init__(f"DICOMweb profile '{name}' not found")
        self.name = name


# ── QIDO-RS ───────────────────────────────────────────────────────────────────

_QIDO_METHOD: dict[str, str] = {
    "studies": "search_for_studies",
    "series": "search_for_series",
    "instances": "search_for_instances",
}


def qido_search(
    profile: DICOMWebProfile,
    level: str = "studies",
    filters: dict[str, str] | None = None,
    study_uid: str | None = None,
    series_uid: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """Run a QIDO-RS search and return normalised result dicts.

    Args:
        profile:    DICOMweb server profile.
        level:      "studies" | "series" | "instances"
        filters:    Tag keyword → value match criteria (e.g. {"PatientID": "123"}).
        study_uid:  Required for level=series/instances.
        series_uid: Required for level=instances.
        limit:      Max results returned by the server.
        offset:     Pagination offset.

    Raises:
        DICOMWebError: on HTTP or protocol failure.
    """
    method_name = _QIDO_METHOD.get(level.lower())
    if not method_name:
        raise ValueError(
            f"Invalid QIDO level '{level}'. Choose: studies, series, instances"
        )

    client = profile.client()
    kwargs: dict[str, Any] = {}
    if filters:
        kwargs["search_filters"] = filters
    if study_uid:
        kwargs["study_instance_uid"] = study_uid
    if series_uid:
        kwargs["series_instance_uid"] = series_uid
    if limit is not None:
        kwargs["limit"] = limit
    if offset is not None:
        kwargs["offset"] = offset

    try:
        raw = getattr(client, method_name)(**kwargs)
        return _normalise_qido(raw or [])
    except Exception as exc:
        raise DICOMWebError(f"QIDO-RS failed: {exc}") from exc


def _normalise_qido(results: list[dict]) -> list[dict[str, Any]]:
    """Convert DICOM JSON model (numeric tag keys) to keyword-keyed dicts."""
    out = []
    for item in results:
        row: dict[str, Any] = {}
        for tag, value_obj in item.items():
            keyword = pydicom.datadict.keyword_for_tag(tag)
            key = keyword if keyword else tag
            values = value_obj.get("Value", [])
            if not values:
                row[key] = ""
            elif len(values) == 1:
                v = values[0]
                # Person Name objects: {"Alphabetic": "Smith^John"}
                row[key] = v.get("Alphabetic", str(v)) if isinstance(v, dict) else str(v)
            else:
                row[key] = [
                    v.get("Alphabetic", str(v)) if isinstance(v, dict) else str(v)
                    for v in values
                ]
        out.append(row)
    return out


# ── WADO-RS ───────────────────────────────────────────────────────────────────

def wado_retrieve(
    profile: DICOMWebProfile,
    study_uid: str,
    series_uid: str | None = None,
    instance_uid: str | None = None,
    output_dir: Path = Path("."),
) -> list[Path]:
    """Download DICOM instances via WADO-RS and write .dcm files to output_dir.

    Granularity is determined by the combination of UIDs supplied:
    - study_uid only          → entire study
    - study_uid + series_uid  → one series
    - all three UIDs          → single instance

    Returns:
        List of paths to saved .dcm files.

    Raises:
        DICOMWebError: on HTTP or protocol failure.
    """
    client = profile.client()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if instance_uid and series_uid:
            result = client.retrieve_instance(
                study_instance_uid=study_uid,
                series_instance_uid=series_uid,
                sop_instance_uid=instance_uid,
            )
            datasets = [result] if isinstance(result, pydicom.Dataset) else list(result)
        elif series_uid:
            datasets = list(client.retrieve_series(
                study_instance_uid=study_uid,
                series_instance_uid=series_uid,
            ))
        else:
            datasets = list(client.retrieve_study(study_instance_uid=study_uid))
    except Exception as exc:
        raise DICOMWebError(f"WADO-RS failed: {exc}") from exc

    saved: list[Path] = []
    for ds in datasets:
        uid = str(getattr(ds, "SOPInstanceUID", f"instance_{len(saved)}"))
        out = output_dir / f"{uid}.dcm"
        has_tsyntax = bool(
            getattr(ds, "file_meta", None)
            and getattr(ds.file_meta, "TransferSyntaxUID", None)
        )
        if has_tsyntax:
            ds.save_as(str(out))
        else:
            ds.save_as(str(out), implicit_vr=False, little_endian=True)
        saved.append(out)
    return saved


# ── STOW-RS ───────────────────────────────────────────────────────────────────

@dataclass
class StowResult:
    stored: int
    failed: int
    files: list[dict[str, Any]] = field(default_factory=list)


def stow_store(
    profile: DICOMWebProfile,
    paths: list[Path],
    study_uid: str | None = None,
) -> StowResult:
    """Upload DICOM files to a server via STOW-RS.

    Args:
        profile:   DICOMweb server profile.
        paths:     .dcm files or directories (expanded recursively).
        study_uid: Optional study UID for study-level endpoint.

    Raises:
        DICOMWebError: if the STOW-RS request itself fails.
    """
    from healthcarecli.dicom.store import _collect_files

    all_files = _collect_files(paths)
    if not all_files:
        return StowResult(stored=0, failed=0)

    datasets: list[pydicom.Dataset] = []
    file_results: list[dict[str, Any]] = []

    for p in all_files:
        try:
            datasets.append(pydicom.dcmread(str(p)))
            file_results.append({"file": str(p), "success": True, "error": ""})
        except Exception as exc:
            file_results.append({"file": str(p), "success": False, "error": str(exc)})

    if not datasets:
        return StowResult(stored=0, failed=len(all_files), files=file_results)

    client = profile.client()
    try:
        kwargs: dict[str, Any] = {"datasets": datasets}
        if study_uid:
            kwargs["study_instance_uid"] = study_uid
        client.store_instances(**kwargs)
    except Exception as exc:
        raise DICOMWebError(f"STOW-RS failed: {exc}") from exc

    failed = sum(1 for r in file_results if not r["success"])
    return StowResult(stored=len(datasets), failed=failed, files=file_results)


class DICOMWebError(RuntimeError):
    pass
