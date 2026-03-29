You are helping the user anonymize (de-identify) DICOM files using `healthcarecli`.

Follow these steps exactly, in order. Do not skip steps or bundle questions together.

---

## Step 1 — Collect source files

Use the AskUserQuestion tool to ask:

1. **Source path** — "Where are the DICOM files you want to anonymize? (file path or directory)"
2. **Output directory** — "Where should the anonymized files be saved? (press Enter for default: ./anonymized)"
   - If the user presses Enter or says "default", use `./anonymized`.

---

## Step 2 — Choose anonymization profile

Ask: "Which anonymization profile do you want to use?"

Show the options:
```
1. safe-harbor (recommended) — HIPAA Safe Harbor, removes all 18 PHI identifiers
2. basic — Minimal, removes patient name, ID, and birth date only
3. keep-dates — Safe Harbor but preserves study/series dates
```

---

## Step 3 — Optional: preserve specific tags

Ask: "Are there any DICOM tags you want to preserve for your ML pipeline? (e.g. SeriesDescription, BodyPartExamined — comma-separated, or press Enter to skip)"

If the user provides tags, add them as `--keep <tag>` flags.

---

## Step 4 — Optional: deterministic salt

Ask: "Do you want UIDs to be remapped deterministically? This is useful when re-running anonymization on the same dataset. (Enter a salt string, or press Enter for random)"

If the user provides a salt, use `--salt <value>`.

---

## Step 5 — Confirm and run

Show a summary and ask: "Ready to anonymize?"

```
Source       : <path>
Output       : <output_dir>
Profile      : <profile>
Keep tags    : <tags or "none">
Salt         : <salt or "random">
```

Run the command:
```bash
healthcarecli dicom anonymize <paths> \
  --output-dir <output_dir> \
  --profile <profile> \
  [--keep <tag1> --keep <tag2>] \
  [--salt <salt>] \
  --output json
```

---

## Step 6 — Report results

- Show how many files were successfully anonymized vs failed.
- If there are failures, show the error messages.
- Suggest next steps:
  ```bash
  # Export anonymized files to a structured dataset
  healthcarecli dataset export <output_dir> --structure patient-study

  # Check dataset stats
  healthcarecli dataset stats <output_dir>
  ```
