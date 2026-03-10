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
