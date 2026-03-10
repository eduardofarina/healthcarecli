"""healthcarecli init — guided first-run setup wizard."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from healthcarecli.config.manager import config_dir
from healthcarecli.dicom.connections import AEProfile

console = Console()


def run_init() -> None:
    """Interactive first-run setup wizard."""
    console.print(
        Panel(
            "[bold]healthcarecli[/bold] — Healthcare Interoperability CLI\n"
            "This wizard will help you configure your first connection.",
            title="Setup",
            border_style="blue",
        )
    )

    cfg = config_dir()
    console.print(f"\nConfig directory: [cyan]{cfg}[/cyan]")

    # ── DICOM profile ────────────────────────────────────────────────────────
    if Confirm.ask("\nConfigure a DICOM / PACS connection?", default=True):
        _setup_dicom()

    console.print("\n[green]Setup complete.[/green]")
    console.print("Run [bold]healthcarecli dicom --help[/bold] to get started.")
    console.print("Run [bold]healthcarecli dicom profile list[/bold] to see saved profiles.")


def _setup_dicom() -> None:
    console.print("\n[bold]DICOM / PACS connection[/bold]")

    name = Prompt.ask("  Profile name", default="my-pacs")
    host = Prompt.ask("  Host / IP")
    port = int(Prompt.ask("  Port", default="4242"))
    ae_title = Prompt.ask("  Remote AE title", default="ORTHANC")
    calling_ae = Prompt.ask("  Our AE title (calling)", default="HEALTHCARECLI")

    profile = AEProfile(
        name=name,
        host=host,
        port=port,
        ae_title=ae_title,
        calling_ae=calling_ae,
    )
    profile.save()
    console.print(f"  [green]Profile '{name}' saved.[/green]")

    if Confirm.ask("  Test the connection with C-ECHO now?", default=True):
        _echo_test(profile)


def _echo_test(profile: AEProfile) -> None:
    from healthcarecli.dicom.echo import DicomEchoError, cecho

    console.print(f"  Pinging {profile.ae_title}@{profile.host}:{profile.port} ...", end=" ")
    try:
        ms = round(cecho(profile) * 1000, 1)
        console.print(f"[green]OK[/green] ({ms} ms)")
    except DicomEchoError as exc:
        console.print(f"[yellow]Could not reach PACS: {exc}[/yellow]")
        console.print("  Profile saved — you can test later with:")
        console.print(f"    [bold]healthcarecli dicom ping --profile {profile.name}[/bold]")
