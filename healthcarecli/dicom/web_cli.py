"""DICOMweb sub-commands: profile, qido, wado, stow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich import print_json
from rich.console import Console
from rich.table import Table

from healthcarecli.dicom.web import (
    DICOMWebError,
    DICOMWebProfile,
    DICOMWebProfileNotFoundError,
    StowResult,
    qido_search,
    stow_store,
    wado_retrieve,
)

web_app = typer.Typer(help="DICOMweb — QIDO-RS search, WADO-RS retrieve, STOW-RS store.")
web_profile_app = typer.Typer(help="Manage DICOMweb server profiles.")
web_app.add_typer(web_profile_app, name="profile")

console = Console(stderr=True)


# ── Profile management ────────────────────────────────────────────────────────

@web_profile_app.command("add")
def web_profile_add(
    name: str = typer.Argument(..., help="Profile name (e.g. orthanc-web, gcp-healthcare)"),
    url: str = typer.Option(..., help="Base DICOMweb URL (e.g. http://localhost:8042/dicom-web)"),
    qido_prefix: str = typer.Option("", "--qido-prefix", help="Override QIDO-RS path prefix"),
    wado_prefix: str = typer.Option("", "--wado-prefix", help="Override WADO-RS path prefix"),
    stow_prefix: str = typer.Option("", "--stow-prefix", help="Override STOW-RS path prefix"),
    auth: str = typer.Option("none", "--auth", help="Auth type: none | basic | bearer"),
    username: str = typer.Option("", "--username", "-u"),
    password: str = typer.Option("", "--password", "-p", hide_input=True),
    token: str = typer.Option("", "--token", "-t", hide_input=True),
) -> None:
    """Save a DICOMweb server profile."""
    p = DICOMWebProfile(
        name=name, url=url,
        qido_prefix=qido_prefix, wado_prefix=wado_prefix, stow_prefix=stow_prefix,
        auth_type=auth, username=username, password=password, token=token,
    )
    p.save()
    console.print(f"[green]DICOMweb profile '{name}' saved.[/green]")


@web_profile_app.command("list")
def web_profile_list(
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
) -> None:
    """List saved DICOMweb profiles."""
    profiles = DICOMWebProfile.list_all()
    if not profiles:
        console.print("[yellow]No DICOMweb profiles configured.[/yellow]")
        raise typer.Exit()

    if output == "json":
        print_json(json.dumps([p.to_dict() for p in profiles]))
        return

    table = Table(title="DICOMweb Profiles")
    for col in ("Name", "URL", "Auth", "QIDO prefix", "WADO prefix", "STOW prefix"):
        table.add_column(col)
    for p in profiles:
        table.add_row(
            p.name, p.url, p.auth_type,
            p.qido_prefix or "-", p.wado_prefix or "-", p.stow_prefix or "-",
        )
    console.print(table)


@web_profile_app.command("show")
def web_profile_show(name: str = typer.Argument(...)) -> None:
    """Show a single DICOMweb profile."""
    try:
        p = DICOMWebProfile.load(name)
        # Redact secrets in display
        d = p.to_dict()
        if d.get("password"):
            d["password"] = "***"
        if d.get("token"):
            d["token"] = "***"
        print_json(json.dumps(d))
    except DICOMWebProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


@web_profile_app.command("delete")
def web_profile_delete(name: str = typer.Argument(...)) -> None:
    """Delete a DICOMweb profile."""
    try:
        DICOMWebProfile.load(name).delete()
        console.print(f"[green]Profile '{name}' deleted.[/green]")
    except DICOMWebProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


# ── QIDO-RS ───────────────────────────────────────────────────────────────────

@web_app.command("qido")
def qido(
    profile_name: str = typer.Option(..., "--profile", "-p"),
    level: str = typer.Option("studies", "--level", "-l",
                               help="Query level: studies | series | instances"),
    patient_id: str = typer.Option("", "--patient-id"),
    patient_name: str = typer.Option("", "--patient-name"),
    study_date: str = typer.Option("", "--study-date", help="YYYYMMDD or YYYYMMDD-YYYYMMDD"),
    study_uid: str = typer.Option("", "--study-uid"),
    series_uid: str = typer.Option("", "--series-uid"),
    accession: str = typer.Option("", "--accession"),
    modality: str = typer.Option("", "--modality"),
    filter: list[str] = typer.Option([], "--filter", "-f",
                                      help="Extra tag=value filter, repeatable"),
    limit: Optional[int] = typer.Option(None, "--limit"),
    offset: Optional[int] = typer.Option(None, "--offset"),
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
) -> None:
    """Search studies/series/instances via QIDO-RS."""
    try:
        profile = DICOMWebProfile.load(profile_name)
    except DICOMWebProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    # Build filter dict from named options + --filter tag=value pairs
    filters: dict[str, str] = {}
    _add_if(filters, "PatientID", patient_id)
    _add_if(filters, "PatientName", patient_name)
    _add_if(filters, "StudyDate", study_date)
    _add_if(filters, "AccessionNumber", accession)
    _add_if(filters, "Modality", modality)
    for f in filter:
        if "=" in f:
            k, _, v = f.partition("=")
            filters[k.strip()] = v.strip()

    try:
        results = qido_search(
            profile, level=level,
            filters=filters or None,
            study_uid=study_uid or None,
            series_uid=series_uid or None,
            limit=limit,
            offset=offset,
        )
    except (DICOMWebError, ValueError) as exc:
        console.print(f"[red]QIDO failed: {exc}[/red]")
        raise typer.Exit(1)

    if not results:
        console.print("[yellow]No results.[/yellow]")
        raise typer.Exit()

    if output == "json":
        print_json(json.dumps(results))
        return

    table = Table(title=f"QIDO-RS {level} ({len(results)} results)")
    keys = list(results[0].keys())
    for k in keys:
        table.add_column(k, overflow="fold")
    for row in results:
        table.add_row(*[str(row.get(k, "")) for k in keys])
    console.print(table)


# ── WADO-RS ───────────────────────────────────────────────────────────────────

@web_app.command("wado")
def wado(
    profile_name: str = typer.Option(..., "--profile", "-p"),
    study_uid: str = typer.Option(..., "--study-uid", help="StudyInstanceUID"),
    series_uid: str = typer.Option("", "--series-uid", help="Restrict to one series"),
    instance_uid: str = typer.Option("", "--instance-uid", help="Retrieve single instance"),
    output_dir: Path = typer.Option(Path("downloaded"), "--output-dir", "-d"),
    output: str = typer.Option("text", "--output", "-o", help="text|json"),
) -> None:
    """Download DICOM instances via WADO-RS."""
    try:
        profile = DICOMWebProfile.load(profile_name)
    except DICOMWebProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    console.print(f"Retrieving from {profile.url} ...")
    try:
        saved = wado_retrieve(
            profile,
            study_uid=study_uid,
            series_uid=series_uid or None,
            instance_uid=instance_uid or None,
            output_dir=output_dir,
        )
    except DICOMWebError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    result = [{"file": str(p)} for p in saved]
    if output == "json":
        print_json(json.dumps({"downloaded": len(saved), "files": result}))
    else:
        for p in saved:
            console.print(f"  [green]saved[/green] {p}")
        console.print(f"\n[bold]{len(saved)} instance(s) downloaded to '{output_dir}'.[/bold]")


# ── STOW-RS ───────────────────────────────────────────────────────────────────

@web_app.command("stow")
def stow(
    profile_name: str = typer.Option(..., "--profile", "-p"),
    paths: Annotated[list[Path], typer.Argument(help="DICOM files or directories")] = ...,
    study_uid: str = typer.Option("", "--study-uid", help="Optional study-level endpoint"),
    output: str = typer.Option("text", "--output", "-o", help="text|json"),
) -> None:
    """Upload DICOM files via STOW-RS."""
    try:
        profile = DICOMWebProfile.load(profile_name)
    except DICOMWebProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    try:
        result: StowResult = stow_store(profile, paths, study_uid=study_uid or None)
    except DICOMWebError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if output == "json":
        print_json(json.dumps({
            "stored": result.stored, "failed": result.failed, "files": result.files,
        }))
    else:
        for f in result.files:
            icon = "[green]OK[/green]" if f["success"] else "[red]FAIL[/red]"
            detail = f.get("error") or "stored"
            console.print(f"  {icon} {Path(f['file']).name} - {detail}")
        console.print(f"\n[bold]{result.stored}/{result.stored + result.failed} files stored.[/bold]")

    if result.failed > 0:
        raise typer.Exit(1)


# ── helpers ───────────────────────────────────────────────────────────────────

def _add_if(d: dict, key: str, value: str) -> None:
    if value:
        d[key] = value
