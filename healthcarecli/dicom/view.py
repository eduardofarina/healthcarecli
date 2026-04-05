"""Interactive DICOM viewer — Textual TUI with high-resolution image rendering."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import ClassVar

import numpy as np
import pydicom
from PIL import Image
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Label

try:
    from textual_image.widget import Image as TxImage
    HAS_TEXTUAL_IMAGE = True
except ImportError:
    HAS_TEXTUAL_IMAGE = False
    from textual.widgets import Static


# ── Windowing ─────────────────────────────────────────────────────────────────


def _apply_window(pixels: np.ndarray, center: float, width: float) -> np.ndarray:
    low = center - width / 2
    high = center + width / 2
    clipped = np.clip(pixels, low, high)
    if high == low:
        return np.zeros_like(clipped, dtype=np.uint8)
    return ((clipped - low) / (high - low) * 255.0).astype(np.uint8)


def _get_default_window(pixels: np.ndarray, ds: pydicom.Dataset) -> tuple[float, float]:
    center = getattr(ds, "WindowCenter", None)
    width = getattr(ds, "WindowWidth", None)
    if center is not None:
        center = (
            float(center[0]) if isinstance(center, pydicom.multival.MultiValue) else float(center)
        )
    if width is not None:
        width = float(width[0]) if isinstance(width, pydicom.multival.MultiValue) else float(width)
    if center is not None and width is not None:
        return center, width
    pmin, pmax = float(pixels.min()), float(pixels.max())
    return (pmin + pmax) / 2, max(pmax - pmin, 1)


# ── DICOM loader ───────────────────────────────────────────────────────────────


def _load_pixels(ds: pydicom.Dataset) -> np.ndarray:
    px = ds.pixel_array.astype(np.float32)
    slope = float(getattr(ds, "RescaleSlope", 1))
    intercept = float(getattr(ds, "RescaleIntercept", 0))
    return px * slope + intercept


def _frame_to_pil(frame: np.ndarray, is_rgb: bool, wc: float, ww: float) -> Image.Image:
    if is_rgb:
        return Image.fromarray(frame.astype(np.uint8), mode="RGB")
    gray = _apply_window(frame, wc, ww)
    return Image.fromarray(gray, mode="L").convert("RGB")


# ── Fallback half-block renderer ───────────────────────────────────────────────


def _render_half_blocks(rgb: np.ndarray) -> str:
    h, w = rgb.shape[:2]
    if h % 2 != 0:
        rgb = np.vstack([rgb, np.zeros((1, w, 3), dtype=np.uint8)])
        h += 1
    lines: list[str] = []
    for y in range(0, h, 2):
        parts: list[str] = []
        for x in range(w):
            rt, gt, bt = int(rgb[y, x, 0]), int(rgb[y, x, 1]), int(rgb[y, x, 2])
            rb, gb, bb = int(rgb[y + 1, x, 0]), int(rgb[y + 1, x, 1]), int(rgb[y + 1, x, 2])
            parts.append(f"\033[38;2;{rt};{gt};{bt}m\033[48;2;{rb};{gb};{bb}m\u2580")
        lines.append("".join(parts) + "\033[0m")
    return "\n".join(lines)


# ── Textual app ────────────────────────────────────────────────────────────────


class DicomViewer(App):
    CSS = """
    Screen { background: #000000; layers: base overlay; }
    #image-container { width: 100%; height: 1fr; align: center middle; }
    #statusbar { height: 1; background: #1a1a2e; color: #00d4ff; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("up,k", "slice_prev", "Prev slice", show=False),
        Binding("down,j", "slice_next", "Next slice", show=False),
        Binding("w", "scroll_up", "Scroll up", show=False),
        Binding("s", "scroll_down", "Scroll down", show=False),
        Binding("a", "scroll_left", "Scroll left", show=False),
        Binding("d", "scroll_right", "Scroll right", show=False),
        Binding("W", "wl_inc_width", "W+", show=False),
        Binding("S", "wl_dec_width", "W-", show=False),
        Binding("A", "wl_dec_center", "L-", show=False),
        Binding("D", "wl_inc_center", "L+", show=False),
        Binding("bracketleft", "zoom_out", "Zoom-", show=False),
        Binding("bracketright", "zoom_in", "Zoom+", show=False),
        Binding("r", "reset_view", "Reset", show=False),
    ]

    def __init__(self, path: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path = path
        self.ds = pydicom.dcmread(str(path), force=True)
        self._pixels = _load_pixels(self.ds)
        self.is_rgb = getattr(self.ds, "PhotometricInterpretation", "") == "RGB"

        if self._pixels.ndim == 3 and not self.is_rgb:
            self.n_slices = self._pixels.shape[0]
        else:
            self.n_slices = 1

        self.current_slice = 0
        frame0 = self._pixels[0] if self.n_slices > 1 else self._pixels
        self.wc, self.ww = _get_default_window(frame0, self.ds)
        self.zoom = 1.0
        self.scroll_x = 0
        self.scroll_y = 0
        self._tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        self._tmp_path = Path(self._tmp.name)

    def compose(self) -> ComposeResult:
        if HAS_TEXTUAL_IMAGE:
            self._save_frame()
            yield TxImage(str(self._tmp_path), id="image-container")
        else:
            yield Static(id="image-container")
        yield Label(self._status(), id="statusbar", markup=False)

    def on_mount(self) -> None:
        self._refresh_image()

    def on_resize(self) -> None:
        self._refresh_image()

    # ── Rendering ──────────────────────────────────────────────────────────────

    def _current_frame(self) -> np.ndarray:
        return self._pixels[self.current_slice] if self.n_slices > 1 else self._pixels

    def _save_frame(self) -> None:
        frame = self._current_frame()
        img = _frame_to_pil(frame, self.is_rgb, self.wc, self.ww)

        # Upscale only when zooming in (let textual-image handle fit-to-screen)
        if self.zoom > 1.0:
            new_w = max(1, int(img.width * self.zoom))
            new_h = max(1, int(img.height * self.zoom))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Crop for pan when zoomed in
        if self.scroll_x > 0 or self.scroll_y > 0:
            w, h = img.size
            sx = max(0, min(self.scroll_x, w - 1))
            sy = max(0, min(self.scroll_y, h - 1))
            img = img.crop((sx, sy, w, h))

        img.save(str(self._tmp_path), format="PNG")

    def _refresh_image(self) -> None:
        if HAS_TEXTUAL_IMAGE:
            self._save_frame()
            widget = self.query_one("#image-container", TxImage)
            widget.image = str(self._tmp_path)
            widget.refresh(layout=True)
        else:
            frame = self._current_frame()
            img = _frame_to_pil(frame, self.is_rgb, self.wc, self.ww)
            size = self.size
            term_w = size.width
            term_h = (size.height - 1) * 2
            scale = max(term_w / img.width, term_h / img.height)
            new_w = max(1, int(img.width * scale * self.zoom))
            new_h = max(1, int(img.height * scale * self.zoom))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            sx = max(0, min(self.scroll_x, max(0, new_w - term_w)))
            sy = max(0, min(self.scroll_y, max(0, new_h - term_h)))
            crop_w = min(term_w, new_w - sx)
            crop_h = min(term_h, new_h - sy)
            img = img.crop((sx, sy, sx + crop_w, sy + crop_h))
            rgb = np.array(img)
            rendered = _render_half_blocks(rgb)
            from rich.text import Text
            self.query_one("#image-container", Static).update(Text.from_ansi(rendered))

        self.query_one("#statusbar", Label).update(self._status())

    def _status(self) -> str:
        frame = self._current_frame()
        h, w = frame.shape[:2]
        modality = getattr(self.ds, "Modality", "?")
        patient = str(getattr(self.ds, "PatientName", "?"))
        sliceinfo = f"Slice {self.current_slice + 1}/{self.n_slices}" if self.n_slices > 1 else "2D"
        renderer = "HD" if HAS_TEXTUAL_IMAGE else "half-block"
        return (
            f" {self.path.name} | {modality} | {patient} | "
            f"{w}x{h} | {sliceinfo} | "
            f"W/L {self.ww:.0f}/{self.wc:.0f} | Zoom {self.zoom:.1f}x | {renderer} | "
            "j/k:Slice  wasd:Pan  WASD:W/L  [/]:Zoom  r:Reset  q:Quit"
        )

    # ── Actions ────────────────────────────────────────────────────────────────

    def action_slice_prev(self) -> None:
        if self.n_slices > 1 and self.current_slice > 0:
            self.current_slice -= 1
            self._refresh_image()

    def action_slice_next(self) -> None:
        if self.n_slices > 1 and self.current_slice < self.n_slices - 1:
            self.current_slice += 1
            self._refresh_image()

    def _pan_step(self) -> int:
        return max(10, int(min(self.size.width, self.size.height) * 0.05))

    def action_scroll_up(self) -> None:
        self.scroll_y = max(0, self.scroll_y - self._pan_step())
        self._refresh_image()

    def action_scroll_down(self) -> None:
        self.scroll_y += self._pan_step()
        self._refresh_image()

    def action_scroll_left(self) -> None:
        self.scroll_x = max(0, self.scroll_x - self._pan_step())
        self._refresh_image()

    def action_scroll_right(self) -> None:
        self.scroll_x += self._pan_step()
        self._refresh_image()

    def action_wl_inc_width(self) -> None:
        self.ww *= 1.1
        self._refresh_image()

    def action_wl_dec_width(self) -> None:
        self.ww = max(1, self.ww * 0.9)
        self._refresh_image()

    def action_wl_inc_center(self) -> None:
        self.wc += self.ww * 0.05
        self._refresh_image()

    def action_wl_dec_center(self) -> None:
        self.wc -= self.ww * 0.05
        self._refresh_image()

    def action_zoom_in(self) -> None:
        self.zoom = min(20.0, round(self.zoom + 0.25, 2))
        self._refresh_image()

    def action_zoom_out(self) -> None:
        self.zoom = max(0.25, round(self.zoom - 0.25, 2))
        self._refresh_image()

    def action_reset_view(self) -> None:
        self.zoom = 1.0
        self.scroll_x = 0
        self.scroll_y = 0
        frame = self._current_frame()
        self.wc, self.ww = _get_default_window(frame, self.ds)
        self._refresh_image()

    def on_unmount(self) -> None:
        try:
            self._tmp_path.unlink()
        except Exception:
            pass


# ── Public entry point ─────────────────────────────────────────────────────────


def launch_viewer(path: Path) -> None:
    app = DicomViewer(path)
    app.run()
