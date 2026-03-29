"""Root CLI entry point."""

import typer

from healthcarecli.dataset import cli as dataset_cli
from healthcarecli.dicom import cli as dicom_cli
from healthcarecli.fhir import cli as fhir_cli

app = typer.Typer(
    name="healthcarecli",
    help="Cross-platform CLI for healthcare interoperability — DICOM, FHIR, HL7.",
    no_args_is_help=True,
)

app.add_typer(dataset_cli.app, name="dataset")
app.add_typer(dicom_cli.app, name="dicom")
app.add_typer(fhir_cli.app, name="fhir")


@app.command("init")
def init() -> None:
    """Guided setup wizard — configure your first PACS/FHIR/HL7 connection."""
    from healthcarecli.init_cmd import run_init

    run_init()
