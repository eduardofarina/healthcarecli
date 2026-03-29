You are helping the user perform bulk DICOM operations (batch queries or parallel sends) using `healthcarecli`.

Follow these steps exactly, in order. Do not skip steps or bundle questions together.

---

## Step 1 — Choose operation

Use the AskUserQuestion tool to ask:

"What bulk operation do you want to perform?"
```
1. batch-query — Run multiple C-FIND queries from a CSV/TSV file
2. parallel-send — Send DICOM files using multiple parallel connections
```

---

## If batch-query:

### Step 2a — Collect details

1. **PACS profile** — "Which PACS profile should I query? (run `healthcarecli dicom profile list` to see available profiles)"
2. **Input file** — "Where is your CSV/TSV file with query parameters?"
   - Explain supported columns: `patient_id` (or `PatientID`), `study_date` (or `StudyDate`), `modality` (or `Modality`), `accession` (or `AccessionNumber`), `study_uid`, `series_uid`, `level`
3. **Results limit** — "Max results per query? (press Enter for unlimited)"
4. **Output format** — "Output as table, json, or ndjson? (ndjson is best for piping into other tools)"

### Step 3a — Run

```bash
healthcarecli dicom batch-query \
  --profile <name> \
  --input <csv_file> \
  [--limit <n>] \
  --output <format>
```

### Step 4a — Next steps

Suggest saving results:
```bash
# Save as NDJSON for downstream processing
healthcarecli dicom batch-query --profile <name> --input queries.csv --output ndjson > results.ndjson

# Pipe into jq for filtering
healthcarecli dicom batch-query --profile <name> --input queries.csv --output ndjson | jq 'select(.Modality == "CT")'
```

---

## If parallel-send:

### Step 2b — Collect details

1. **PACS profile** — "Which PACS profile should I send to?"
2. **Source files** — "Where are the DICOM files to send? (file path or directory)"
3. **Workers** — "How many parallel connections? (default: 4, max recommended: 8)"

### Step 3b — Run

```bash
healthcarecli dicom parallel-send \
  --profile <name> \
  --workers <n> \
  <paths> \
  --output json
```

### Step 4b — Report

Show success/failure counts and suggest troubleshooting for failures.

---

## CSV Template

If the user needs help creating a batch query CSV, offer this template:

```csv
patient_id,modality,study_date
PAT001,CT,20240101-20240331
PAT002,MR,
PAT003,,20240101-
```

Explain:
- Empty values mean "any" (wildcard)
- Date ranges use DICOM format: `YYYYMMDD-YYYYMMDD`
- Open ranges: `20240101-` means "from Jan 1 2024 onwards"
