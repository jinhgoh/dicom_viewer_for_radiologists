"""Patient-space geometry: orientation markers and cross-reference lines.

DICOM patient coordinates are LPS: +X = Left, +Y = Posterior, +Z = Head.

For quadrupeds the scanner still writes LPS, so the human axis names map onto
veterinary directions only under the usual sternal (prone) recumbency:
    +Y (posterior) -> dorsal, +Z (head) -> cranial.
That assumption is what the veterinary label set below encodes; it is offered
as an explicit user choice rather than applied silently.
"""
from __future__ import annotations

import numpy as np

# axis -> (positive label, negative label)
HUMAN_LABELS = {0: ("L", "R"), 1: ("P", "A"), 2: ("H", "F")}
VET_LABELS = {0: ("L", "R"), 1: ("D", "V"), 2: ("Cr", "Cd")}


def direction_label(vector, veterinary: bool = False, max_parts: int = 3) -> str:
    """Compose an orientation string such as "RP" or "Cr" from a 3-vector."""
    v = np.asarray(vector, dtype=float)
    n = np.linalg.norm(v)
    if n == 0:
        return ""
    v = v / n
    table = VET_LABELS if veterinary else HUMAN_LABELS
    order = np.argsort(-np.abs(v))
    parts = []
    for axis in order[:max_parts]:
        comp = v[axis]
        if abs(comp) < 0.15:
            continue
        pos, neg = table[int(axis)]
        parts.append(pos if comp > 0 else neg)
    return "".join(parts)


def edge_labels(geometry, veterinary: bool = False) -> dict[str, str]:
    """Orientation letters for the four image edges, before display transforms.

    Returns keys 'left', 'right', 'top', 'bottom'.
    """
    if not geometry.valid:
        return {}
    right = direction_label(geometry.row_dir, veterinary)
    left = direction_label(-geometry.row_dir, veterinary)
    bottom = direction_label(geometry.col_dir, veterinary)
    top = direction_label(-geometry.col_dir, veterinary)
    return {"left": left, "right": right, "top": top, "bottom": bottom}


