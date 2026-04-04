# healthcarecli

A cross-platform CLI for healthcare interoperability — DICOM, FHIR, and HL7 messaging.
Designed to be called by **AI agents** and humans alike.

```
healthcarecli dicom query --profile orthanc --patient-id 12345 --output json
```

---

## Install

```bash
npm install -g healthcarecli
```

> Requires Node.js >=18 and Python >=3.10.
> The npm postinstall step automatically runs `pip install healthcarecli`.

### Alternative (Python-only, no Node.js needed)

```bash
pipx install healthcarecli   # recommended Python-only install
pip install healthcarecli    # or plain pip
```

### From source (development)

```bash
git clone https://github.com/eduardofarina/healthcarecli
cd healthcarecli
pip install -e ".[dev]"
```

---

## Quick start

```bash
# 1. Run the guided setup wizard
healthcarecli init

# 2. Add a PACS connection profile
healthcarecli dicom profile add orthanc \
  --host 127.0.0.1 --port 4242 --ae-title ORTHANC

# 3. Verify the connection
healthcarecli dicom ping --profile orthanc

# 4. Query studies
healthcarecli dicom query --profile orthanc --level STUDY --output json

# 5. Send a DICOM file
healthcarecli dicom send --profile orthanc /path/to/study.dcm
```

---

## DICOM commands

```
healthcarecli dicom --help

Commands:
  profile        Manage PACS connection profiles (add, list, show, delete)
  ping           Verify a PACS connection with C-ECHO
  query          C-FIND — search for patients, studies, series, or instances
  send           C-STORE SCU — send DICOM files to a PACS
  listen         C-STORE SCP — receive incoming DICOM files
  move           C-MOVE SCU — retrieve studies/series to a destination AE
  anonymize      De-identify DICOM files — remove PHI tags
  batch-query    Run multiple C-FIND queries from a CSV/TSV file
  parallel-send  Send DICOM files using multiple parallel associations
  autotune       Benchmark and optimize pynetdicom parameters for a PACS
  web            DICOMweb operations (QIDO-RS, WADO-RS, STOW-RS)
```

### Profiles

```bash
healthcarecli dicom profile add orthanc \
  --host 127.0.0.1 --port 4242 --ae-title ORTHANC

healthcarecli dicom profile list
healthcarecli dicom profile show orthanc
healthcarecli dicom profile delete orthanc
```

Profiles are stored in:

| Platform | Path |
|---|---|
| Linux / macOS | `~/.config/healthcarecli/profiles.json` |
| Windows | `%APPDATA%\healthcarecli\profiles.json` |

### C-ECHO (ping)

```bash
healthcarecli dicom ping --profile orthanc
```

### C-FIND (query)

```bash
# All studies for a patient
healthcarecli dicom query --profile orthanc --patient-id 12345

# CT studies in a date range
healthcarecli dicom query --profile orthanc \
  --study-date 20240101-20241231 --modality CT

# Series within a study (JSON output for agents)
healthcarecli dicom query --profile orthanc \
  --level SERIES --study-uid 1.2.3.4 --output json

# Available options
healthcarecli dicom query --help
```

### C-STORE (send)

```bash
# Send a single file
healthcarecli dicom send --profile orthanc image.dcm

# Send an entire study directory (recursive)
healthcarecli dicom send --profile orthanc /path/to/study/

# JSON result per file (for agents)
healthcarecli dicom send --profile orthanc /path/to/study/ --output json
```

### SCP listener

```bash
# Listen for incoming DICOM on port 11112, save to ./received/
healthcarecli dicom listen --port 11112 --output-dir ./received
```

### C-MOVE (retrieve)

```bash
# Retrieve an entire study to a destination AE
healthcarecli dicom move --profile orthanc \
  --destination MY_SCP --study-uid 1.2.840.10008.5.1.4.1.1.4

# Retrieve a single series
healthcarecli dicom move --profile orthanc \
  --destination MY_SCP --study-uid 1.2.3 --series-uid 4.5.6 --output json
```

---

## FHIR R4 commands

