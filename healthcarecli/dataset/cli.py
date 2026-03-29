"""Dataset CLI — export, manifest, and stats commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich import print_json
from rich.console import Console
from rich.table import Table

from healthcarecli.dataset.export import (
    STRUCTURES,
    DatasetExportError,
    ExportRecord,
    dataset_stats,
    export_dataset,
    write_manifest,
)

app = typer.Typer(help="Dataset operations — export DICOM to ML-ready structures.")

console = Console(stderr=True)


@app.command("export")
def export(
    paths: Annotated[list[Path], typer.Argument(help="DICOM files or directories")] = ...,
    output_dir: Path = typer.Option(Path("dataset"), "--output-dir", "-d", help="Output directory"),
    structure: str = typer.Option(
        "patient-study",
        "--structure",
        "-s",
        help=f"Organization: {', '.join(STRUCTURES.keys())}",
    ),
    manifest: str = typer.Option(
        "csv",
        "--manifest",
        "-m",
        help="Manifest format: csv|json|none",
    ),
    symlink: bool = typer.Option(
        False, "--symlink/--copy", help="Create symlinks instead of copying"
    ),
    output: str = typer.Option("text", "--output", "-o", help="Output format: text|json"),
) -> None:
    """Export DICOM files to an organized directory with metadata manifest."""

    def progress(r: ExportRecord) -> None:
        console.print(f"  [green]OK[/green] {Path(r.source_path).name} → {r.output_path}")

    console.print(f"[bold]Exporting with structure: {structure}[/bold]")

    try:
        result = export_dataset(
            paths,
            output_dir,
            structure=structure,
            copy=not symlink,
            on_progress=progress if output != "json" else None,
        )
    except DatasetExportError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    # Write manifest
    if manifest != "none" and result.records:
        manifest_path = output_dir / f"manifest.{manifest}"
        write_manifest(result.records, manifest_path, fmt=manifest)
        console.print(f"\n[bold]Manifest written → {manifest_path}[/bold]")

    console.print(
        f"\n[bold]{result.exported}/{result.total_files} files exported → {output_dir}[/bold]"
    )

    if result.errors:
        console.print(f"[yellow]{result.failed} file(s) failed.[/yellow]")

    if output == "json":
        print_json(
            json.dumps(
                {
                    "total_files": result.total_files,
                    "exported": result.exported,
                    "failed": result.failed,
                    "output_dir": str(output_dir),
                    "structure": structure,
                    "manifest": manifest,
                    "errors": result.errors,
                }
            )
        )

    if result.failed:
        raise typer.Exit(1)


@app.command("stats")
def stats(
    paths: Annotated[list[Path], typer.Argument(help="DICOM files or directories")] = ...,
    output: str = typer.Option("table", "--output", "-o", help="Output format: table|json"),
) -> None:
    """Show summary statistics for a DICOM dataset."""
    from healthcarecli.dataset.export import _collect_dicom_files, _extract_record

    files = _collect_dicom_files(paths)
    if not files:
        console.print("[yellow]No DICOM files found.[/yellow]")
        raise typer.Exit()

    console.print(f"Scanning {len(files)} files...")

    records: list[ExportRecord] = []
    import pydicom

    for fpath in files:
        try:
            ds = pydicom.dcmread(str(fpath), stop_before_pixels=True)
            records.append(_extract_record(ds, fpath, fpath))
        except Exception:
            pass

    summary = dataset_stats(records)

    if output == "json":
        print_json(json.dumps(summary))
        return

    # Display as rich tables
    console.print("\n[bold]Dataset Summary[/bold]")
    console.print(f"  Files: {summary['total_files']}")
    console.print(f"  Patients: {summary['patients']}")
    console.print(f"  Studies: {summary['studies']}")
    console.print(f"  Series: {summary['series']}")

    if summary["date_range"]["earliest"]:
        console.print(
            f"  Date range: {summary['date_range']['earliest']} → {summary['date_range']['latest']}"
        )

    if summary["modalities"]:
        table = Table(title="Modalities")
        table.add_column("Modality")
        table.add_column("Count", justify="right")
        for mod, cnt in sorted(summary["modalities"].items(), key=lambda x: -x[1]):
            table.add_row(mod, str(cnt))
        console.print(table)

    if summary["body_parts"]:
        table = Table(title="Body Parts")
        table.add_column("Body Part")
        table.add_column("Count", justify="right")
        for bp, cnt in sorted(summary["body_parts"].items(), key=lambda x: -x[1]):
            table.add_row(bp, str(cnt))
        console.print(table)

    if summary["resolutions"]:
        table = Table(title="Resolutions")
        table.add_column("Resolution")
        table.add_column("Count", justify="right")
        for res, cnt in sorted(summary["resolutions"].items(), key=lambda x: -x[1]):
            table.add_row(res, str(cnt))
        console.print(table)
