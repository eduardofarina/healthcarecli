"""DICOM C-STORE SCU — send one or more DICOM files to a PACS.

Also exposes a minimal C-STORE SCP (listener) for receiving files.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pydicom
from pydicom import Dataset
from pynetdicom import AE, AllStoragePresentationContexts, evt
from pynetdicom.sop_class import Verification

from healthcarecli.dicom.connections import AEProfile

# ── C-STORE SCU ──────────────────────────────────────────────────────────────


@dataclass
class StoreResult:
    path: Path
    success: bool
    status_code: int | None = None
    message: str = ""


class DicomStoreError(RuntimeError):
    pass


def csend(
    profile: AEProfile,
    paths: list[Path],
    *,
    on_progress: Callable[[StoreResult], None] | None = None,
) -> list[StoreResult]:
    """Send DICOM files to a remote PACS via C-STORE.

    Args:
        profile:     PACS connection profile.
        paths:       List of .dcm file paths (or directories — expanded recursively).
        on_progress: Optional callback invoked for each file after it is sent.

    Returns:
        List of StoreResult, one per file attempted.

    Raises:
        DicomStoreError: if the association cannot be established.
    """
    files = _collect_files(paths)
    if not files:
        return []

    ae = AE(ae_title=profile.calling_ae)
    # Request only the SOP classes actually present in the files (DICOM limits
    # associations to 128 presentation contexts).
    seen_sop_classes: set[str] = set()
    for fpath in files:
        try:
            ds = pydicom.dcmread(str(fpath), stop_before_pixels=True)
            if hasattr(ds, "SOPClassUID"):
                seen_sop_classes.add(str(ds.SOPClassUID))
        except Exception:
            pass
    for sop_class in seen_sop_classes:
        ae.add_requested_context(sop_class)

    assoc = ae.associate(
        profile.host,
        profile.port,
        ae_title=profile.ae_title,
    )
    if not assoc.is_established:
        raise DicomStoreError(
            f"Could not associate with {profile.ae_title}@{profile.host}:{profile.port}"
        )

    results: list[StoreResult] = []
    try:
        for fpath in files:
            result = _send_one(assoc, fpath)
            results.append(result)
            if on_progress:
                on_progress(result)
    finally:
        assoc.release()

    return results


def _send_one(assoc, fpath: Path) -> StoreResult:
    try:
        ds = pydicom.dcmread(str(fpath))
    except Exception as exc:
        return StoreResult(path=fpath, success=False, message=f"Read error: {exc}")

    status = assoc.send_c_store(ds)
    if status is None:
        return StoreResult(path=fpath, success=False, message="No response (timeout)")

    code = status.Status
    success = code == 0x0000
    return StoreResult(
        path=fpath,
        success=success,
        status_code=code,
        message="OK" if success else f"Status 0x{code:04X}",
    )


def _collect_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("*.dcm")))
        elif p.is_file():
            files.append(p)
    return files


# ── C-STORE SCP (listener) ───────────────────────────────────────────────────


@dataclass
class SCPServer:
    """Minimal C-STORE SCP that writes received DICOM files to a directory.

    Usage::

        server = SCPServer(ae_title="MYSCP", port=11112, output_dir=Path("/tmp/dcm"))
        server.start()          # non-blocking
        ...
        server.stop()
    """

    ae_title: str = "HEALTHCARECLI"
    port: int = 11112
    output_dir: Path = field(default_factory=lambda: Path.cwd() / "received")
    received: list[Path] = field(default_factory=list, init=False)

    _ae: AE = field(default=None, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

        ae = AE(ae_title=self.ae_title)
        ae.supported_contexts = AllStoragePresentationContexts
        ae.add_supported_context(Verification)

        handlers = [(evt.EVT_C_STORE, self._handle_store)]

        self._ae = ae
        self._thread = threading.Thread(
            target=ae.start_server,
            args=(("", self.port),),
            kwargs={"evt_handlers": handlers, "block": True},
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._ae:
            self._ae.shutdown()

    def _handle_store(self, event: evt.Event) -> int:
        ds: Dataset = event.dataset
        ds.file_meta = event.file_meta

        uid = getattr(ds, "SOPInstanceUID", "unknown")
        out_path = self.output_dir / f"{uid}.dcm"
        ds.save_as(str(out_path), write_like_original=False)
        self.received.append(out_path)
        return 0x0000  # Success