```
healthcarecli fhir --help

Commands:
  profile       Manage FHIR server profiles (add, list, show, delete)
  capabilities  Fetch the server CapabilityStatement (confirms reachability)
  search        Search for FHIR resources
  get           Read a single FHIR resource
  create        Create a new FHIR resource (POST)
  update        Update a FHIR resource (PUT)
  delete        Delete a FHIR resource (DELETE)
```

### Profiles

```bash
# Public HAPI test server (no auth)
healthcarecli fhir profile add hapi --url https://hapi.fhir.org/baseR4

# Bearer token
healthcarecli fhir profile add myserver \
  --url https://fhir.example.com --auth bearer --token <token>

# SMART on FHIR client credentials
healthcarecli fhir profile add epic \
  --url https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4 \
  --auth smart \
  --token-url https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token \
  --client-id <id> --client-secret <secret>
```

### Search

```bash
healthcarecli fhir search Patient --profile hapi --output json
healthcarecli fhir search Patient --profile hapi \
  --param family=Smith --param birthdate=1990-01-01
healthcarecli fhir search Observation --profile hapi \
  --param subject=Patient/123 --count 20 --output ndjson
```

### CRUD

```bash
healthcarecli fhir get Patient/123 --profile hapi
healthcarecli fhir create --profile hapi --file patient.json
healthcarecli fhir update Patient/123 --profile hapi --file updated.json
healthcarecli fhir delete Patient/123 --profile hapi --yes
```

### Anonymize (de-identify)

```bash
# Anonymize a single file
healthcarecli dicom anonymize input.dcm --output-dir ./anon/

# Anonymize a directory of DICOM files
healthcarecli dicom anonymize /path/to/study/ --output-dir ./anon/

# Use a specific de-identification profile
healthcarecli dicom anonymize /path/to/study/ --output-dir ./anon/ --profile safe-harbor

# Keep specific tags (e.g. InstitutionName)
healthcarecli dicom anonymize /path/to/study/ --output-dir ./anon/ --keep-tag InstitutionName

# Preserve dates (useful for longitudinal studies)
healthcarecli dicom anonymize /path/to/study/ --output-dir ./anon/ --keep-dates
```

### Bulk operations

```bash
# Batch query — run multiple C-FIND queries from a CSV file
healthcarecli dicom batch-query --profile orthanc queries.csv --output json

# Parallel send — faster uploads using multiple associations
healthcarecli dicom parallel-send --profile orthanc /path/to/study/ --workers 4
```

### Autotune (benchmark & optimize)

```bash
# Sweep N parameter combinations to find the best settings
healthcarecli dicom autotune sweep --profile orthanc --iterations 20

# View benchmark history
healthcarecli dicom autotune history --profile orthanc

# Apply the best parameters to your profile
healthcarecli dicom autotune apply --profile orthanc

# Show tunable parameter ranges
healthcarecli dicom autotune show-space
```

---

## DICOMweb commands (QIDO-RS / WADO-RS / STOW-RS)

For PACS that expose a DICOMweb endpoint (Orthanc, DCM4CHEE, Google Cloud Healthcare, AWS HealthImaging, etc.).

```
healthcarecli dicom web --help

Commands:
  profile  Manage DICOMweb server profiles (add, list, show, delete)
  qido     Search studies/series/instances via QIDO-RS
  wado     Download DICOM instances via WADO-RS
  stow     Upload DICOM files via STOW-RS
```

### DICOMweb profiles

```bash
# Plain (no auth)
healthcarecli dicom web profile add orthanc-web \
  --url http://localhost:8042/dicom-web

# Basic auth
healthcarecli dicom web profile add dcm4chee \
  --url http://dcm4chee:8080/dcm4chee-arc/aets/DCM4CHEE/rs \
  --auth basic --username admin --password secret

# Bearer token (Google Cloud Healthcare, AWS, etc.)
healthcarecli dicom web profile add gcp \
  --url https://healthcare.googleapis.com/v1/projects/P/datasets/D/dicomStores/S/dicomWeb \
  --auth bearer --token $(gcloud auth print-access-token)

# Separate QIDO / WADO / STOW prefixes (some DCM4CHEE configs)
healthcarecli dicom web profile add dcm4chee-split \
  --url http://dcm4chee:8080 \
  --qido-prefix /dcm4chee-arc/aets/DCM4CHEE/rs \
  --wado-prefix /dcm4chee-arc/aets/DCM4CHEE/rs \
  --stow-prefix /dcm4chee-arc/aets/DCM4CHEE/rs
```

