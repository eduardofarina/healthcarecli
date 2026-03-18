"""TuningParams — the knobs an agent can tune for DICOM extraction."""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, fields
from itertools import product
from typing import Any

# ── Param space spec (machine-readable; consumed by show-space command) ───────

PARAM_SPACE: list[dict[str, Any]] = [
    {
        "name": "maximum_pdu_size",
        "type": "int",
        "default": 16382,
        "min": 4096,
        "max": 131072,
        "step": 4096,
        "note": "PDU size in bytes; larger values reduce round-trips for big datasets",
    },
    {
        "name": "acse_timeout",
        "type": "float",
        "default": 30.0,
        "min": 5.0,
        "max": 120.0,
        "step": 5.0,
        "note": "Association negotiation timeout in seconds",
    },
    {
        "name": "dimse_timeout",
        "type": "float",
        "default": 30.0,
        "min": 5.0,
        "max": 120.0,
        "step": 5.0,
        "note": "DIMSE message response timeout in seconds",
    },
    {
        "name": "network_timeout",
        "type": "float",
        "default": 60.0,
        "min": 10.0,
        "max": 300.0,
        "step": 10.0,
        "note": "Network I/O idle timeout in seconds",
    },
    {
        "name": "workers",
        "type": "int",
        "default": 1,
        "min": 1,
        "max": 16,
        "step": 1,
        "note": "Parallel C-FIND associations; higher values test PACS concurrency",
    },
]

_SPACE_BY_NAME: dict[str, dict] = {s["name"]: s for s in PARAM_SPACE}


# ── TuningParams dataclass ────────────────────────────────────────────────────


@dataclass
class TuningParams:
    """All pynetdicom knobs that affect DICOM extraction performance."""

    maximum_pdu_size: int = 16382
    acse_timeout: float = 30.0
    dimse_timeout: float = 30.0
    network_timeout: float = 60.0
    workers: int = 1

    # ── apply to a live AE ────────────────────────────────────────────────

    def apply_to_ae(self, ae: Any) -> None:
        """Mutate a pynetdicom AE instance with these params."""
        ae.maximum_pdu_size = self.maximum_pdu_size
        ae.acse_timeout = self.acse_timeout
        ae.dimse_timeout = self.dimse_timeout
        ae.network_timeout = self.network_timeout

    # ── serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TuningParams:
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


# ── Sampling ──────────────────────────────────────────────────────────────────


def _knob_values(spec: dict) -> list:
    """Enumerate every value of a knob according to its step."""
    lo, hi, step = spec["min"], spec["max"], spec["step"]
    if spec["type"] == "int":
        return list(range(lo, hi + 1, int(step)))
    # float
    n = round((hi - lo) / step)
    return [round(lo + i * step, 6) for i in range(n + 1)]


def sample_random(seed: int | None = None) -> TuningParams:
    """Draw one TuningParams by independently sampling each knob uniformly."""
    rng = random.Random(seed)
    kwargs: dict[str, Any] = {}
    for spec in PARAM_SPACE:
        values = _knob_values(spec)
        kwargs[spec["name"]] = rng.choice(values)
    return TuningParams(**kwargs)


def sample_grid() -> list[TuningParams]:
    """Return the full Cartesian product of all knob values.

    May be large (product of knob value counts).  Use sample_grid_limited()
    to draw a manageable subset.
    """
    all_values = [_knob_values(s) for s in PARAM_SPACE]
    names = [s["name"] for s in PARAM_SPACE]
    return [TuningParams(**dict(zip(names, combo))) for combo in product(*all_values)]


def sample_grid_limited(n: int, seed: int | None = None) -> list[TuningParams]:
    """Random subsample of n points from the full grid."""
    full = sample_grid()
    rng = random.Random(seed)
    rng.shuffle(full)
    return full[:n]


def grid_size() -> int:
    """Total number of points in the full grid."""
    return math.prod(len(_knob_values(s)) for s in PARAM_SPACE)
