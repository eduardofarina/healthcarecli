"""CLI subcommands for DICOM autotune.

Usage pattern (agent-driven exploration):

    # 1. Understand the parameter space
    healthcarecli dicom autotune show-space

    # 2. Run single experiments (agent picks params each time)
    healthcarecli dicom autotune run-one --profile orthanc \\
        --pdu-size 65536 --workers 4 --output json

    # 3. Check history
    healthcarecli dicom autotune history --profile orthanc --sort-by score --output json

    # 4. Lock in winner
    healthcarecli dicom autotune apply --profile orthanc --from-best

Or let the sweeper run autonomously:
    healthcarecli dicom autotune sweep --profile orthanc --n 30 --strategy random
"""

from __future__ import annotations

import json

import typer
from rich import print_json
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from healthcarecli.config.manager import get_profile, save_profile
from healthcarecli.dicom.connections import AEProfile, ProfileNotFoundError

from .benchmark import (
    BenchmarkResult,
    append_result,
    best_result,
    load_history,
    run_benchmark,
)
from .params import (
    PARAM_SPACE,
    TuningParams,
    grid_size,
    sample_grid_limited,
    sample_random,
)

autotune_app = typer.Typer(
    help=(
        "Auto-tune pynetdicom parameters against a live PACS.\n\n"
        "Inspired by Karpathy/autoresearch: run experiments, measure throughput, "
        "find the optimal config for each specific PACS."
    )
)
console = Console(stderr=True)

AUTOTUNER_SECTION = "autotuner"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_profile(name: str) -> AEProfile:
    try:
        return AEProfile.load(name)
    except ProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


def _print_result_text(result: BenchmarkResult) -> None:
    status = "[green]OK[/green]" if result.success else "[red]FAIL[/red]"
    echo = f"{result.echo_rtt_ms:.1f} ms" if result.echo_rtt_ms >= 0 else "n/a"
    console.print(
        f"{status}  score=[bold]{result.score:.4f}[/bold]  "
        f"echo={echo}  cfind_tput={result.cfind_tput:.2f}/s  "
        f"speedup={result.worker_speedup:.2f}x  "
        f"params=pdu={result.params.maximum_pdu_size} "
        f"dimse={result.params.dimse_timeout}s "
        f"workers={result.params.workers}"
    )
    if result.echo_error:
        console.print(f"  echo_error: {result.echo_error}")
    if result.cfind_error:
        console.print(f"  cfind_error: {result.cfind_error}")


# ── run-one ───────────────────────────────────────────────────────────────────


@autotune_app.command("run-one")
def run_one(
    profile_name: str = typer.Option(..., "--profile", "-p", help="AE profile name"),
    pdu_size: int = typer.Option(16382, "--pdu-size", help="PDU size in bytes"),
    acse_timeout: float = typer.Option(30.0, "--acse-timeout"),
    dimse_timeout: float = typer.Option(30.0, "--dimse-timeout"),
    network_timeout: float = typer.Option(60.0, "--network-timeout"),
    workers: int = typer.Option(1, "--workers", help="Parallel associations"),
    limit: int = typer.Option(50, "--limit", help="Max C-FIND results per association"),
    no_save: bool = typer.Option(False, "--no-save", help="Skip persisting result"),
    output: str = typer.Option("text", "--output", "-o", help="text|json"),
) -> None:
    """Run a single benchmark with explicit parameter values.

    This is the primitive an agent calls in a loop to explore the param space.
    Results are appended to history unless --no-save is passed.
    """
    profile = _load_profile(profile_name)
    params = TuningParams(
        maximum_pdu_size=pdu_size,
        acse_timeout=acse_timeout,
        dimse_timeout=dimse_timeout,
        network_timeout=network_timeout,
        workers=workers,
    )

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
        prog.add_task(f"Benchmarking {profile.ae_title}@{profile.host}:{profile.port}…")
        result = run_benchmark(profile, params, limit=limit)

    if not no_save:
        append_result(result)

    if output == "json":
        print_json(json.dumps(result.to_dict()))
    else:
        _print_result_text(result)

    raise typer.Exit(0 if result.success else 1)


# ── sweep ─────────────────────────────────────────────────────────────────────


