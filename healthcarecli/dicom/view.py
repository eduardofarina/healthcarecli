"""Render DICOM images in the terminal using Unicode half-block characters."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
from PIL import Image
from rich.console import Console
from rich.text import Text


def _apply_window(pixels: np.ndarray, center: float, width: float) -> np.ndarray:
    """Apply window/level to pixel data → uint8 (0-255)."""
    low = center - width / 2
    high = center + width / 2
    clipped = np.clip(pixels, low, high)
    if high == low:
        return np.zeros_like(clipped, dtype=np.uint8)
    normalized = (clipped - low) / (high - low) * 255.0
    return normalized.astype(np.uint8)


def _get_default_window(ds: pydicom.Dataset) -> tuple[float, float]:
    """Extract WindowCenter/WindowWidth from DICOM dataset, with fallbacks."""
    center = getattr(ds, "WindowCenter", None)
    width = getattr(ds, "WindowWidth", None)

    if center is not None:
        center = float(center[0]) if isinstance(center, pydicom.multival.MultiValue) else float(center)
    if width is not None:
        width = float(width[0]) if isinstance(width, pydicom.multival.MultiValue) else float(width)

    if center is not None and width is not None:
        return center, width

    # Fallback: use min/max of pixel data
    pixels = ds.pixel_array.astype(float)
    slope = float(getattr(ds, "RescaleSlope", 1))
    intercept = float(getattr(ds, "RescaleIntercept", 0))
    pixels = pixels * slope + intercept
    pmin, pmax = float(pixels.min()), float(pixels.max())
    return (pmin + pmax) / 2, max(pmax - pmin, 1)


def render_dicom(
    path: Path,
    width: int | None = None,
    window_center: float | None = None,
    window_width: float | None = None,
    colormap: str = "gray",
) -> str:
    """Read a DICOM file and return a terminal-renderable string using half-blocks.

    Each character row encodes two pixel rows using the upper-half-block '▀'.
    The top pixel sets the foreground color and the bottom pixel sets the
    background color, effectively doubling vertical resolution.
    """
    ds = pydicom.dcmread(str(path))

    if not hasattr(ds, "pixel_array"):
        raise ValueError(f"No pixel data in {path.name}")

    pixels = ds.pixel_array.astype(float)

    # Handle multi-frame — take first frame
    if pixels.ndim > 2 and ds.get("NumberOfFrames", 1) > 1:
        pixels = pixels[0]

    # Apply rescale slope/intercept
    slope = float(getattr(ds, "RescaleSlope", 1))
    intercept = float(getattr(ds, "RescaleIntercept", 0))

    is_rgb = getattr(ds, "PhotometricInterpretation", "") == "RGB"

    if is_rgb:
        rgb_array = pixels.astype(np.uint8)
    else:
        pixels = pixels * slope + intercept
        center = window_center if window_center is not None else _get_default_window(ds)[0]
        w = window_width if window_width is not None else _get_default_window(ds)[1]
        gray = _apply_window(pixels, center, w)
        # Convert grayscale to RGB
        rgb_array = np.stack([gray, gray, gray], axis=-1)

    # Resize to fit terminal width
    img = Image.fromarray(rgb_array, mode="RGB")
    console = Console()
    term_width = width or (console.size.width - 2)
    aspect = img.height / img.width
    new_width = min(term_width, img.width)
    # Terminal chars are ~2x taller than wide; half-blocks double vertical res
    new_height = int(new_width * aspect)
    # Make height even for half-block pairing
    new_height = new_height + (new_height % 2)
    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    rgb = np.array(img)

    # Build half-block output: each row of text = 2 pixel rows
    lines: list[str] = []
    for y in range(0, new_height, 2):
        row_top = rgb[y]
        row_bot = rgb[y + 1] if y + 1 < new_height else np.zeros_like(row_top)
        parts: list[str] = []
        for x in range(new_width):
            rt, gt, bt = int(row_top[x][0]), int(row_top[x][1]), int(row_top[x][2])
            rb, gb, bb = int(row_bot[x][0]), int(row_bot[x][1]), int(row_bot[x][2])
            # ▀ with fg=top pixel, bg=bottom pixel
            parts.append(f"\033[38;2;{rt};{gt};{bt}m\033[48;2;{rb};{gb};{bb}m▀")
        lines.append("".join(parts) + "\033[0m")

    return "\n".join(lines)


def print_dicom_info(ds: pydicom.Dataset, path: Path, console: Console) -> None:
    """Print key DICOM metadata below the image."""
    fields = [
        ("Patient", getattr(ds, "PatientName", "N/A")),
        ("ID", getattr(ds, "PatientID", "N/A")),
        ("Modality", getattr(ds, "Modality", "N/A")),
        ("Study", getattr(ds, "StudyDescription", "N/A")),
        ("Series", getattr(ds, "SeriesDescription", "N/A")),
        ("Size", f"{getattr(ds, 'Rows', '?')}×{getattr(ds, 'Columns', '?')}"),
        ("Instance", getattr(ds, "InstanceNumber", "N/A")),
    ]
    info_parts = [f"[bold]{k}[/]: {v}" for k, v in fields if str(v) != "N/A"]
    console.print(" | ".join(info_parts))
