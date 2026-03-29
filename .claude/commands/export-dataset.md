You are helping the user export DICOM files into an ML-ready dataset with metadata manifest using `healthcarecli`.

Follow these steps exactly, in order. Do not skip steps or bundle questions together.

---

## Step 1 — Collect source files

Use the AskUserQuestion tool to ask:

1. **Source path** — "Where are the DICOM files you want to export? (file path or directory)"
2. **Output directory** — "Where should the dataset be created? (press Enter for default: ./dataset)"
   - If the user presses Enter or says "default", use `./dataset`.

---

## Step 2 — Choose directory structure

Ask: "How should the files be organized?"

Show the options:
```
1. patient-study (recommended) — PatientID/StudyInstanceUID/file.dcm
2. modality-patient — Modality/PatientID/file.dcm
3. study-series — StudyInstanceUID/SeriesInstanceUID/file.dcm
4. flat — All files in one directory
```

---

## Step 3 — Choose manifest format

Ask: "What format for the metadata manifest? (csv for pandas, json for programmatic use, or none)"

Default to `csv` if the user presses Enter.

---

## Step 4 — Copy or symlink

Ask: "Copy files or create symlinks? (copy is safer, symlinks save disk space)"

Default to `copy` if the user presses Enter.

---

## Step 5 — Confirm and run

Show a summary and ask: "Ready to export?"

```
Source       : <path>
Output       : <output_dir>
Structure    : <structure>
Manifest     : <format>
Mode         : <copy or symlink>
```

Run the command:
```bash
healthcarecli dataset export <paths> \
  --output-dir <output_dir> \
  --structure <structure> \
  --manifest <format> \
  [--symlink] \
  --output json
```

---

## Step 6 — Show stats and next steps

After export, run stats:
```bash
healthcarecli dataset stats <output_dir> --output json
```

Show the summary (patients, studies, modalities, date range, resolutions).

Suggest next steps:
```bash
# Load manifest in Python
import pandas as pd
df = pd.read_csv("<output_dir>/manifest.csv")

# Anonymize first if you haven't already
healthcarecli dicom anonymize <source> --output-dir ./anonymized
healthcarecli dataset export ./anonymized --structure patient-study
```
