"""Tests for the DICOM autotuner module (no live PACS required)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from healthcarecli.dicom.autotuner.benchmark import (
    BenchmarkResult,
    _compute_score,
    append_result,
    best_result,
    load_history,
)
from healthcarecli.dicom.autotuner.params import (
    PARAM_SPACE,
    TuningParams,
    grid_size,
    sample_grid_limited,
    sample_random,
)
from healthcarecli.dicom.cli import app

runner = CliRunner()


# ── TuningParams ─────────────────────────────────────────────────────────────


def test_tuning_params_defaults():
    p = TuningParams()
    assert p.maximum_pdu_size == 16382
    assert p.workers == 1


def test_tuning_params_roundtrip():
    p = TuningParams(maximum_pdu_size=65536, workers=4, dimse_timeout=60.0)
    assert TuningParams.from_dict(p.to_dict()) == p


def test_tuning_params_from_dict_ignores_unknown():
    p = TuningParams.from_dict({"maximum_pdu_size": 32768, "unknown_key": "ignored"})
    assert p.maximum_pdu_size == 32768
    assert p.workers == 1  # default


def test_apply_to_ae():
    params = TuningParams(maximum_pdu_size=65536, acse_timeout=10.0, dimse_timeout=20.0, network_timeout=30.0)
    ae = MagicMock()
    params.apply_to_ae(ae)
    assert ae.maximum_pdu_size == 65536
    assert ae.acse_timeout == 10.0
    assert ae.dimse_timeout == 20.0
    assert ae.network_timeout == 30.0


# ── Sampling ──────────────────────────────────────────────────────────────────


def test_sample_random_is_within_bounds():
    for _ in range(20):
        p = sample_random()
        for spec in PARAM_SPACE:
            val = getattr(p, spec["name"])
            assert spec["min"] <= val <= spec["max"], f"{spec['name']}={val} out of bounds"


def test_sample_random_deterministic():
    assert sample_random(seed=42) == sample_random(seed=42)


def test_grid_size_is_positive():
    assert grid_size() > 0


def test_sample_grid_limited():
    pts = sample_grid_limited(5, seed=0)
    assert len(pts) == 5
    assert all(isinstance(p, TuningParams) for p in pts)


# ── Score ─────────────────────────────────────────────────────────────────────


def test_score_zero_on_error():
    assert _compute_score(10.0, 5.0, 1.0, "some error", "") == 0.0
    assert _compute_score(10.0, 5.0, 1.0, "", "echo error") == 0.0


def test_score_zero_on_no_throughput():
    assert _compute_score(10.0, 0.0, 1.0, "", "") == 0.0


def test_score_higher_with_better_tput():
    s1 = _compute_score(10.0, 1.0, 1.0, "", "")
    s2 = _compute_score(10.0, 5.0, 1.0, "", "")
    assert s2 > s1


def test_score_higher_with_lower_rtt():
    s_fast = _compute_score(10.0, 5.0, 1.0, "", "")
    s_slow = _compute_score(500.0, 5.0, 1.0, "", "")
    assert s_fast > s_slow


def test_score_higher_with_speedup():
    s1 = _compute_score(10.0, 5.0, 1.0, "", "")
    s2 = _compute_score(10.0, 5.0, 3.0, "", "")
    assert s2 > s1


# ── BenchmarkResult serialisation ────────────────────────────────────────────


def _make_result(profile_name: str = "test", score: float = 1.0) -> BenchmarkResult:
    return BenchmarkResult(
        profile_name=profile_name,
        timestamp_utc="2026-01-01T00:00:00Z",
        params=TuningParams(maximum_pdu_size=32768, workers=2),
        limit=50,
        echo_rtt_ms=12.5,
        echo_error="",
        cfind_results=10,
        cfind_elapsed_s=2.0,
        cfind_tput=5.0,
        cfind_error="",
        parallel_elapsed_s=1.5,
        parallel_tput=12.0,
        worker_speedup=2.4,
        score=score,
        success=True,
    )


def test_benchmark_result_roundtrip():
    r = _make_result()
    d = r.to_dict()
    r2 = BenchmarkResult.from_dict(d)
    assert r2.params == r.params
    assert r2.score == r.score
    assert r2.profile_name == r.profile_name


def test_benchmark_result_param_prefix_in_dict():
    d = _make_result().to_dict()
    assert "param_maximum_pdu_size" in d
    assert "param_workers" in d
    assert "params" not in d  # should be flattened


def test_benchmark_result_jsonl_line():
    line = _make_result().to_jsonl_line()
    assert line.endswith("\n")
    parsed = json.loads(line)
    assert parsed["profile_name"] == "test"


# ── History persistence ───────────────────────────────────────────────────────


def test_append_and_load_history(tmp_path):
    with patch(
        "healthcarecli.dicom.autotuner.benchmark.config_dir", return_value=tmp_path
    ):
        r1 = _make_result("mypacs", score=2.0)
        r2 = _make_result("mypacs", score=5.0)
        append_result(r1)
        append_result(r2)
        history = load_history("mypacs")

    assert len(history) == 2
    assert history[0].timestamp_utc <= history[1].timestamp_utc  # sorted by time


def test_best_result(tmp_path):
    with patch(
        "healthcarecli.dicom.autotuner.benchmark.config_dir", return_value=tmp_path
    ):
        append_result(_make_result("mypacs", score=1.0))
        append_result(_make_result("mypacs", score=9.0))
        append_result(_make_result("mypacs", score=3.0))
        winner = best_result("mypacs")

    assert winner is not None
    assert winner.score == 9.0


def test_load_history_empty(tmp_path):
    with patch(
        "healthcarecli.dicom.autotuner.benchmark.config_dir", return_value=tmp_path
    ):
        assert load_history("nonexistent") == []


def test_best_result_none_when_no_history(tmp_path):
    with patch(
        "healthcarecli.dicom.autotuner.benchmark.config_dir", return_value=tmp_path
    ):
        assert best_result("nonexistent") is None


# ── CLI wiring ────────────────────────────────────────────────────────────────


def test_show_space_json():
    result = runner.invoke(app, ["autotune", "show-space", "--output", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "knobs" in data
    assert len(data["knobs"]) == len(PARAM_SPACE)
    assert "total_grid_size" in data


def test_show_space_table():
    result = runner.invoke(app, ["autotune", "show-space", "--output", "table"])
    assert result.exit_code == 0
    assert "maximum_pdu_size" in result.output


def test_run_one_requires_profile():
    result = runner.invoke(app, ["autotune", "run-one"])
    assert result.exit_code != 0


def test_history_no_profile_data(tmp_path):
    with patch(
        "healthcarecli.dicom.autotuner.benchmark.config_dir", return_value=tmp_path
    ), patch(
        "healthcarecli.dicom.autotuner.cli.load_history", return_value=[]
    ), patch(
        "healthcarecli.dicom.connections.AEProfile.load",
        return_value=MagicMock(name="x"),
    ):
        result = runner.invoke(app, ["autotune", "history", "--profile", "nope"])
    assert result.exit_code == 0


def test_apply_no_history(tmp_path):
    with patch(
        "healthcarecli.dicom.autotuner.benchmark.config_dir", return_value=tmp_path
    ), patch(
        "healthcarecli.dicom.autotuner.cli.best_result", return_value=None
    ), patch(
        "healthcarecli.dicom.connections.AEProfile.load",
        return_value=MagicMock(name="x"),
    ):
        result = runner.invoke(
            app, ["autotune", "apply", "--profile", "nope", "--from-best"]
        )
    assert result.exit_code == 1
