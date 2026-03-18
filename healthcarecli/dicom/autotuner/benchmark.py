"""Benchmark a TuningParams configuration against a live PACS."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pynetdicom import AE
from pynetdicom.sop_class import (
    StudyRootQueryRetrieveInformationModelFind,
    Verification,
)
from pynetdicom.status import code_to_category

from healthcarecli.config.manager import config_dir
from healthcarecli.dicom.connections import AEProfile
from healthcarecli.dicom.query import QueryParams

from .params import TuningParams

# ── BenchmarkResult ───────────────────────────────────────────────────────────


@dataclass
class BenchmarkResult:
    profile_name: str
    timestamp_utc: str
    params: TuningParams
    limit: int

    # Echo
    echo_rtt_ms: float      # -1.0 on failure
    echo_error: str

    # Sequential C-FIND
    cfind_results: int
    cfind_elapsed_s: float
    cfind_tput: float       # results/sec; 0.0 on error or 0 results
    cfind_error: str

    # Parallel C-FIND (params.workers > 1 only; else mirrors sequential)
    parallel_elapsed_s: float
    parallel_tput: float
    worker_speedup: float   # parallel_tput / cfind_tput; 1.0 when workers==1

    score: float
    success: bool

    # ── serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Inline params with "param_" prefix for easy jq / CSV use
        params_flat = {f"param_{k}": v for k, v in d.pop("params").items()}
        return {**d, **params_flat}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BenchmarkResult:
        param_raw = {k[len("param_"):]: v for k, v in d.items() if k.startswith("param_")}
        rest = {k: v for k, v in d.items() if not k.startswith("param_")}
        valid = {f.name for f in fields(cls)} - {"params"}
        return cls(
            params=TuningParams.from_dict(param_raw),
            **{k: v for k, v in rest.items() if k in valid},
        )

    def to_jsonl_line(self) -> str:
        return json.dumps(self.to_dict()) + "\n"


# ── Score ─────────────────────────────────────────────────────────────────────


def _compute_score(
    echo_rtt_ms: float,
    cfind_tput: float,
    worker_speedup: float,
    cfind_error: str,
    echo_error: str,
) -> float:
    if cfind_error or echo_error:
        return 0.0
    if cfind_tput <= 0.0:
        return 0.0
    echo_rtt_s = echo_rtt_ms / 1000.0
    rtt_penalty = 1.0 + (echo_rtt_s / 0.100)          # 100 ms RTT doubles denominator
    speedup = max(1.0, worker_speedup)
    return round((cfind_tput * speedup) / rtt_penalty, 4)


# ── Low-level PACS helpers ────────────────────────────────────────────────────


def _cecho(profile: AEProfile, params: TuningParams) -> tuple[float, str]:
    """Return (rtt_ms, error_str). rtt_ms = -1.0 on failure."""
    ae = AE(ae_title=profile.calling_ae)
    params.apply_to_ae(ae)
    ae.add_requested_context(Verification)
    t0 = time.perf_counter()
    try:
        assoc = ae.associate(profile.host, profile.port, ae_title=profile.ae_title)
        if not assoc.is_established:
            return -1.0, "Association failed"
        try:
            status = assoc.send_c_echo()
            elapsed = time.perf_counter() - t0
            if status is None:
                return -1.0, "C-ECHO timeout"
            if status.Status != 0x0000:
                return -1.0, f"C-ECHO status 0x{status.Status:04X}"
            return round(elapsed * 1000, 2), ""
        finally:
            assoc.release()
    except Exception as exc:
        return -1.0, str(exc)


def _cfind_count(
    profile: AEProfile,
    params: TuningParams,
    query_params: QueryParams,
    limit: int,
) -> tuple[int, float, str]:
    """Return (result_count, elapsed_s, error_str)."""
    ae = AE(ae_title=profile.calling_ae)
    params.apply_to_ae(ae)
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
    t0 = time.perf_counter()
    try:
        assoc = ae.associate(profile.host, profile.port, ae_title=profile.ae_title)
        if not assoc.is_established:
            return 0, time.perf_counter() - t0, "Association failed"
        count = 0
        try:
            identifier = query_params.to_dataset()
            for status, dataset in assoc.send_c_find(
                identifier, StudyRootQueryRetrieveInformationModelFind
            ):
                if status is None:
                    return count, time.perf_counter() - t0, "Timeout during C-FIND"
                category = code_to_category(status.Status)
                if category == "Failure":
                    return count, time.perf_counter() - t0, f"C-FIND failure 0x{status.Status:04X}"
                if category == "Pending" and dataset is not None:
                    count += 1
                    if count >= limit:
                        break
        finally:
            assoc.release()
        return count, time.perf_counter() - t0, ""
    except Exception as exc:
        return 0, time.perf_counter() - t0, str(exc)


# ── Main benchmark function ───────────────────────────────────────────────────


def run_benchmark(
    profile: AEProfile,
    params: TuningParams,
    *,
    limit: int = 50,
) -> BenchmarkResult:
    """Run a full benchmark of one TuningParams against a live PACS.

    Steps:
    1. C-ECHO to measure RTT.
    2. Sequential C-FIND (STUDY level, no filter) timed for throughput.
    3. If params.workers > 1: run workers parallel C-FINDs, measure aggregate tput.

    Does NOT write to disk — caller calls append_result() if persistence is wanted.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Wildcard STUDY-level query — no filter, just count whatever the PACS returns
    query_params = QueryParams(query_level="STUDY")

    # Step 1 — C-ECHO
    echo_rtt_ms, echo_error = _cecho(profile, params)

    # Step 2 — sequential C-FIND
    seq_count, seq_elapsed, cfind_error = _cfind_count(profile, params, query_params, limit)

    if seq_count == 0 and not cfind_error:
        cfind_error = "no-results: PACS returned 0 studies — benchmark not meaningful"

    cfind_tput = seq_count / seq_elapsed if seq_elapsed > 0 and seq_count > 0 else 0.0

    # Step 3 — parallel C-FIND
    if params.workers > 1 and not cfind_error:
        par_t0 = time.perf_counter()
        total_par_results = 0
        with ThreadPoolExecutor(max_workers=params.workers) as executor:
            futs = [
                executor.submit(_cfind_count, profile, params, query_params, limit)
                for _ in range(params.workers)
            ]
            for fut in as_completed(futs):
                cnt, _, _ = fut.result()
                total_par_results += cnt
        par_elapsed = time.perf_counter() - par_t0
        parallel_tput = total_par_results / par_elapsed if par_elapsed > 0 else 0.0
        worker_speedup = parallel_tput / cfind_tput if cfind_tput > 0 else 1.0
    else:
        par_elapsed = seq_elapsed
        parallel_tput = cfind_tput
        worker_speedup = 1.0

    score = _compute_score(echo_rtt_ms, cfind_tput, worker_speedup, cfind_error, echo_error)

    return BenchmarkResult(
        profile_name=profile.name,
        timestamp_utc=ts,
        params=params,
        limit=limit,
        echo_rtt_ms=echo_rtt_ms,
        echo_error=echo_error,
        cfind_results=seq_count,
        cfind_elapsed_s=round(seq_elapsed, 4),
        cfind_tput=round(cfind_tput, 4),
        cfind_error=cfind_error,
        parallel_elapsed_s=round(par_elapsed, 4),
        parallel_tput=round(parallel_tput, 4),
        worker_speedup=round(worker_speedup, 4),
        score=score,
        success=not cfind_error and not echo_error,
    )


# ── History persistence ───────────────────────────────────────────────────────


def _history_path(profile_name: str) -> Path:
    p = config_dir() / "autotuner"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{profile_name}.jsonl"


def append_result(result: BenchmarkResult) -> None:
    with _history_path(result.profile_name).open("a", encoding="utf-8") as fh:
        fh.write(result.to_jsonl_line())


def load_history(profile_name: str) -> list[BenchmarkResult]:
    path = _history_path(profile_name)
    if not path.exists():
        return []
    results: list[BenchmarkResult] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            results.append(BenchmarkResult.from_dict(json.loads(line)))
        except Exception:
            pass  # skip corrupt lines silently
    return sorted(results, key=lambda r: r.timestamp_utc)


def best_result(profile_name: str) -> BenchmarkResult | None:
    history = load_history(profile_name)
    if not history:
        return None
    return max(history, key=lambda r: r.score)
