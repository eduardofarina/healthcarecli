# Sample Data — Debug & Test Guide

Synthetic open data for testing and debugging `healthcarecli`.
All patient data is **fictional** — no real PHI.

---

## Patients Overview

| ID     | Name             | Modalities | Description          |
|--------|------------------|------------|----------------------|
| PAT001 | SILVA^MARIA      | CT, SR     | CT Abdomen + Report  |
| PAT002 | SANTOS^PEDRO     | MR         | MR Brain T1          |
| PAT003 | OLIVEIRA^ANA     | CR         | Chest X-Ray PA       |
| PAT004 | COSTA^LUCAS      | US         | US Abdomen           |

---

## DICOM files (`sample_data/dicom/`)

| File                | Modality | Description                    | Pixels   |
|---------------------|----------|--------------------------------|----------|
| `ct_slice_001.dcm`  | CT       | CT Abdomen — slice 1/3         | 64×64 i16 |
| `ct_slice_002.dcm`  | CT       | CT Abdomen — slice 2/3         | 64×64 i16 |
| `ct_slice_003.dcm`  | CT       | CT Abdomen — slice 3/3         | 64×64 i16 |
| `mr_brain_001.dcm`  | MR       | MR Brain T1 Axial              | 64×64 u16 |
| `cr_chest_001.dcm`  | CR       | Chest X-Ray PA                 | 128×128 u16 |
| `us_abdomen_001.dcm`| US       | Ultrasound Abdomen (RGB)       | 64×64×3 u8 |
| `sr_report_001.dcm` | SR       | Structured Report (no pixels)  | —        |

### Quick debug commands

```bash
# Inspect a DICOM file
python -c "import pydicom; ds = pydicom.dcmread('sample_data/dicom/ct_slice_001.dcm'); print(ds)"

# Send all sample files to a PACS
healthcarecli dicom send --profile orthanc sample_data/dicom/

# Send in parallel (4 workers)
healthcarecli dicom parallel-send --profile orthanc sample_data/dicom/ --workers 4

# Query after sending
healthcarecli dicom query --profile orthanc --patient-id PAT001 --output json

# Anonymize the sample files
healthcarecli dicom anonymize sample_data/dicom/ --output-dir /tmp/anon/ --profile safe-harbor

# Export to ML dataset (flat structure with CSV manifest)
healthcarecli dataset export sample_data/dicom/ --output-dir /tmp/dataset/ --structure flat

# Export organized by patient/study
healthcarecli dataset export sample_data/dicom/ --output-dir /tmp/dataset/ --structure patient-study

# Dataset stats
healthcarecli dataset stats sample_data/dicom/

# Regenerate DICOM files (if needed)
python sample_data/generate_dicom.py
```

---

## FHIR R4 files (`sample_data/fhir/`)

| File                     | Resources                              |
|--------------------------|----------------------------------------|
| `patient_bundle.json`    | 4 Patients (PAT001–PAT004)             |
| `observations.json`      | Blood Pressure, Glucose, Hemoglobin    |
| `diagnostic_report.json` | Chest X-Ray radiology report           |

### Quick debug commands

```bash
# Create patients from bundle (requires a FHIR server profile)
healthcarecli fhir create --profile hapi --file sample_data/fhir/patient_bundle.json

# Create a diagnostic report
healthcarecli fhir create --profile hapi --file sample_data/fhir/diagnostic_report.json

# Search for patients
healthcarecli fhir search Patient --profile hapi --param "family=Silva" --output json

# Search observations by patient
healthcarecli fhir search Observation --profile hapi --param "subject=Patient/pat-001" --output json

# Validate JSON structure
python -m json.tool sample_data/fhir/patient_bundle.json > /dev/null && echo "Valid JSON"
```

### Public FHIR servers for testing

```bash
# HAPI FHIR (public, no auth)
healthcarecli fhir profile add hapi --url https://hapi.fhir.org/baseR4

# Test connection
healthcarecli fhir capabilities --profile hapi --output json
```

---

## HL7 v2 messages (`sample_data/hl7/`)

| File                   | Type     | Description                          |
|------------------------|----------|--------------------------------------|
| `adt_a01_admit.hl7`    | ADT^A01  | Patient admission (PAT001)           |
| `adt_a08_update.hl7`   | ADT^A08  | Patient info update (address change) |
| `adt_a03_discharge.hl7`| ADT^A03  | Patient discharge                    |
| `orm_o01_order.hl7`    | ORM^O01  | Radiology order (Chest X-Ray)        |
| `oru_r01_result.hl7`   | ORU^R01  | Lab results (glucose, CBC)           |

### Message flow (real-world scenario)

```
1. adt_a01_admit.hl7     → Patient Maria Silva is admitted to Ward-A
2. orm_o01_order.hl7     → Chest X-Ray ordered for Ana Oliveira
3. oru_r01_result.hl7    → Lab results (glucose, hemoglobin, WBC, platelets)
4. adt_a08_update.hl7    → Maria Silva's address is updated
5. adt_a03_discharge.hl7 → Maria Silva is discharged
```

### Quick debug commands

```bash
# Send a single HL7 message via MLLP
healthcarecli hl7 send --host 127.0.0.1 --port 2575 sample_data/hl7/adt_a01_admit.hl7

# Parse and inspect a message
python -c "
with open('sample_data/hl7/oru_r01_result.hl7') as f:
    for line in f:
        seg = line.strip().split('|')
        print(f'{seg[0]:4s} → {len(seg)} fields')
"
```

---

## Batch query files (`sample_data/batch/`)

| File                   | Description                                |
|------------------------|--------------------------------------------|
| `batch_query.csv`      | Multi-patient query by ID, name, modality  |
| `batch_query_tags.csv` | Query by DICOM tags (BodyPartExamined)     |

### Quick debug commands

```bash
# Run batch queries against a PACS
healthcarecli dicom batch-query --profile orthanc sample_data/batch/batch_query.csv --output json

# Batch query with tag-based filters
healthcarecli dicom batch-query --profile orthanc sample_data/batch/batch_query_tags.csv --output json
```

---

## Autotune (benchmark your PACS)

```bash
# Quick sweep with 5 iterations
healthcarecli dicom autotune sweep --profile orthanc --iterations 5

# View results
healthcarecli dicom autotune history --profile orthanc

# Apply best parameters
healthcarecli dicom autotune apply --profile orthanc

# See tunable parameters
healthcarecli dicom autotune show-space
```

---

## Full end-to-end test scenario

```bash
# 1. Setup a PACS profile (Orthanc or any PACS)
healthcarecli dicom profile add orthanc --host 127.0.0.1 --port 4242 --ae-title ORTHANC

# 2. Ping
healthcarecli dicom ping --profile orthanc

# 3. Send sample DICOM files
healthcarecli dicom send --profile orthanc sample_data/dicom/

# 4. Query studies
healthcarecli dicom query --profile orthanc --level STUDY --output json

# 5. Query specific patient
healthcarecli dicom query --profile orthanc --patient-id PAT001 --modality CT --output json

# 6. Anonymize
healthcarecli dicom anonymize sample_data/dicom/ --output-dir /tmp/anon/

# 7. Export to ML dataset
healthcarecli dataset export /tmp/anon/ --output-dir /tmp/ml-dataset/ --structure flat

# 8. Check dataset stats
healthcarecli dataset stats /tmp/ml-dataset/

# 9. Setup FHIR server
healthcarecli fhir profile add hapi --url https://hapi.fhir.org/baseR4

# 10. Push patient data to FHIR
healthcarecli fhir create --profile hapi --file sample_data/fhir/patient_bundle.json
```