### QIDO-RS (search)

```bash
# All studies for a patient
healthcarecli dicom web qido --profile orthanc-web --patient-id 12345

# CT studies in a date range
healthcarecli dicom web qido --profile orthanc-web \
  --study-date 20240101-20241231 --modality CT --output json

# Series within a study
healthcarecli dicom web qido --profile orthanc-web \
  --level series --study-uid 1.2.3.4 --output json

# Instances within a series
healthcarecli dicom web qido --profile orthanc-web \
  --level instances --study-uid 1.2.3.4 --series-uid 1.2.3.4.5 --output json

# Arbitrary tag filter
healthcarecli dicom web qido --profile orthanc-web \
  --level studies --filter "00080060=CT" --limit 20
```

### WADO-RS (download)

```bash
# Download entire study
healthcarecli dicom web wado --profile orthanc-web \
  --study-uid 1.2.3.4 --output-dir ./study/

# Download one series
healthcarecli dicom web wado --profile orthanc-web \
  --study-uid 1.2.3.4 --series-uid 1.2.3.4.5 --output-dir ./series/

# Download single instance
healthcarecli dicom web wado --profile orthanc-web \
  --study-uid 1.2.3.4 --series-uid 1.2.3.4.5 --instance-uid 1.2.3.4.5.6 \
  --output-dir ./
```

### STOW-RS (upload)

```bash
# Upload files or a directory
healthcarecli dicom web stow --profile orthanc-web /path/to/study/
healthcarecli dicom web stow --profile orthanc-web image.dcm --output json
```

---

## For AI agents

Every command supports `--output json` for machine-readable output.
The CLI exits with code `0` on success, `1` on error — safe to use in scripts.

For Claude Code integration, copy the agent skill:

```bash
mkdir -p ~/.claude/skills/healthcarecli
cp SKILL.md ~/.claude/skills/healthcarecli/SKILL.md
```

Then prompt your agent: _"Use the healthcarecli tool to query the orthanc PACS for all CT studies from last month."_

---

## Dataset commands (ML export)

```bash
# Export DICOM files to a flat directory with CSV manifest
healthcarecli dataset export /path/to/dicoms/ --output-dir ./dataset/ --structure flat

# Organize by patient/study
healthcarecli dataset export /path/to/dicoms/ --output-dir ./dataset/ --structure patient-study

# Organize by modality/patient
healthcarecli dataset export /path/to/dicoms/ --output-dir ./dataset/ --structure modality-patient

# Use symlinks instead of copying (saves disk space)
healthcarecli dataset export /path/to/dicoms/ --output-dir ./dataset/ --symlink

# Show summary statistics for a dataset
healthcarecli dataset stats /path/to/dicoms/
```

---

## Shell completion

```bash
healthcarecli --install-completion   # bash, zsh, fish, PowerShell
```

---

## Roadmap

- [x] DICOM — C-FIND, C-STORE SCU/SCP, C-ECHO, C-MOVE, AE profiles
- [x] DICOM — Anonymize, bulk operations, autotune
- [x] DICOMweb — QIDO-RS, WADO-RS, STOW-RS (REST, auth: none/basic/bearer)
- [x] FHIR R4 — search, CRUD, capabilities, SMART on FHIR auth
- [x] Dataset — ML-ready export with metadata manifest
- [x] npm distribution (`npm install -g healthcarecli`)
- [x] CI — GitHub Actions (Ubuntu, Windows, macOS × Python 3.10–3.12)
- [ ] HL7 v2 — MLLP send/receive, ADT/ORM/ORU message builders
- [ ] PyPI / npm publish
