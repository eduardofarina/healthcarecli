"""FHIR R4 sub-commands: profile, search, get, create, update, delete, capabilities."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich import print_json
from rich.console import Console
from rich.table import Table

from healthcarecli.fhir.client import (
    COMMON_RESOURCE_TYPES,
    FHIRAuthError,
    FHIRError,
    FHIRProfile,
    FHIRProfileNotFoundError,
    bundle_entries,
    bundle_total,
    fhir_capabilities,
    fhir_create,
    fhir_delete,
    fhir_get,
    fhir_search,
    fhir_update,
)
from healthcarecli.fhir.token import (
    build_jwt_assertion,
    cache_token,
    exchange_jwt_for_token,
    generate_rsa_keypair,
    load_cached_token,
    load_private_key,
    save_private_key,
)

app = typer.Typer(help="FHIR R4 — search, read, create, update, delete resources.")
profile_app = typer.Typer(help="Manage FHIR server profiles.")
app.add_typer(profile_app, name="profile")

console = Console(stderr=True)

# ── FHIR resource type completion ──────────────────────────────────────────────


def _complete_resource_type(incomplete: str) -> list[str]:
    return [r for r in COMMON_RESOURCE_TYPES if r.lower().startswith(incomplete.lower())]


# ── Profile management ────────────────────────────────────────────────────────


@profile_app.command("add")
def profile_add(
    name: str = typer.Argument(..., help="Profile name (e.g. hapi, epic-sandbox)"),
    url: str = typer.Option(..., help="FHIR base URL (e.g. https://hapi.fhir.org/baseR4)"),
    auth: str = typer.Option("none", "--auth", help="Auth type: none|basic|bearer|smart"),
    username: str = typer.Option("", "--username", "-u"),
    password: str = typer.Option("", "--password", "-p", hide_input=True),
    token: str = typer.Option("", "--token", "-t", hide_input=True),
    token_url: str = typer.Option("", "--token-url", help="SMART token endpoint"),
    client_id: str = typer.Option("", "--client-id"),
    client_secret: str = typer.Option("", "--client-secret", hide_input=True),
) -> None:
    """Save a FHIR server profile."""
    p = FHIRProfile(
        name=name,
        url=url,
        auth_type=auth,
        username=username,
        password=password,
        token=token,
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
    )
    p.save()
    console.print(f"[green]FHIR profile '{name}' saved.[/green]")


@profile_app.command("list")
def profile_list(
    output: str = typer.Option("table", "--output", "-o", help="table|json"),
) -> None:
    """List saved FHIR profiles."""
    profiles = FHIRProfile.list_all()
    if not profiles:
        console.print("[yellow]No FHIR profiles configured.[/yellow]")
        raise typer.Exit()

    if output == "json":
        print_json(json.dumps([p.to_dict() for p in profiles]))
        return

    table = Table(title="FHIR Profiles")
    for col in ("Name", "URL", "Auth"):
        table.add_column(col)
    for p in profiles:
        table.add_row(p.name, p.url, p.auth_type)
    console.print(table)


@profile_app.command("show")
def profile_show(name: str = typer.Argument(...)) -> None:
    """Show a single FHIR profile (secrets redacted)."""
    try:
        p = FHIRProfile.load(name)
        print_json(json.dumps(p.to_dict()))
    except FHIRProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


@profile_app.command("delete")
def profile_delete(name: str = typer.Argument(...)) -> None:
    """Delete a FHIR profile."""
    try:
        FHIRProfile.load(name).delete()
        console.print(f"[green]Profile '{name}' deleted.[/green]")
    except FHIRProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


# ── Capabilities (ping / metadata) ───────────────────────────────────────────


@app.command("capabilities")
def capabilities(
    profile_name: str = typer.Option(..., "--profile", "-p"),
    output: str = typer.Option("text", "--output", "-o", help="text|json"),
) -> None:
    """Fetch the server CapabilityStatement (confirms server is reachable)."""
    profile = _load_profile(profile_name)
    try:
        cap = fhir_capabilities(profile)
    except (FHIRError, FHIRAuthError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if output == "json":
        print_json(json.dumps(cap))
    else:
        fhir_ver = cap.get("fhirVersion", "?")
        software = cap.get("software", {}).get("name", "?")
        console.print(f"[green]OK[/green] {profile.url} — FHIR {fhir_ver}, software: {software}")


# ── Search ────────────────────────────────────────────────────────────────────


@app.command("search")
def search(
    resource_type: Annotated[
        str,
        typer.Argument(
            help="FHIR resource type (e.g. Patient, Observation)",
            autocompletion=_complete_resource_type,
        ),
    ],
    profile_name: str = typer.Option(..., "--profile", "-p"),
    param: list[str] = typer.Option(
        [],
        "--param",
        "-q",
        help="Search parameter as key=value (repeatable). e.g. --param family=Smith",
    ),
    count: int | None = typer.Option(None, "--count", help="Max results (_count)"),
    offset: int | None = typer.Option(None, "--offset"),
    output: str = typer.Option("table", "--output", "-o", help="table|json|ndjson"),
) -> None:
    """Search for FHIR resources."""
    profile = _load_profile(profile_name)
    params = _parse_params(param)

    try:
        bundle = fhir_search(profile, resource_type, params=params, count=count, offset=offset)
    except FHIRAuthError as exc:
        console.print(f"[red]{exc}[/red]")
        if profile.auth_type == "smart":
            console.print(
                f"[yellow]Token expired or missing. "
                f"Run: healthcarecli fhir token {profile_name}[/yellow]"
            )
        raise typer.Exit(1)
    except FHIRError as exc:
        if exc.status_code == 401 and profile.auth_type == "smart":
            console.print(f"[red]{exc}[/red]")
            console.print(
                f"[yellow]Token expired or missing. "
                f"Run: healthcarecli fhir token {profile_name}[/yellow]"
            )
            raise typer.Exit(1)
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    entries = bundle_entries(bundle)
    total = bundle_total(bundle)

    if not entries:
        console.print("[yellow]No results.[/yellow]")
        raise typer.Exit()

    if output == "json":
        print_json(json.dumps(bundle))
        return

    if output == "ndjson":
        for r in entries:
            sys.stdout.write(json.dumps(r) + "\n")
        return

    # table: flatten top-level scalar fields
    table = Table(title=f"{resource_type} ({total or len(entries)} total)")
    keys = _top_keys(entries)
    for k in keys:
        table.add_column(k, overflow="fold")
    for r in entries:
        table.add_row(*[_cell(r.get(k)) for k in keys])
    console.print(table)


# ── Get ───────────────────────────────────────────────────────────────────────


@app.command("get")
def get(
    ref: str = typer.Argument(
        ..., help="ResourceType/id — e.g. Patient/123 or just '123' with --type"
    ),
    profile_name: str = typer.Option(..., "--profile", "-p"),
    resource_type: str = typer.Option("", "--type", "-t", help="Resource type if not in ref"),
    output: str = typer.Option("json", "--output", "-o", help="json|text"),
) -> None:
    """Read a single FHIR resource."""
    rtype, rid = _parse_ref(ref, resource_type)
    profile = _load_profile(profile_name)

    try:
        resource = fhir_get(profile, rtype, rid)
    except (FHIRError, FHIRAuthError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    print_json(json.dumps(resource))


# ── Create ────────────────────────────────────────────────────────────────────


@app.command("create")
def create(
    profile_name: str = typer.Option(..., "--profile", "-p"),
    file: Path | None = typer.Option(None, "--file", "-f", help="JSON resource file"),
    stdin: bool = typer.Option(False, "--stdin", help="Read resource JSON from stdin"),
    output: str = typer.Option("json", "--output", "-o", help="json|text"),
) -> None:
    """Create a new FHIR resource (POST). Reads JSON from --file or --stdin."""
    resource = _read_resource(file, stdin)
    profile = _load_profile(profile_name)

    try:
        created = fhir_create(profile, resource)
    except (FHIRError, FHIRAuthError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if output == "json":
        print_json(json.dumps(created))
    else:
        rid = created.get("id", "?")
        rtype = created.get("resourceType", "?")
        console.print(f"[green]Created {rtype}/{rid}[/green]")


# ── Update ────────────────────────────────────────────────────────────────────


@app.command("update")
def update(
    ref: str = typer.Argument(..., help="ResourceType/id to update"),
    profile_name: str = typer.Option(..., "--profile", "-p"),
    file: Path | None = typer.Option(None, "--file", "-f"),
    stdin: bool = typer.Option(False, "--stdin"),
    output: str = typer.Option("json", "--output", "-o", help="json|text"),
) -> None:
    """Update a FHIR resource (PUT)."""
    rtype, rid = _parse_ref(ref, "")
    resource = _read_resource(file, stdin)
    profile = _load_profile(profile_name)

    try:
        updated = fhir_update(profile, rtype, rid, resource)
    except (FHIRError, FHIRAuthError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if output == "json":
        print_json(json.dumps(updated))
    else:
        console.print(f"[green]Updated {rtype}/{rid}[/green]")


# ── Delete ────────────────────────────────────────────────────────────────────


@app.command("delete")
def delete(
    ref: str = typer.Argument(..., help="ResourceType/id to delete"),
    profile_name: str = typer.Option(..., "--profile", "-p"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Delete a FHIR resource (DELETE)."""
    rtype, rid = _parse_ref(ref, "")
    if not confirm:
        typer.confirm(f"Delete {rtype}/{rid}?", abort=True)

    profile = _load_profile(profile_name)
    try:
        fhir_delete(profile, rtype, rid)
        console.print(f"[green]Deleted {rtype}/{rid}[/green]")
    except (FHIRError, FHIRAuthError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


# ── Keygen ────────────────────────────────────────────────────────────────────


@app.command("keygen")
def keygen(
    profile_name: str = typer.Argument(..., help="Profile name (e.g. epic-sandbox)"),
) -> None:
    """Generate an RSA-2048 keypair for Backend Services JWT auth.

    Saves the private key locally and prints the public JWK to stdout.
    Paste the JWK into Epic's app registration (JSON Web Keys section).
    """
    private_pem, public_jwk_json = generate_rsa_keypair()
    key_path = save_private_key(profile_name, private_pem)

    # Update or create the profile with the key path recorded
    try:
        profile = FHIRProfile.load(profile_name)
        profile.private_key_path = str(key_path)
        profile.save()
    except FHIRProfileNotFoundError:
        pass  # Profile doesn't exist yet; user should run profile add first

    console.print(f"[green]Private key saved to:[/green] {key_path}")
    console.print()
    console.print("[bold]Public JWK (paste into your Epic app registration):[/bold]")
    console.print()
    # Print JWK to stdout so agents can capture it
    sys.stdout.write(public_jwk_json + "\n")
    console.print()
    console.print(
        "[yellow]Go to https://fhir.epic.com/developer → your app → Edit → "
        "JSON Web Keys → paste the above[/yellow]"
    )


# ── Token ─────────────────────────────────────────────────────────────────────


@app.command("token")
def token_cmd(
    profile_name: str = typer.Argument(..., help="Profile name (e.g. epic-sandbox)"),
    scope: str = typer.Option("system/*.read", "--scope", "-s", help="OAuth2 scope"),
    force: bool = typer.Option(False, "--force", "-f", help="Ignore cache, fetch new token"),
) -> None:
    """Fetch (or return cached) a Backend Services JWT access token.

    Prints the access_token to stdout so agents can capture it:
      TOKEN=$(healthcarecli fhir token epic-sandbox)
    """
    profile = _load_profile(profile_name)

    if profile.auth_type != "smart":
        console.print(
            f"[red]Profile '{profile_name}' auth type is '{profile.auth_type}', "
            f"not 'smart'. Set --auth smart when adding the profile.[/red]"
        )
        raise typer.Exit(1)

    if not profile.token_url or not profile.client_id:
        console.print(
            "[red]Profile is missing token_url or client_id. "
            "Re-add the profile with --token-url and --client-id.[/red]"
        )
        raise typer.Exit(1)

    # Check cache unless forced
    if not force:
        cached = load_cached_token(profile_name)
        if cached:
            sys.stdout.write(cached["access_token"] + "\n")
            return

    # Load private key
    try:
        private_key_pem = load_private_key(profile_name)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    # Build assertion and exchange
    try:
        assertion = build_jwt_assertion(profile.client_id, profile.token_url, private_key_pem)
        token_response = exchange_jwt_for_token(profile.token_url, assertion, scope=scope)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Token exchange failed: {exc}[/red]")
        raise typer.Exit(1)

    cache_token(profile_name, token_response)
    sys.stdout.write(token_response["access_token"] + "\n")


# ── helpers ───────────────────────────────────────────────────────────────────


def _load_profile(name: str) -> FHIRProfile:
    try:
        return FHIRProfile.load(name)
    except FHIRProfileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


def _parse_params(param_list: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for p in param_list:
        if "=" in p:
            k, _, v = p.partition("=")
            params[k.strip()] = v.strip()
    return params


def _parse_ref(ref: str, fallback_type: str) -> tuple[str, str]:
    if "/" in ref:
        rtype, _, rid = ref.partition("/")
        return rtype, rid
    if fallback_type:
        return fallback_type, ref
    console.print("[red]Specify ResourceType/id or use --type.[/red]")
    raise typer.Exit(1)


def _read_resource(file: Path | None, from_stdin: bool) -> dict:
    if file:
        return json.loads(file.read_text(encoding="utf-8"))
    if from_stdin:
        return json.loads(sys.stdin.read())
    console.print("[red]Provide --file or --stdin.[/red]")
    raise typer.Exit(1)


def _top_keys(resources: list[dict]) -> list[str]:
    """Return the most useful top-level scalar keys for table display."""
    priority = [
        "resourceType",
        "id",
        "name",
        "code",
        "status",
        "subject",
        "effectiveDateTime",
        "valueQuantity",
        "birthDate",
        "gender",
    ]
    all_keys: list[str] = []
    for k in priority:
        if any(k in r for r in resources):
            all_keys.append(k)
    return all_keys or list(resources[0].keys())[:6]


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        # FHIR CodeableConcept: {coding: [...], text: "..."}
        if "text" in value:
            return value["text"]
        if "coding" in value and value["coding"]:
            c = value["coding"][0]
            return c.get("display") or c.get("code", str(value))
        # HumanName: [{family, given:[...]}]
        return str(value)
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            # HumanName list
            name = value[0]
            given = " ".join(name.get("given", []))
            family = name.get("family", "")
            return f"{given} {family}".strip() or str(value[0])
        return ", ".join(str(v) for v in value)
    return str(value)
