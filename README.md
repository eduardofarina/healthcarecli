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
  profile  Manage PACS connection profiles (add, list, show, delete)
  ping     Verify a PACS connection with C-ECHO
  query    C-FIND — search for patients, studies, series, or instances
  send     C-STORE SCU — send DICOM files to a PACS
  listen   C-STORE SCP — receive incoming DICOM files
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

## Shell completion

```bash
healthcarecli --install-completion   # bash, zsh, fish, PowerShell
```

---

## Roadmap

- [x] DICOM — C-FIND, C-STORE SCU/SCP, C-ECHO, AE profiles
- [x] DICOMweb — QIDO-RS, WADO-RS, STOW-RS (REST, auth: none/basic/bearer)
- [x] npm distribution (`npm install -g healthcarecli`)
- [x] CI — GitHub Actions (Ubuntu, Windows, macOS × Python 3.10–3.12)
- [ ] FHIR R4 — patient search, resource CRUD, SMART on FHIR auth
- [ ] HL7 v2 — MLLP send/receive, ADT/ORM/ORU message builders
