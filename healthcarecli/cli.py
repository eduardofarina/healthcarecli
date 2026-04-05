"""Root CLI entry point."""

from __future__ import annotations

import typer
from rich.console import Console

from healthcarecli.dataset import cli as dataset_cli
from healthcarecli.dicom import cli as dicom_cli
from healthcarecli.fhir import cli as fhir_cli

VERSION = "0.1.0"

BANNER_LINES = [
    "  _   _            _ _   _                            ___ _     ___ ",
    " | | | | ___  __ _| | |_| |__   ___ __ _ _ __ ___   / __| |   |_ _|",
    " | |_| |/ _ \\/ _` | | __| '_ \\ / __/ _` | '__/ _ \\ | |  | |    | | ",
    " |  _  |  __| (_| | | |_| | | | (_| (_| | | |  __/ | |__| |___ | | ",
    " |_| |_|\\___|\\__,_|_|\\__|_| |_|\\___\\__,_|_|  \\___|  \\___|_____|___|",
]


def _print_banner() -> None:
    console = Console()
    console.print()
    for line in BANNER_LINES:
        console.print(line, style="bold blue", highlight=False)
    console.print()
    console.print(f"  v{VERSION}", style="bright_green")
    console.print("  DICOM  |  FHIR  |  HL7\n", style="dim")


app = typer.Typer(
    name="healthcarecli",
    help="Cross-platform CLI for healthcare interoperability — DICOM, FHIR, HL7.",
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool | None = typer.Option(
        None, "--version", "-v", help="Show version and exit.", is_eager=True
    ),
) -> None:
    """Cross-platform CLI for healthcare interoperability — DICOM, FHIR, HL7."""
    if version:
        _print_banner()
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        _print_banner()
        console = Console()
        console.print(ctx.get_help())
        raise typer.Exit()


app.add_typer(dataset_cli.app, name="dataset")
app.add_typer(dicom_cli.app, name="dicom")
app.add_typer(fhir_cli.app, name="fhir")


@app.command("init")
def init() -> None:
    """Guided setup wizard — configure your first PACS/FHIR/HL7 connection."""
    from healthcarecli.init_cmd import run_init

    run_init()
