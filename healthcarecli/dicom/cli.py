"""DICOM sub-commands: profile, query, send, listen."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich import print_json
from rich.console import Console
from rich.table import Table

from healthcarecli.dicom.connections import AEProfile, ProfileNotFoundError
from healthcarecli.dicom.echo import DicomEchoError, cecho
from healthcarecli.dicom.query import DicomQueryError, QueryParams, cfind
from healthcarecli.dicom.store import DicomStoreError, SCPServer, StoreResult, csend
from healthcarecli.dicom.web_cli import web_app

app = typer.Typer(help="DICOM operations — profiles, C-FIND, C-STORE, DICOMweb.")
profile_app = typer.Typer(help="Manage DICOM AE connection profiles.")
app.add_typer(profile_app, name="profile")
app.add_typer(web_app, name="web")

console = Console(stderr=True)  # status/errors → stderr; data → stdout


# ── Profile management ────────────────────────────────────────────────────────


@profile_app.command("add")
def profile_add(
    name: str = typer.Argument(..., help="Profile name (e.g. orthanc, dcm4chee)"),
    host: str = typer.Option(..., help="PACS hostname or IP"),
    port: int = typer.Option(..., help="PACS port (e.g. 4242, 11112)"),
    ae_title: str = typer.Option(..., "--ae-title", help="Remote AE title"),
    calling_ae: str = typer.Option("HEALTHCARECLI", "--calling-ae", help="Our local AE title"),
    tls: bool = typer.Option(False, "--tls/--no-tls", help="Enable TLS"),
) -> None:
    """Save a new DICOM AE connection profile."""
    p = AEProfile(
        name=name,
        host=host,
        port=port,
        ae_title=ae_title,
        calling_ae=calling_ae,
        tls=tls,
    )
    p.save()
    console.print(f"[green]Profile '{name}' saved.[/green]")


@profile_app.command("list")
def profile_list(
    output: str = typer.Option("table", "--output", "-o", help="Output format: table|json"),
) -> None:
    """List saved DICOM profiles."""
    profiles = AEProfile.list_all()
    if not profiles:
        console.print("[yellow]No DICOM profiles configured.[/yellow]")
        raise typer.Exit()

    if output == "json":
        print_json(json.dumps([p.to_dict() for p in profiles]))
        return

    table = Table(title="DICOM Profiles")
    for col in ("Name", "Host", "Port", "Remote AE", "Calling AE", "TLS"):
        table.add_column(col)
    for p in profiles:
        table.add_row(p.name, p.host, str(p.port), p.ae_title, p.calling_ae, str(p.tls))
    console.print(table)


@profile_app.command("delete")
def profile_delete(
    name: str = typer.Argument(..., help="Profile name to delete"),
) -> None:
    """Delete a saved DICOM profile."""
    try:
        AEProfile.load(name).delete()
        console.print(f"[green]Profile '{name}' deleted.[/green]")
    except ProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


@profile_app.command("show")
def profile_show(name: str = typer.Argument(...)) -> None:
    """Show details of a single profile."""
    try:
        p = AEProfile.load(name)
        print_json(json.dumps(p.to_dict()))
    except ProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


# ── C-ECHO (ping) ────────────────────────────────────────────────────────────


@app.command("ping")
def ping(
    profile_name: str = typer.Option(..., "--profile", "-p", help="AE profile name"),
    output: str = typer.Option("text", "--output", "-o", help="Output format: text|json"),
) -> None:
    """Verify a PACS connection with C-ECHO."""
    try:
        ae = AEProfile.load(profile_name)
    except ProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    try:
        elapsed = cecho(ae)
    except DicomEchoError as exc:
        if output == "json":
            print_json(json.dumps({"profile": profile_name, "success": False, "error": str(exc)}))
        else:
            console.print(f"[red]FAIL[/red] {ae.ae_title}@{ae.host}:{ae.port} - {exc}")
        raise typer.Exit(1)

    ms = round(elapsed * 1000, 1)
    if output == "json":
        print_json(
            json.dumps(
                {
                    "profile": profile_name,
                    "success": True,
                    "host": ae.host,
                    "port": ae.port,
                    "ae_title": ae.ae_title,
                    "rtt_ms": ms,
                }
            )
        )
    else:
        console.print(f"[green]OK[/green] {ae.ae_title}@{ae.host}:{ae.port} - {ms} ms")


# ── C-FIND ────────────────────────────────────────────────────────────────────


@app.command("query")
def query(
    profile_name: str = typer.Option(..., "--profile", "-p", help="AE profile name"),
    level: str = typer.Option(
        "STUDY", "--level", "-l", help="Query level: PATIENT|STUDY|SERIES|IMAGE"
    ),
    patient_id: str = typer.Option("", "--patient-id"),
    patient_name: str = typer.Option("", "--patient-name"),
    study_date: str = typer.Option("", "--study-date", help="YYYYMMDD or YYYYMMDD-YYYYMMDD range"),
    accession: str = typer.Option("", "--accession"),
    modality: str = typer.Option("", "--modality", help="e.g. CT, MR, US"),
    study_uid: str = typer.Option("", "--study-uid"),
    series_uid: str = typer.Option("", "--series-uid"),
    model: str = typer.Option("STUDY", "--model", help="Query model: STUDY|PATIENT"),
    output: str = typer.Option("table", "--output", "-o", help="Output format: table|json"),
    limit: int | None = typer.Option(None, "--limit", help="Max results to return"),
) -> None:
    """Run a C-FIND query against a PACS."""
    try:
        ae = AEProfile.load(profile_name)
    except ProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    params = QueryParams(
        query_level=level.upper(),
        patient_id=patient_id,
        patient_name=patient_name,
        study_date=study_date,
        accession_number=accession,
        modalities_in_study=modality if level.upper() == "STUDY" else "",
        modality=modality if level.upper() == "SERIES" else "",
        study_instance_uid=study_uid,
        series_instance_uid=series_uid,
    )

    try:
        results = []
        for i, r in enumerate(cfind(ae, params, model=model)):
            results.append(r.data)
            if limit and i + 1 >= limit:
                break
    except DicomQueryError as exc:
        console.print(f"[red]Query failed: {exc}[/red]")
        raise typer.Exit(1)

    if not results:
        console.print("[yellow]No results.[/yellow]")
        raise typer.Exit()

    if output == "json":
        print_json(json.dumps(results))
        return

    # Build table from first result's keys
    table = Table(title=f"C-FIND results ({len(results)})")
    keys = list(results[0].keys())
    for k in keys:
        table.add_column(k, overflow="fold")
    for row in results:
        table.add_row(*[str(row.get(k, "")) for k in keys])
    console.print(table)


# ── C-STORE SCU ───────────────────────────────────────────────────────────────


@app.command("send")
def send(
    profile_name: str = typer.Option(..., "--profile", "-p", help="AE profile name"),
    paths: Annotated[list[Path], typer.Argument(help="DICOM files or directories")] = ...,
    output: str = typer.Option("table", "--output", "-o", help="Output format: table|json"),
) -> None:
    """Send DICOM files to a PACS via C-STORE."""
    try:
        ae = AEProfile.load(profile_name)
    except ProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    sent: list[dict] = []

    def progress(r: StoreResult) -> None:
        icon = "[green]OK[/green]" if r.success else "[red]FAIL[/red]"
        console.print(f"  {icon} {r.path.name} - {r.message}")
        sent.append(
            {
                "file": str(r.path),
                "success": r.success,
                "status": r.status_code,
                "message": r.message,
            }
        )

    try:
        csend(ae, paths, on_progress=progress)
    except DicomStoreError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    ok = sum(1 for r in sent if r["success"])
    console.print(f"\n[bold]{ok}/{len(sent)} files sent successfully.[/bold]")

    if output == "json":
        print_json(json.dumps(sent))

    if ok < len(sent):
        raise typer.Exit(1)


# ── C-STORE SCP (listener) ───────────────────────────────────────────────────


@app.command("listen")
def listen(
    ae_title: str = typer.Option("HEALTHCARECLI", "--ae-title"),
    port: int = typer.Option(11112, "--port"),
    output_dir: Path = typer.Option(Path("received"), "--output-dir", "-d"),
) -> None:
    """Start a C-STORE SCP listener that saves incoming DICOM files to disk."""
    server = SCPServer(ae_title=ae_title, port=port, output_dir=output_dir)
    console.print(
        f"[green]Listening on port {port} as '{ae_title}' → saving to '{output_dir}'[/green]"
    )
    console.print("Press Ctrl+C to stop.")
    server.start()
    try:
        # Block main thread — server runs in daemon thread
        import time

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        console.print(f"\n[yellow]Stopped. Received {len(server.received)} file(s).[/yellow]")