@autotune_app.command("sweep")
def sweep(
    profile_name: str = typer.Option(..., "--profile", "-p"),
    strategy: str = typer.Option("random", "--strategy", help="random|grid"),
    n: int = typer.Option(20, "--n", help="Number of trials (random) or grid subsample"),
    limit: int = typer.Option(50, "--limit"),
    seed: int | None = typer.Option(None, "--seed"),
    output: str = typer.Option("text", "--output", "-o", help="text|json"),
) -> None:
    """Run N benchmarks using sampled parameter combinations.

    Each result is saved to history as it completes — Ctrl+C won't lose progress.

    Example (let the agent loose for 50 random trials):
        healthcarecli dicom autotune sweep --profile orthanc --n 50 --strategy random
    """
    profile = _load_profile(profile_name)

    if strategy == "grid":
        total = grid_size()
        candidates = sample_grid_limited(min(n, total), seed)
    else:
        candidates = [sample_random(seed=seed if i == 0 else None) for i in range(n)]

    results: list[BenchmarkResult] = []

    console.print(
        f"[bold]Sweeping {len(candidates)} configurations against "
        f"{profile.ae_title}@{profile.host}:{profile.port}[/bold]"
    )

    for i, params in enumerate(candidates, 1):
        console.print(
            f"  [{i}/{len(candidates)}] pdu={params.maximum_pdu_size} "
            f"dimse={params.dimse_timeout}s workers={params.workers} … ",
            end="",
        )
        result = run_benchmark(profile, params, limit=limit)
        append_result(result)
        results.append(result)

        score_str = f"score={result.score:.4f}"
        status = "[green]OK[/green]" if result.success else "[red]FAIL[/red]"
        console.print(f"{status} {score_str}")

    results.sort(key=lambda r: r.score, reverse=True)

    if output == "json":
        print_json(json.dumps([r.to_dict() for r in results]))
        return

    # Summary table — top 5
    console.print(f"\n[bold]Top results (best of {len(results)}):[/bold]")
    table = Table()
    for col in ("Rank", "Score", "PDU", "DIMSE (s)", "Workers", "CFIND tput", "Speedup", "OK"):
        table.add_column(col)
    for rank, r in enumerate(results[:5], 1):
        table.add_row(
            str(rank),
            f"{r.score:.4f}",
            str(r.params.maximum_pdu_size),
            str(r.params.dimse_timeout),
            str(r.params.workers),
            f"{r.cfind_tput:.2f}/s",
            f"{r.worker_speedup:.2f}x",
            "Y" if r.success else "N",
        )
    console.print(table)
    console.print(
        "\n[dim]Run [bold]healthcarecli dicom autotune apply --profile "
        f"{profile_name} --from-best[/bold] to lock in the winner.[/dim]"
    )


# ── history ───────────────────────────────────────────────────────────────────


@autotune_app.command("history")
def history_cmd(
    profile_name: str = typer.Option(..., "--profile", "-p"),
    limit: int = typer.Option(20, "--limit", help="Max entries to show"),
    sort_by: str = typer.Option("score", "--sort-by", help="score|timestamp"),
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
) -> None:
    """Show benchmark history for a profile."""
    history = load_history(profile_name)
    if not history:
        console.print(f"[yellow]No autotune history for profile '{profile_name}'.[/yellow]")
        raise typer.Exit()

    if sort_by == "score":
        history.sort(key=lambda r: r.score, reverse=True)
    else:
        history.sort(key=lambda r: r.timestamp_utc, reverse=True)

    history = history[:limit]
    best_score = max(r.score for r in history)

    if output == "json":
        print_json(json.dumps([r.to_dict() for r in history]))
        return

    table = Table(title=f"Autotune history — {profile_name} (top {len(history)})")
    for col in ("Timestamp", "PDU", "ACSE(s)", "DIMSE(s)", "NET(s)", "W",
                "Echo(ms)", "Tput(/s)", "Speedup", "Score", "OK"):
        table.add_column(col, no_wrap=True)

    for r in history:
        style = "bold green" if r.score == best_score and r.score > 0 else ""
        table.add_row(
            r.timestamp_utc[:19],
            str(r.params.maximum_pdu_size),
            str(r.params.acse_timeout),
            str(r.params.dimse_timeout),
            str(r.params.network_timeout),
            str(r.params.workers),
            f"{r.echo_rtt_ms:.1f}" if r.echo_rtt_ms >= 0 else "n/a",
            f"{r.cfind_tput:.2f}",
            f"{r.worker_speedup:.2f}x",
            f"{r.score:.4f}",
            "Y" if r.success else "N",
            style=style,
        )

    console.print(table)


# ── apply ─────────────────────────────────────────────────────────────────────