def transform_edge_labels(labels: dict, rotation: int, flip_h: bool,
                          flip_v: bool) -> dict:
    """Re-map edge labels through the viewport's rotation and flips."""
    if not labels:
        return {}
    order = ["top", "right", "bottom", "left"]
    cur = dict(labels)
    steps = (rotation // 90) % 4
    for _ in range(steps):
        # rotating the image clockwise moves the top edge to the right
        cur = {order[(i + 1) % 4]: cur[order[i]] for i in range(4)}
    if flip_h:
        cur["left"], cur["right"] = cur["right"], cur["left"]
    if flip_v:
        cur["top"], cur["bottom"] = cur["bottom"], cur["top"]
    return cur


# --------------------------------------------------------------------------
# cross-reference (localizer) lines
# --------------------------------------------------------------------------

def plane_intersection_line(src, dst):
    """Line where plane ``src`` cuts plane ``dst``, in ``dst`` pixel coords.

    Both arguments are ImageGeometry.  Returns ((x0, y0), (x1, y1)) clipped to
    the destination image, or None when the planes are parallel or the line
    misses the image.
    """
    if not (src.valid and dst.valid):
        return None
    n1, n2 = src.normal, dst.normal
    if abs(float(np.dot(n1, n2))) > 0.9995:          # parallel
        return None
    d1 = float(np.dot(n1, src.origin))
    d2 = float(np.dot(n2, dst.origin))
    n1n1 = float(np.dot(n1, n1))
    n2n2 = float(np.dot(n2, n2))
    n1n2 = float(np.dot(n1, n2))
    det = n1n1 * n2n2 - n1n2 * n1n2
    if abs(det) < 1e-12:
        return None
    c1 = (d1 * n2n2 - d2 * n1n2) / det
    c2 = (d2 * n1n1 - d1 * n1n2) / det
    point = c1 * n1 + c2 * n2                        # a point on both planes
    direction = np.cross(n1, n2)
    norm = np.linalg.norm(direction)
    if norm < 1e-9:
        return None
    direction = direction / norm

    p0 = dst.to_pixel(point)
    p1 = dst.to_pixel(point + direction * 100.0)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return None
    return clip_line_to_rect(p0, (dx, dy), dst.cols, dst.rows)


def clip_line_to_rect(point, direction, width: int, height: int):
    """Clip an infinite line (point + t*direction) to [0,width]x[0,height]."""
    px, py = point
    dx, dy = direction
    t_min, t_max = -1e18, 1e18
    for p, q in ((-dx, px - 0.0), (dx, float(width) - px),
                 (-dy, py - 0.0), (dy, float(height) - py)):
        if abs(p) < 1e-12:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            t_min = max(t_min, t)
        else:
            t_max = min(t_max, t)
    if t_min > t_max:
        return None
    return ((px + dx * t_min, py + dy * t_min),
            (px + dx * t_max, py + dy * t_max))


def slab_lines(src, dst, thickness: float):
    """Two lines bounding the source slice's thickness on the target image."""
    if thickness is None or thickness <= 0:
        return []
    out = []
    for sign in (-0.5, 0.5):
        shifted = _ShiftedGeometry(src, src.normal * (thickness * sign))
        line = plane_intersection_line(shifted, dst)
        if line:
            out.append(line)
    return out


class _ShiftedGeometry:
    """A plane translated along its normal - used for slab boundaries."""

    def __init__(self, base, offset):
        self.origin = base.origin + offset
        self.normal = base.normal
        self.row_dir = base.row_dir
        self.col_dir = base.col_dir
        self.d_row = base.d_row
        self.d_col = base.d_col
        self.rows = base.rows
        self.cols = base.cols
        self.valid = base.valid


def nearest_slice(series, point) -> int:
    """Index of the slice in ``series`` whose plane is closest to a 3-D point."""
    return locate_point(series, point)[0]


def locate_point(series, point) -> tuple[int, float, bool]:
    """Find where a 3-D patient point falls in a series.

    Returns ``(index, distance_mm, covered)`` where ``distance_mm`` is the
    out-of-plane distance to the nearest slice and ``covered`` says whether the
    point actually lies inside that series' acquired volume - both within the
    slice slab and inside the in-plane field of view.  Callers use ``covered``
    to avoid pointing a cross-reference cursor at anatomy a series never
    imaged.
    """
    best, best_d = 0, float("inf")
    p = np.asarray(point, dtype=float)
    for i, inst in enumerate(series.instances):
        g = inst.geometry
        if not g.valid:
            continue
        d = abs(g.distance_to_plane(p))
        if d < best_d:
            best, best_d = i, d
    if not np.isfinite(best_d):
        return 0, float("inf"), False

    inst = series.instances[best]
    g = inst.geometry
    # Out-of-plane tolerance: half a slab, or half the spacing for a gapped
    # stack, so a point between two slices of a gapped series still counts.
    thickness = inst.num("SliceThickness") or 0.0
    spacing = series.slice_spacing or thickness or 1.0
    tolerance = max(thickness, spacing) / 2.0 + 1e-3
    if best_d > tolerance:
        return best, best_d, False

    x, y = g.to_pixel(p)
    covered = (-0.5 <= x <= g.cols - 0.5) and (-0.5 <= y <= g.rows - 0.5)
    return best, best_d, covered


# --------------------------------------------------------------------------
# volume assembly (for MPR)
# --------------------------------------------------------------------------

def build_volume(series):
    """Stack a parallel, evenly spaced series into (volume, spacing, geometry).

    ``spacing`` is (slice, row, col) in millimetres.  Returns None when the
    series is not a coherent volume.
    """
    if not series.is_volume:
        return None
    first = series.first
    g = first.geometry
    slices = [inst.pixels for inst in series.instances]
    if any(sl is None for sl in slices):
        return None
    vol = np.stack(slices).astype(np.float32)
    sp = series.slice_spacing or 1.0
    return vol, (sp, g.d_row, g.d_col), g
