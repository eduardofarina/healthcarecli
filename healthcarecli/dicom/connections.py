"""DICOM AE connection profiles — save, load, and validate PACS targets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from healthcarecli.config.manager import (
    delete_profile,
    get_profile,
    list_profiles,
    save_profile,
)

SECTION = "dicom"


@dataclass
class AEProfile:
    """Application Entity connection profile for a remote PACS node."""

    name: str
    host: str
    port: int
    ae_title: str  # remote AE title
    calling_ae: str = "HEALTHCARECLI"  # our local AE title
    tls: bool = False

    # ── persistence ───────────────────────────────────────────────────────

    def save(self) -> None:
        data = asdict(self)
        data.pop("name")
        save_profile(SECTION, self.name, data)

    @classmethod
    def load(cls, name: str) -> "AEProfile":
        data = get_profile(SECTION, name)
        if data is None:
            raise ProfileNotFoundError(name)
        return cls(name=name, **data)

    @classmethod
    def list_all(cls) -> list["AEProfile"]:
        return [
            cls(name=n, **v) for n, v in list_profiles(SECTION).items()
        ]

    def delete(self) -> None:
        if not delete_profile(SECTION, self.name):
            raise ProfileNotFoundError(self.name)

    # ── helpers ───────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:  # pragma: no cover
        tls_flag = " [TLS]" if self.tls else ""
        return (
            f"{self.name}: {self.calling_ae} → {self.ae_title}@"
            f"{self.host}:{self.port}{tls_flag}"
        )


class ProfileNotFoundError(KeyError):
    def __init__(self, name: str) -> None:
        super().__init__(f"DICOM profile '{name}' not found")
        self.name = name
