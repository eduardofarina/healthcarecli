# healthcarecli — Agent Skill

Use the `healthcarecli` command-line tool to interact with healthcare systems:
DICOM imaging networks (PACS), FHIR servers, and HL7 messaging endpoints.

Install once with `npm install -g healthcarecli` (requires Node >=18 and Python >=3.10).
Alternative: `pipx install healthcarecli` (Python-only, no Node required).
Every command supports `--output json` for structured output.

---

## DICOM — Managing PACS connections

### Save a PACS profile (run once per server)
```bash
healthcarecli dicom profile add <name> --host <host> --port <port> --ae-title <AE>
# Example:
healthcarecli dicom profile add orthanc --host 127.0.0.1 --port 4242 --ae-title ORTHANC
```

### List saved profiles
```bash
healthcarecli dicom profile list --output json
```

### Verify a connection is alive (C-ECHO)
```bash
healthcarecli dicom ping --profile <name> --output json
# Returns: {"success": true, "rtt_ms": 4.2, ...} or exits with code 1 on failure
```

---

## DICOM — Querying studies (C-FIND)

```bash
# Find all studies for a patient
healthcarecli dicom query --profile <name> --patient-id <id> --output json

# Filter by modality and date range (YYYYMMDD or YYYYMMDD-YYYYMMDD)
healthcarecli dicom query --profile <name> --modality CT --study-date 20240101-20241231 --output json

# Query at SERIES level within a known study
healthcarecli dicom query --profile <name> --level SERIES --study-uid <uid> --output json

# Query at IMAGE level
healthcarecli dicom query --profile <name> --level IMAGE --series-uid <uid> --output json

# Limit results
healthcarecli dicom query --profile <name> --limit 10 --output json
```

Output is a JSON array of objects. Key fields vary by level:
- STUDY: `PatientID`, `PatientName`, `StudyInstanceUID`, `StudyDate`, `ModalitiesInStudy`, `AccessionNumber`
- SERIES: `SeriesInstanceUID`, `Modality`, `SeriesDescription`, `NumberOfSeriesRelatedInstances`
- IMAGE: `SOPInstanceUID`, `SOPClassUID`, `InstanceNumber`

---

## DICOM — Sending files (C-STORE)

```bash
# Send a single DICOM file
healthcarecli dicom send --profile <name> /path/to/image.dcm --output json

# Send all .dcm files in a directory (recursive)
healthcarecli dicom send --profile <name> /path/to/study/ --output json
```

Output is a JSON array: `[{"file": "...", "success": true, "status": 0, "message": "OK"}, ...]`
Exit code is `1` if any file failed.

---

## DICOM — Receiving files (C-STORE SCP listener)

```bash
# Start a listener on port 11112, save files to ./received/
healthcarecli dicom listen --port 11112 --output-dir ./received
# Press Ctrl+C to stop
```

---

## Tips for agents

- Always check `--output json` responses for `"success": false` or non-zero exit codes.
- Run `healthcarecli dicom ping` before querying to confirm the PACS is reachable.
- Profile names are arbitrary labels you assign — choose descriptive names (e.g. `orthanc`, `prod-pacs`, `dcm4chee`).
- Use `--level STUDY` → `--level SERIES` → `--level IMAGE` drill-down to navigate the DICOM hierarchy.
- `StudyInstanceUID` from a STUDY-level query is the key needed for SERIES and IMAGE queries.

---

## DICOMweb — QIDO-RS / WADO-RS / STOW-RS

Use when the PACS exposes a DICOMweb (REST) endpoint instead of (or in addition to) traditional DICOM network.

### Save a DICOMweb profile (run once)
```bash
healthcarecli dicom web profile add <name> --url <base-url>
# With auth:
healthcarecli dicom web profile add gcp --url https://... --auth bearer --token <token>
healthcarecli dicom web profile add local --url http://localhost:8042/dicom-web --auth basic --username admin --password secret
```

### QIDO-RS — search
```bash
# Studies
healthcarecli dicom web qido --profile <name> --level studies --patient-id <id> --output json

# Series within a study
healthcarecli dicom web qido --profile <name> --level series --study-uid <uid> --output json

# Instances within a series
healthcarecli dicom web qido --profile <name> --level instances --study-uid <uid> --series-uid <uid> --output json

# Extra tag filter
healthcarecli dicom web qido --profile <name> --filter "00080060=CT" --limit 20 --output json
```

Output is a JSON array with DICOM keyword keys (e.g. `PatientID`, `StudyInstanceUID`, `Modality`).

### WADO-RS — download
```bash
# Entire study → saves .dcm files to output-dir
healthcarecli dicom web wado --profile <name> --study-uid <uid> --output-dir ./study/ --output json

# Specific series
healthcarecli dicom web wado --profile <name> --study-uid <uid> --series-uid <uid> --output-dir ./

# Single instance
healthcarecli dicom web wado --profile <name> --study-uid <uid> --series-uid <uid> --instance-uid <uid> --output-dir ./
```

Output JSON: `{"downloaded": N, "files": [{"file": "/path/to/uid.dcm"}, ...]}`

### STOW-RS — upload
```bash
healthcarecli dicom web stow --profile <name> /path/to/study/ --output json
healthcarecli dicom web stow --profile <name> file.dcm
```

Output JSON: `{"stored": N, "failed": M, "files": [{"file": "...", "success": true}, ...]}`

### Tips for agents (DICOMweb)
- QIDO → WADO is the standard retrieve flow: search first to get UIDs, then download.
- `--output json` on `qido` returns an array — use `StudyInstanceUID` from results to drive `wado`.
- STOW-RS and WADO-RS both use separate profile types from the DICOM network profile (`dicom profile` vs `dicom web profile`).
- Some PACS (e.g. Orthanc) expose DICOMweb at `/dicom-web`; others (DCM4CHEE) use `/dcm4chee-arc/aets/<AET>/rs`.

---

## Setup

Install (once):

```bash
npm install -g healthcarecli
```

First run the guided wizard (saves a profile and optionally tests the connection):

```bash
healthcarecli init
```

Or add a profile directly (non-interactive, safe for automation):

```bash
healthcarecli dicom profile add orthanc --host 127.0.0.1 --port 4242 --ae-title ORTHANC
```