@autotune_app.command("apply")
def apply_cmd(
    profile_name: str = typer.Option(..., "--profile", "-p"),
    from_best: bool = typer.Option(
        True, "--from-best/--no-from-best", help="Apply highest-scoring result from history"
    ),
    pdu_size: int | None = typer.Option(None, "--pdu-size"),
    acse_timeout: float | None = typer.Option(None, "--acse-timeout"),
    dimse_timeout: float | None = typer.Option(None, "--dimse-timeout"),
    network_timeout: float | None = typer.Option(None, "--network-timeout"),
    workers: int | None = typer.Option(None, "--workers"),
    output: str = typer.Option("text", "--output", "-o"),
) -> None:
    """Persist the best (or supplied) TuningParams to profiles config.

    Stored under section 'autotuner' with the profile name as key.
    Read back with: healthcarecli dicom autotune show-space --profile <name>
    """
    if from_best:
        winner = best_result(profile_name)
        if winner is None:
            console.print(
                f"[red]No history for '{profile_name}'. Run a sweep first.[/red]"
            )
            raise typer.Exit(1)
        params = winner.params
    else:
        defaults = TuningParams()
        params = TuningParams(
            maximum_pdu_size=pdu_size if pdu_size is not None else defaults.maximum_pdu_size,
            acse_timeout=acse_timeout if acse_timeout is not None else defaults.acse_timeout,
            dimse_timeout=dimse_timeout if dimse_timeout is not None else defaults.dimse_timeout,
            network_timeout=(
                network_timeout if network_timeout is not None else defaults.network_timeout
            ),
            workers=workers if workers is not None else defaults.workers,
        )

    existing_raw = get_profile(AUTOTUNER_SECTION, profile_name)
    save_profile(AUTOTUNER_SECTION, profile_name, params.to_dict())

    if output == "json":
        print_json(json.dumps({"profile": profile_name, "applied": params.to_dict()}))
        return

    console.print(f"[green]Applied tuning params for '{profile_name}':[/green]")
    table = Table()
    table.add_column("Parameter")
    table.add_column("Old")
    table.add_column("New")
    old_params = TuningParams.from_dict(existing_raw) if existing_raw else TuningParams()
    for f_name, old_val, new_val in [
        ("maximum_pdu_size", old_params.maximum_pdu_size, params.maximum_pdu_size),
        ("acse_timeout", old_params.acse_timeout, params.acse_timeout),
        ("dimse_timeout", old_params.dimse_timeout, params.dimse_timeout),
        ("network_timeout", old_params.network_timeout, params.network_timeout),
        ("workers", old_params.workers, params.workers),
    ]:
        style = "green" if old_val != new_val else ""
        table.add_row(f_name, str(old_val), str(new_val), style=style)
    console.print(table)


# ── show-space ────────────────────────────────────────────────────────────────


@autotune_app.command("show-space")
def show_space(
    profile_name: str | None = typer.Option(
        None, "--profile", "-p",
        help="If given, also shows the currently applied params for this profile"
    ),
    output: str = typer.Option("json", "--output", "-o", help="json|table"),
) -> None:
    """Print the parameter space spec — what knobs exist and their valid ranges.

    Agents should call this first to understand what to sample before exploring.
    """
    current: dict | None = None
    if profile_name:
        current = get_profile(AUTOTUNER_SECTION, profile_name)

    space_with_current = []
    for spec in PARAM_SPACE:
        entry = dict(spec)
        if current:
            entry["current_value"] = current.get(spec["name"], spec["default"])
        space_with_current.append(entry)

    payload = {
        "knobs": space_with_current,
        "total_grid_size": grid_size(),
        "agent_workflow": [
            "healthcarecli dicom autotune show-space --output json",
            "healthcarecli dicom autotune run-one --profile <name> --pdu-size <v> --output json",
            "healthcarecli dicom autotune history --profile <name> --sort-by score --output json",
            "healthcarecli dicom autotune apply --profile <name> --from-best",
        ],
    }

    if output == "json":
        print_json(json.dumps(payload))
        return

    table = Table(title="Autotune parameter space")
    cols = ["Name", "Type", "Default", "Min", "Max", "Step", "Note"]
    if current:
        cols.append("Current")
    for col in cols:
        table.add_column(col)

    for entry in space_with_current:
        row = [
            entry["name"],
            entry["type"],
            str(entry["default"]),
            str(entry["min"]),
            str(entry["max"]),
            str(entry["step"]),
            entry["note"],
        ]
        if current:
            row.append(str(entry.get("current_value", entry["default"])))
        table.add_row(*row)

    console.print(table)
    console.print(f"\n[dim]Total grid size: {grid_size():,} combinations[/dim]")
