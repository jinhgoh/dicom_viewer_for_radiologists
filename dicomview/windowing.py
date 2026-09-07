"""VOI windowing, presets and colour lookup tables."""
from __future__ import annotations

import numpy as np

# --------------------------------------------------------------------------
# window presets
# --------------------------------------------------------------------------

# CT presets are in Hounsfield units and only meaningful for rescaled CT.
CT_PRESETS = [
    ("Soft tissue", 50, 400),
    ("Lung", -600, 1600),
    ("Bone", 300, 1500),
    ("Brain", 40, 80),
    ("Posterior fossa", 40, 120),
    ("Abdomen", 60, 400),
    ("Liver", 60, 160),
    ("Mediastinum", 50, 350),
    ("Angio", 300, 600),
    ("Spine (bone)", 400, 1800),
    ("Spine (soft)", 50, 250),
]


def preset_list(modality: str) -> list[tuple[str, float, float]]:
    """Window presets appropriate for a modality (empty for MR - see below)."""
    if str(modality).upper() in ("CT", "PT", "PET"):
        return CT_PRESETS
    return []


def auto_window(data: np.ndarray, low_pct: float = 1.0,
                high_pct: float = 99.0) -> tuple[float, float]:
    """Robust window from intensity percentiles, ignoring the air background."""
    flat = data[np.isfinite(data)]
    if flat.size == 0:
        return 0.0, 1.0
    if flat.size > 200_000:                       # subsample large images
        step = max(1, flat.size // 200_000)
        flat = flat.ravel()[::step]
    lo = float(np.percentile(flat, low_pct))
    hi = float(np.percentile(flat, high_pct))
    if hi <= lo:
        lo, hi = float(flat.min()), float(flat.max())
    if hi <= lo:
        hi = lo + 1.0
    return (lo + hi) / 2.0, hi - lo


def full_window(data: np.ndarray) -> tuple[float, float]:
    lo, hi = float(np.nanmin(data)), float(np.nanmax(data))
    if hi <= lo:
        hi = lo + 1.0
    return (lo + hi) / 2.0, hi - lo


def apply_window(data: np.ndarray, center: float, width: float,
                 invert: bool = False) -> np.ndarray:
    """Apply a DICOM LINEAR VOI transform, returning uint8.

    Follows PS3.3 C.11.2.1.2:
        x <= c-0.5-(w-1)/2  -> 0
        x >  c-0.5+(w-1)/2  -> 255
        else  ((x-(c-0.5))/(w-1)+0.5) * 255
    """
    w = max(float(width), 1e-6)
    c = float(center)
    if data.dtype.kind in "iu" and data.dtype.itemsize <= 2:
        return _apply_window_lut(data, c, w, invert)
    lo = c - 0.5 - (w - 1.0) / 2.0
    scale = 255.0 / (w - 1.0) if w > 1.0 else 255.0
    out = (data.astype(np.float32) - lo) * scale
    np.clip(out, 0, 255, out=out)
    out = out.astype(np.uint8)
    if invert:
        out = 255 - out
    return out


_LUT_CACHE: dict[tuple, np.ndarray] = {}


def _apply_window_lut(data: np.ndarray, c: float, w: float,
                      invert: bool) -> np.ndarray:
    """Fast path for 8/16-bit integer images: window once into a table."""
    info = np.iinfo(data.dtype)
    key = (data.dtype.str, round(c, 3), round(w, 3), invert)
    lut = _LUT_CACHE.get(key)
    if lut is None:
        if len(_LUT_CACHE) > 64:
            _LUT_CACHE.clear()
        values = np.arange(info.min, info.max + 1, dtype=np.float32)
        lo = c - 0.5 - (w - 1.0) / 2.0
        scale = 255.0 / (w - 1.0) if w > 1.0 else 255.0
        tbl = (values - lo) * scale
        np.clip(tbl, 0, 255, out=tbl)
        lut = tbl.astype(np.uint8)
        if invert:
            lut = 255 - lut
        _LUT_CACHE[key] = lut
    return lut[data.astype(np.int64) - info.min]


# --------------------------------------------------------------------------
# colour maps
# --------------------------------------------------------------------------

def _ramp(stops) -> np.ndarray:
    """Build a 256x3 uint8 LUT from (position 0-1, (r,g,b)) control points."""
    xs = np.linspace(0.0, 1.0, 256)
    pos = np.array([p for p, _ in stops], dtype=float)
    lut = np.zeros((256, 3), dtype=np.uint8)
    for ch in range(3):
        vals = np.array([c[ch] for _, c in stops], dtype=float)
        lut[:, ch] = np.clip(np.interp(xs, pos, vals), 0, 255).astype(np.uint8)
    return lut


def _build_colormaps() -> dict[str, np.ndarray | None]:
    grey = None                                    # rendered as Grayscale8
    hot_iron = _ramp([(0.0, (0, 0, 0)), (0.35, (180, 40, 0)),
                      (0.65, (255, 150, 0)), (0.85, (255, 235, 100)),
                      (1.0, (255, 255, 255))])
    pet = _ramp([(0.0, (0, 0, 0)), (0.15, (40, 0, 90)), (0.3, (120, 0, 160)),
                 (0.45, (220, 0, 90)), (0.6, (255, 90, 0)),
                 (0.8, (255, 210, 0)), (1.0, (255, 255, 255))])
    rainbow = _ramp([(0.0, (0, 0, 0)), (0.12, (60, 0, 130)), (0.3, (0, 0, 255)),
                     (0.45, (0, 255, 255)), (0.6, (0, 255, 0)),
                     (0.75, (255, 255, 0)), (0.9, (255, 0, 0)),
                     (1.0, (255, 255, 255))])
    bone = _ramp([(0.0, (0, 0, 0)), (0.38, (84, 84, 116)),
                  (0.75, (167, 199, 199)), (1.0, (255, 255, 255))])
    hot_metal = _ramp([(0.0, (0, 0, 0)), (0.25, (128, 0, 0)),
                       (0.5, (255, 128, 0)), (0.75, (255, 255, 64)),
                       (1.0, (255, 255, 255))])
    # Perfusion-style blue->red used for subtraction / diffusion overlays.
    cold_hot = _ramp([(0.0, (0, 0, 160)), (0.25, (0, 160, 255)),
                      (0.5, (230, 230, 230)), (0.75, (255, 160, 0)),
                      (1.0, (180, 0, 0))])
    return {
        "Grayscale": grey,
        "Hot iron": hot_iron,
        "PET": pet,
        "Rainbow": rainbow,
        "Bone": bone,
        "Hot metal": hot_metal,
        "Cold / hot": cold_hot,
    }


COLORMAPS = _build_colormaps()
COLORMAP_NAMES = list(COLORMAPS.keys())


def colorize(gray: np.ndarray, name: str) -> np.ndarray | None:
    """Map a uint8 image through a colour LUT, returning HxWx3 uint8."""
    lut = COLORMAPS.get(name)
    if lut is None:
        return None
    return lut[gray]
