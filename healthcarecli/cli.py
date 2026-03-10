"""Root CLI entry point."""

import typer

from healthcarecli.dicom import cli as dicom_cli

app = typer.Typer(
    name="healthcarecli",
    help="Cross-platform CLI for healthcare interoperability — DICOM, FHIR, HL7.",
    no_args_is_help=True,
)

app.add_typer(dicom_cli.app, name="dicom")


@app.command("init")
def init() -> None:
    """Guided setup wizard — configure your first PACS/FHIR/HL7 connection."""
    from healthcarecli.init_cmd import run_init
    run_init()
