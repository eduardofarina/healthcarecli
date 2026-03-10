# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

`healthcarecli` is a cross-platform Python CLI that gives AI agents skills for interacting with healthcare systems — DICOM imaging networks, FHIR REST APIs, and HL7 v2 messaging. The design philosophy mirrors tools like `gcloud` or `obsidian-cli`: a structured, scriptable interface that agents can call as subprocesses or import as a library.

## Architecture

```
healthcarecli/
├── healthcarecli/
│   ├── cli.py              # Root CLI group (Click/Typer entry point)
│   ├── dicom/              # DICOM module (pynetdicom + pydicom)
│   │   ├── connections.py  # SCU/SCP connection profiles
│   │   ├── query.py        # C-FIND, C-MOVE, C-GET operations
│   │   ├── store.py        # C-STORE SCP server
│   │   └── utils.py
│   ├── fhir/               # FHIR R4 module (fhirclient)
│   │   ├── client.py       # Base FHIR client, auth (OAuth2/SMART)
│   │   ├── resources.py    # Patient, Observation, etc. helpers
│   │   └── search.py       # FHIR search parameter builders
│   ├── hl7/                # HL7 v2 messaging (hl7apy or python-hl7)
│   │   ├── mllp.py         # MLLP sender/listener
│   │   ├── messages.py     # ADT, ORM, ORU message builders
│   │   └── parser.py       # HL7 parsing utilities
│   └── config/
│       ├── manager.py      # Config file management (~/.healthcarecli/)
│       └── profiles.py     # Named connection profiles (DICOM AEs, FHIR servers, HL7 endpoints)
├── tests/
├── pyproject.toml
└── README.md
```

## Technology Choices

| Concern | Library | Rationale |
|---|---|---|
| CLI framework | `typer` (over `click`) | Type-annotated, auto-generates help, supports completion |
| DICOM networking | `pynetdicom` | Pure Python DIMSE; no dcmtk dependency required for cross-platform |
| DICOM file I/O | `pydicom` | Standard library for reading/writing DICOM datasets |
| FHIR | `fhirclient` | Official SMART Health IT Python client |
| HL7 v2 | `hl7apy` | Validation-aware; supports v2.5–v2.8 |
| Config storage | `platformdirs` | XDG/AppData-aware config/data paths on all platforms |
| Output formatting | `rich` | Structured tables and JSON output for agent-readable responses |

## Common Commands

```bash
# Install in development mode
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/dicom/test_query.py -v

# Run tests matching a pattern
pytest -k "test_cfind"

# Lint
ruff check healthcarecli/
ruff format healthcarecli/

# Type check
mypy healthcarecli/

# Build distribution
python -m build
```

## CLI Usage Patterns

Commands follow the pattern `healthcarecli <module> <action> [options]`:

```bash
# DICOM — save a connection profile
healthcarecli dicom profile add orthanc --host 127.0.0.1 --port 4242 --ae-title ORTHANC

# DICOM — C-FIND worklist query
healthcarecli dicom query --profile orthanc --level STUDY --patient-id "12345"

# DICOM — C-STORE send file
healthcarecli dicom send --profile orthanc path/to/image.dcm

# FHIR — save a server profile
healthcarecli fhir profile add hapi --url https://hapi.fhir.org/baseR4

# FHIR — search patients
healthcarecli fhir search Patient --profile hapi --param "family=Smith"

# HL7 — send an ADT^A01 message via MLLP
healthcarecli hl7 send --host 127.0.0.1 --port 2575 message.hl7
```

## Config & Profiles

Connection profiles are stored in the platform-appropriate config directory:
- Linux/macOS: `~/.config/healthcarecli/profiles.json`
- Windows: `%APPDATA%\healthcarecli\profiles.json`

`config/manager.py` uses `platformdirs.user_config_dir("healthcarecli")` to resolve paths.

## Key Design Decisions

- **Agent-first output**: All commands support `--output json` for machine-readable responses. Default human-readable output uses `rich`.
- **No dcmtk dependency**: `pynetdicom` is used exclusively for DICOM networking to avoid platform-specific binary dependencies. If dcmtk wrappers are added later, they must be optional.
- **FHIR version**: Target FHIR R4 (4.0.1). R5 support may be added as optional.
- **HL7 MLLP**: The `hl7 send` command wraps messages in MLLP framing (`\x0b` start block, `\x1c\x0d` end block).
- **Async**: Long-running operations (DICOM C-MOVE, MLLP listener) use `asyncio`; short operations are synchronous.
