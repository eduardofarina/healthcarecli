"""Generate synthetic DICOM test files for healthcarecli debugging."""

from pathlib import Path
import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from pydicom.sequence import Sequence
import tempfile
import datetime

OUTPUT_DIR = Path(__file__).parent / "dicom"


def _base_dataset(
    filename: str,
    modality: str,
    patient_name: str = "DOE^JOHN",
    patient_id: str = "PAT001",
    study_date: str = "20240315",
    study_description: str = "Test Study",
) -> FileDataset:
    """Create a base DICOM dataset with common attributes."""
    filepath = OUTPUT_DIR / filename
    file_meta = pydicom.Dataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(filepath), {}, file_meta=file_meta, preamble=b"\x00" * 128)

    # Patient Module
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.PatientBirthDate = "19850101"
    ds.PatientSex = "M"
    ds.PatientAge = "039Y"

    # Study Module
    ds.StudyInstanceUID = generate_uid()
    ds.StudyDate = study_date
    ds.StudyTime = "100000"
    ds.StudyDescription = study_description
    ds.StudyID = "STUDY001"
    ds.AccessionNumber = "ACC001"
    ds.ReferringPhysicianName = "SMITH^JANE^DR"

    # Series Module
    ds.SeriesInstanceUID = generate_uid()
    ds.SeriesNumber = 1
    ds.Modality = modality
    ds.SeriesDescription = f"{modality} Series"
    ds.InstitutionName = "Test Hospital"
    ds.Manufacturer = "HealthcareCLI"

    # SOP Common
    ds.SOPClassUID = pydicom.uid.SecondaryCaptureImageStorage
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.InstanceNumber = 1
    ds.SpecificCharacterSet = "ISO_IR 100"

    return ds


def create_ct_scan() -> None:
    """CT scan — 3 slices, 64x64 pixels."""
    study_uid = generate_uid()
    series_uid = generate_uid()

    for i in range(3):
        ds = _base_dataset(
            f"ct_slice_{i+1:03d}.dcm",
            modality="CT",
            patient_name="SILVA^MARIA",
            patient_id="PAT001",
            study_description="CT Abdomen",
        )
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.InstanceNumber = i + 1
        ds.SeriesDescription = "Axial Abdomen"
        ds.SliceThickness = "5.0"
        ds.ImagePositionPatient = [0.0, 0.0, float(i * 5)]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.PixelSpacing = [0.5, 0.5]

        # Image pixel data
        ds.Rows = 64
        ds.Columns = 64
        ds.BitsAllocated = 16
        ds.BitsStored = 12
        ds.HighBit = 11
        ds.PixelRepresentation = 1
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.RescaleIntercept = -1024
        ds.RescaleSlope = 1
        ds.WindowCenter = 40
        ds.WindowWidth = 400

        np.random.seed(42 + i)
        pixel_data = np.random.randint(-200, 300, (64, 64), dtype=np.int16)
        ds.PixelData = pixel_data.tobytes()

        ds.save_as(OUTPUT_DIR / f"ct_slice_{i+1:03d}.dcm")

    print(f"  Created 3 CT slices (PAT001 - CT Abdomen)")


def create_mr_brain() -> None:
    """MR brain — single slice."""
    ds = _base_dataset(
        "mr_brain_001.dcm",
        modality="MR",
        patient_name="SANTOS^PEDRO",
        patient_id="PAT002",
        study_description="MR Brain",
    )
    ds.SeriesDescription = "T1 Axial"
    ds.MagneticFieldStrength = "3.0"
    ds.SliceThickness = "3.0"
    ds.RepetitionTime = "2000"
    ds.EchoTime = "30"

    ds.Rows = 64
    ds.Columns = 64
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"

    np.random.seed(100)
    pixel_data = np.random.randint(0, 500, (64, 64), dtype=np.uint16)
    ds.PixelData = pixel_data.tobytes()

    ds.save_as(OUTPUT_DIR / "mr_brain_001.dcm")
    print(f"  Created 1 MR Brain (PAT002 - MR Brain)")


def create_xray_chest() -> None:
    """CR chest X-ray."""
    ds = _base_dataset(
        "cr_chest_001.dcm",
        modality="CR",
        patient_name="OLIVEIRA^ANA",
        patient_id="PAT003",
        study_description="Chest X-Ray",
    )
    ds.SeriesDescription = "PA Chest"
    ds.BodyPartExamined = "CHEST"
    ds.ViewPosition = "PA"

    ds.Rows = 128
    ds.Columns = 128
    ds.BitsAllocated = 16
    ds.BitsStored = 14
    ds.HighBit = 13
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"

    np.random.seed(200)
    pixel_data = np.random.randint(0, 4000, (128, 128), dtype=np.uint16)
    ds.PixelData = pixel_data.tobytes()

    ds.save_as(OUTPUT_DIR / "cr_chest_001.dcm")
    print(f"  Created 1 CR Chest (PAT003 - Chest X-Ray)")


def create_us_abdomen() -> None:
    """US abdomen — ultrasound with RGB pixels."""
    ds = _base_dataset(
        "us_abdomen_001.dcm",
        modality="US",
        patient_name="COSTA^LUCAS",
        patient_id="PAT004",
        study_description="US Abdomen",
    )
    ds.SeriesDescription = "Abdomen Survey"

    ds.Rows = 64
    ds.Columns = 64
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 3
    ds.PhotometricInterpretation = "RGB"
    ds.PlanarConfiguration = 0

    np.random.seed(300)
    pixel_data = np.random.randint(0, 256, (64, 64, 3), dtype=np.uint8)
    ds.PixelData = pixel_data.tobytes()

    ds.save_as(OUTPUT_DIR / "us_abdomen_001.dcm")
    print(f"  Created 1 US Abdomen (PAT004 - US Abdomen)")


def create_structured_report() -> None:
    """DICOM SR — structured report without pixel data."""
    filepath = OUTPUT_DIR / "sr_report_001.dcm"
    file_meta = pydicom.Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.88.11"  # Basic Text SR
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(filepath), {}, file_meta=file_meta, preamble=b"\x00" * 128)

    ds.PatientName = "SILVA^MARIA"
    ds.PatientID = "PAT001"
    ds.PatientBirthDate = "19850101"
    ds.PatientSex = "M"

    ds.StudyInstanceUID = generate_uid()
    ds.StudyDate = "20240315"
    ds.StudyDescription = "Radiology Report"
    ds.SeriesInstanceUID = generate_uid()
    ds.SeriesNumber = 1
    ds.Modality = "SR"
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.InstanceNumber = 1
    ds.SpecificCharacterSet = "ISO_IR 100"

    ds.CompletionFlag = "COMPLETE"
    ds.VerificationFlag = "VERIFIED"

    # Content sequence with a simple text finding
    content_item = Dataset()
    content_item.ValueType = "TEXT"
    content_item.TextValue = "No acute findings. Heart and lungs within normal limits."

    concept_name = Dataset()
    concept_name.CodeValue = "121071"
    concept_name.CodingSchemeDesignator = "DCM"
    concept_name.CodeMeaning = "Finding"
    content_item.ConceptNameCodeSequence = Sequence([concept_name])

    ds.ContentSequence = Sequence([content_item])

    ds.save_as(filepath)
    print(f"  Created 1 SR Report (PAT001 - Radiology Report)")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating synthetic DICOM files...")
    create_ct_scan()
    create_mr_brain()
    create_xray_chest()
    create_us_abdomen()
    create_structured_report()
    print(f"\nDone! Files saved to {OUTPUT_DIR}/")
