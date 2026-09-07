"""Measurement and annotation primitives.

All geometry is stored in *image pixel* coordinates so annotations stay
attached to anatomy through zoom, pan, rotation and flips.  Physical values
are derived at display time from PixelSpacing.
"""
from __future__ import annotations

import math
import uuid

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF

# --------------------------------------------------------------------------

DEFAULT_COLOR = "#00e5ff"
SELECTED_COLOR = "#ffd23f"

HANDLE_RADIUS = 4.0          # screen pixels
PICK_TOLERANCE = 7.0         # screen pixels


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point_segment_distance(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return _dist(p, a)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class Scale:
    """Millimetres-per-pixel for one image, or None when uncalibrated."""

    def __init__(self, d_col: float | None, d_row: float | None, calibrated: bool):
        self.d_col = d_col or 1.0        # mm per pixel horizontally
        self.d_row = d_row or 1.0        # mm per pixel vertically
        self.calibrated = calibrated

    @classmethod
    def from_instance(cls, inst):
        ps = inst.get("PixelSpacing")
        imager = inst.get("ImagerPixelSpacing")
        src = ps or imager
        if src is not None and len(src) >= 2:
            try:
                return cls(float(src[1]), float(src[0]), True)
            except (TypeError, ValueError):
                pass
        return cls(1.0, 1.0, False)

    @property
    def unit(self) -> str:
        return "mm" if self.calibrated else "px"

    @property
    def area_unit(self) -> str:
        return "mm²" if self.calibrated else "px²"

    def length(self, dx: float, dy: float) -> float:
        return math.hypot(dx * self.d_col, dy * self.d_row)

    @property
    def pixel_area(self) -> float:
        return self.d_col * self.d_row

    @property
    def isotropic(self) -> bool:
        return abs(self.d_col - self.d_row) < 1e-6


# --------------------------------------------------------------------------
# base
# --------------------------------------------------------------------------

class Annotation:
    kind = "base"
    name = "Annotation"
    min_points = 2
    max_points = 2
    closed = False
    is_roi = False

    def __init__(self, points=None, color: str = DEFAULT_COLOR, text: str = ""):
        self.id = uuid.uuid4().hex[:12]
        self.points: list[list[float]] = [list(p) for p in (points or [])]
        self.color = color
        self.text = text
        self.locked = False
        self.visible = True
        self.series_uid = ""
        self.sop_uid = ""
        self.frame = 0
        self.label_offset = [12.0, -12.0]     # screen px, from the anchor

    # -- construction ------------------------------------------------------
    def add_point(self, pt) -> bool:
        """Append a point during interactive creation.  True when complete."""
        self.points.append([float(pt[0]), float(pt[1])])
        return len(self.points) >= self.max_points

    def is_complete(self) -> bool:
        return len(self.points) >= self.min_points

    def finish(self) -> bool:
        """Called when the user ends a multi-point tool.  False = discard."""
        return self.is_complete()

    # -- editing -----------------------------------------------------------
    def handles(self) -> list[list[float]]:
        return self.points

    def move_handle(self, index: int, pt):
        if 0 <= index < len(self.points):
            self.points[index] = [float(pt[0]), float(pt[1])]

    def translate(self, dx: float, dy: float):
        for p in self.points:
            p[0] += dx
            p[1] += dy

    def hit_test(self, pt, tol: float) -> bool:
        for a, b in zip(self.points, self.points[1:]):
            if _point_segment_distance(pt, a, b) <= tol:
                return True
        if self.closed and len(self.points) > 2:
            if _point_segment_distance(pt, self.points[-1], self.points[0]) <= tol:
                return True
        return any(_dist(pt, p) <= tol for p in self.points)

    def handle_at(self, pt, tol: float) -> int:
        for i, p in enumerate(self.points):
            if _dist(pt, p) <= tol:
                return i
        return -1

    # -- geometry ----------------------------------------------------------
    def anchor(self) -> list[float]:
        """Point the text label hangs off."""
        return self.points[-1] if self.points else [0.0, 0.0]

    def bounds(self) -> QRectF:
        if not self.points:
            return QRectF()
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def path(self) -> QPainterPath:
        """Outline in image coordinates (used for drawing and ROI masks)."""
        path = QPainterPath()
        if not self.points:
            return path
        path.moveTo(*self.points[0])
        for p in self.points[1:]:
            path.lineTo(*p)
        if self.closed:
            path.closeSubpath()
        return path

    # -- results -----------------------------------------------------------
    def describe(self, scale: Scale, image=None) -> list[str]:
        return []

    def report_row(self, scale: Scale, image=None) -> dict:
        return {"type": self.name, "value": " ".join(self.describe(scale, image))}

    # -- persistence -------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "points": self.points,
            "color": self.color, "text": self.text, "locked": self.locked,
            "series_uid": self.series_uid, "sop_uid": self.sop_uid,
            "frame": self.frame, "label_offset": self.label_offset,
        }

    @staticmethod
    def from_dict(d: dict) -> "Annotation | None":
        cls = ANNOTATION_TYPES.get(d.get("kind"))
        if cls is None:
            return None
        obj = cls(points=d.get("points", []), color=d.get("color", DEFAULT_COLOR),
                  text=d.get("text", ""))
        obj.id = d.get("id", obj.id)
        obj.locked = bool(d.get("locked", False))
        obj.series_uid = d.get("series_uid", "")
        obj.sop_uid = d.get("sop_uid", "")
        obj.frame = int(d.get("frame", 0) or 0)
        off = d.get("label_offset")
        if isinstance(off, (list, tuple)) and len(off) == 2:
            obj.label_offset = [float(off[0]), float(off[1])]
        return obj


# --------------------------------------------------------------------------
# ROI statistics
# --------------------------------------------------------------------------

class RoiMixin:
    is_roi = True

    def mask(self, shape) -> np.ndarray | None:
        """Rasterise the outline into a boolean mask of the given (rows, cols)."""
        rows, cols = shape[0], shape[1]
        rect = self.bounds()
        if rect.width() < 0.5 and rect.height() < 0.5:
            return None
        img = QImage(cols, rows, QImage.Format.Format_Grayscale8)
        img.fill(0)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawPath(self.path())
        painter.end()
        ptr = img.constBits()
        ptr.setsize(img.sizeInBytes())
        buf = np.frombuffer(ptr, dtype=np.uint8).reshape(rows, img.bytesPerLine())
        return buf[:, :cols] > 127

    def statistics(self, image: np.ndarray | None, scale: Scale) -> dict | None:
        if image is None:
            return None
        m = self.mask(image.shape)
        if m is None or not m.any():
            return None
        vals = image[m].astype(np.float64)
        return {
            "count": int(vals.size),
            "area": vals.size * scale.pixel_area,
            "mean": float(vals.mean()),
            "sd": float(vals.std(ddof=1)) if vals.size > 1 else 0.0,
            "min": float(vals.min()),
            "max": float(vals.max()),
        }

    def area_lines(self, scale: Scale, image) -> list[str]:
        out = []
        st = self.statistics(image, scale)
        if st:
            out.append(f"Area {st['area']:.1f} {scale.area_unit}")
            out.append(f"Mean {st['mean']:.1f}  SD {st['sd']:.1f}")
            out.append(f"Min {st['min']:.0f}  Max {st['max']:.0f}")
        return out

    def report_row(self, scale: Scale, image=None) -> dict:
        st = self.statistics(image, scale)
        row = {"type": self.name}
        if st:
            row.update({
                "area": round(st["area"], 2), "unit": scale.area_unit,
                "mean": round(st["mean"], 2), "sd": round(st["sd"], 2),
                "min": round(st["min"], 2), "max": round(st["max"], 2),
                "pixels": st["count"],
            })
        return row


# --------------------------------------------------------------------------
# concrete annotations
# --------------------------------------------------------------------------

class Probe(Annotation):
    kind = "probe"
    name = "Probe"
    min_points = 1
    max_points = 1

    def hit_test(self, pt, tol):
        return bool(self.points) and _dist(pt, self.points[0]) <= tol + 3

    def describe(self, scale, image=None):
        if not self.points or image is None:
            return []
        x, y = int(round(self.points[0][0])), int(round(self.points[0][1]))
        if not (0 <= y < image.shape[0] and 0 <= x < image.shape[1]):
            return []
        v = image[y, x]
        val = f"{v:.1f}" if isinstance(v, (float, np.floating)) else f"{int(v)}"
        return [f"({x}, {y})", val]

    def report_row(self, scale, image=None):
        d = self.describe(scale, image)
        return {"type": self.name, "position": d[0] if d else "",
                "value": d[1] if len(d) > 1 else ""}


class Length(Annotation):
    kind = "length"
    name = "Length"
    min_points = 2
    max_points = 2

    def value(self, scale: Scale) -> float:
        (x0, y0), (x1, y1) = self.points[0], self.points[1]
        return scale.length(x1 - x0, y1 - y0)

    def describe(self, scale, image=None):
        if len(self.points) < 2:
            return []
        return [f"{self.value(scale):.2f} {scale.unit}"]

    def anchor(self):
        return self.points[-1]

    def report_row(self, scale, image=None):
        if len(self.points) < 2:
            return {"type": self.name}
        return {"type": self.name, "length": round(self.value(scale), 2),
                "unit": scale.unit}


class Polyline(Annotation):
    kind = "polyline"
    name = "Polyline"
    min_points = 2
    max_points = 512

    def value(self, scale: Scale) -> float:
        return sum(scale.length(b[0] - a[0], b[1] - a[1])
                   for a, b in zip(self.points, self.points[1:]))

    def describe(self, scale, image=None):
        if len(self.points) < 2:
            return []
        return [f"{self.value(scale):.2f} {scale.unit}",
                f"{len(self.points) - 1} segments"]

    def report_row(self, scale, image=None):
        return {"type": self.name, "length": round(self.value(scale), 2),
                "unit": scale.unit, "segments": max(0, len(self.points) - 1)}


class Angle(Annotation):
    kind = "angle"
    name = "Angle"
    min_points = 3
    max_points = 3

    def value(self, scale: Scale) -> float:
        a, v, b = self.points[0], self.points[1], self.points[2]
        u = ((a[0] - v[0]) * scale.d_col, (a[1] - v[1]) * scale.d_row)
        w = ((b[0] - v[0]) * scale.d_col, (b[1] - v[1]) * scale.d_row)
        nu, nw = math.hypot(*u), math.hypot(*w)
        if nu == 0 or nw == 0:
            return 0.0
        cos = max(-1.0, min(1.0, (u[0] * w[0] + u[1] * w[1]) / (nu * nw)))
        return math.degrees(math.acos(cos))

    def describe(self, scale, image=None):
        if len(self.points) < 3:
            return []
        deg = self.value(scale)
        return [f"{deg:.1f}°  ({180 - deg:.1f}°)"]

    def anchor(self):
        return self.points[1] if len(self.points) > 1 else self.points[0]

    def report_row(self, scale, image=None):
        return {"type": self.name, "angle": round(self.value(scale), 1),
                "unit": "deg"}


class CobbAngle(Annotation):
    """Angle between two independent lines - the standard spinal Cobb method."""
    kind = "cobb"
    name = "Cobb angle"
    min_points = 4
    max_points = 4

    def value(self, scale: Scale) -> float:
        if len(self.points) < 4:
            return 0.0
        p = self.points
        u = ((p[1][0] - p[0][0]) * scale.d_col, (p[1][1] - p[0][1]) * scale.d_row)
        w = ((p[3][0] - p[2][0]) * scale.d_col, (p[3][1] - p[2][1]) * scale.d_row)
        nu, nw = math.hypot(*u), math.hypot(*w)
        if nu == 0 or nw == 0:
            return 0.0
        cos = abs(u[0] * w[0] + u[1] * w[1]) / (nu * nw)
        return math.degrees(math.acos(max(-1.0, min(1.0, cos))))

    def path(self):
        path = QPainterPath()
        if len(self.points) >= 2:
            path.moveTo(*self.points[0])
            path.lineTo(*self.points[1])
        if len(self.points) >= 4:
            path.moveTo(*self.points[2])
            path.lineTo(*self.points[3])
        return path

    def hit_test(self, pt, tol):
        p = self.points
        if len(p) >= 2 and _point_segment_distance(pt, p[0], p[1]) <= tol:
            return True
        if len(p) >= 4 and _point_segment_distance(pt, p[2], p[3]) <= tol:
            return True
        return any(_dist(pt, q) <= tol for q in p)

    def describe(self, scale, image=None):
        if len(self.points) < 4:
            return []
        return [f"Cobb {self.value(scale):.1f}°"]

    def report_row(self, scale, image=None):
        return {"type": self.name, "angle": round(self.value(scale), 1),
                "unit": "deg"}


class Rectangle(RoiMixin, Annotation):
    kind = "rect"
    name = "Rectangle ROI"
    min_points = 2
    max_points = 2
    closed = True

    def rect(self) -> QRectF:
        return QRectF(QPointF(*self.points[0]), QPointF(*self.points[1])).normalized()

    def path(self):
        path = QPainterPath()
        path.addRect(self.rect())
        return path

    def handles(self):
        r = self.rect()
        return [[r.left(), r.top()], [r.right(), r.bottom()],
                [r.right(), r.top()], [r.left(), r.bottom()]]

    def move_handle(self, index, pt):
        r = self.rect()
        corners = {0: (r.right(), r.bottom()), 1: (r.left(), r.top()),
                   2: (r.left(), r.bottom()), 3: (r.right(), r.top())}
        fixed = corners.get(index, (r.left(), r.top()))
        self.points = [[fixed[0], fixed[1]], [float(pt[0]), float(pt[1])]]

    def hit_test(self, pt, tol):
        r = self.rect().adjusted(-tol, -tol, tol, tol)
        inner = self.rect().adjusted(tol, tol, -tol, -tol)
        p = QPointF(*pt)
        return r.contains(p) and not inner.contains(p)

    def describe(self, scale, image=None):
        if len(self.points) < 2:
            return []
        r = self.rect()
        out = [f"{scale.length(r.width(), 0):.1f} × "
               f"{scale.length(0, r.height()):.1f} {scale.unit}"]
        out += self.area_lines(scale, image)
        return out

    def anchor(self):
        r = self.rect()
        return [r.right(), r.top()]


class Ellipse(RoiMixin, Annotation):
    kind = "ellipse"
    name = "Ellipse ROI"
    min_points = 2
    max_points = 2
    closed = True

    rect = Rectangle.rect
    handles = Rectangle.handles
    move_handle = Rectangle.move_handle

    def path(self):
        path = QPainterPath()
        path.addEllipse(self.rect())
        return path

    def hit_test(self, pt, tol):
        r = self.rect()
        cx, cy = r.center().x(), r.center().y()
        a, b = max(r.width() / 2, 1e-6), max(r.height() / 2, 1e-6)
        d = ((pt[0] - cx) / a) ** 2 + ((pt[1] - cy) / b) ** 2
        span = tol / max(min(a, b), 1e-6)
        return abs(math.sqrt(d) - 1.0) <= max(span, 0.06)

    def describe(self, scale, image=None):
        if len(self.points) < 2:
            return []
        r = self.rect()
        out = [f"{scale.length(r.width(), 0):.1f} × "
               f"{scale.length(0, r.height()):.1f} {scale.unit}"]
        out += self.area_lines(scale, image)
        return out

    def anchor(self):
        r = self.rect()
        return [r.right() - r.width() * 0.15, r.top() + r.height() * 0.1]


class Polygon(RoiMixin, Annotation):
    kind = "polygon"
    name = "Polygon ROI"
    min_points = 3
    max_points = 512
    closed = True

    def describe(self, scale, image=None):
        if len(self.points) < 3:
            return []
        peri = sum(scale.length(b[0] - a[0], b[1] - a[1])
                   for a, b in zip(self.points, self.points[1:] + self.points[:1]))
        return [f"Perimeter {peri:.1f} {scale.unit}"] + self.area_lines(scale, image)

    def anchor(self):
        r = self.bounds()
        return [r.right(), r.top()]


class Freehand(Polygon):
    kind = "freehand"
    name = "Freehand ROI"
    min_points = 3
    max_points = 100000

    def handles(self):
        # Too many vertices to edit individually; expose a sparse subset.
        n = len(self.points)
        if n <= 12:
            return self.points
        step = max(1, n // 12)
        return self.points[::step]

    def move_handle(self, index, pt):
        n = len(self.points)
        step = max(1, n // 12) if n > 12 else 1
        real = min(index * step, n - 1)
        self.points[real] = [float(pt[0]), float(pt[1])]


class Arrow(Annotation):
    kind = "arrow"
    name = "Arrow"
    min_points = 2
    max_points = 2

    def describe(self, scale, image=None):
        return [self.text] if self.text else []

    def anchor(self):
        return self.points[-1]

    def report_row(self, scale, image=None):
        return {"type": self.name, "text": self.text}


class TextNote(Annotation):
    kind = "text"
    name = "Text"
    min_points = 1
    max_points = 1

    def __init__(self, points=None, color=DEFAULT_COLOR, text=""):
        super().__init__(points, color, text)
        self.label_offset = [0.0, 0.0]

    def hit_test(self, pt, tol):
        return bool(self.points) and _dist(pt, self.points[0]) <= tol + 10

    def describe(self, scale, image=None):
        return [line for line in (self.text or "").splitlines()]

    def report_row(self, scale, image=None):
        return {"type": self.name, "text": self.text}


ANNOTATION_TYPES = {c.kind: c for c in (
    Probe, Length, Polyline, Angle, CobbAngle, Rectangle, Ellipse,
    Polygon, Freehand, Arrow, TextNote,
)}


# --------------------------------------------------------------------------
# painting
# --------------------------------------------------------------------------

def paint_annotation(painter: QPainter, ann: Annotation, xform,
                     selected: bool, scale: Scale, image, show_labels=True,
                     hovered=False):
    """Draw one annotation.  ``xform`` maps image coords to widget coords."""
    if not ann.visible or not ann.points:
        return
    color = QColor(SELECTED_COLOR if selected else ann.color)
    pen = QPen(color, 2.0 if (selected or hovered) else 1.6)
    pen.setCosmetic(True)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    pts = [xform.map(QPointF(p[0], p[1])) for p in ann.points]

    if ann.kind == "probe":
        p = pts[0]
        painter.drawLine(QPointF(p.x() - 7, p.y()), QPointF(p.x() + 7, p.y()))
        painter.drawLine(QPointF(p.x(), p.y() - 7), QPointF(p.x(), p.y() + 7))
    elif ann.kind == "text":
        p = pts[0]
        painter.drawEllipse(p, 3, 3)
    elif ann.kind == "arrow":
        _draw_arrow(painter, pts[0], pts[-1], color)
    elif ann.kind == "cobb":
        if len(pts) >= 2:
            painter.drawLine(pts[0], pts[1])
        if len(pts) >= 4:
            painter.drawLine(pts[2], pts[3])
            _draw_cobb_extension(painter, pts, color)
    elif ann.kind in ("rect", "ellipse"):
        if len(pts) >= 2:
            r = QRectF(pts[0], pts[1]).normalized()
            if ann.kind == "rect":
                painter.drawRect(r)
            else:
                painter.drawEllipse(r)
    elif ann.kind in ("polygon", "freehand"):
        poly = QPolygonF(pts)
        painter.drawPolygon(poly)
    else:
        painter.drawPolyline(QPolygonF(pts))

    if ann.kind == "angle" and len(pts) >= 3:
        _draw_angle_arc(painter, pts, color)

    # end caps for linear measurements
    if ann.kind in ("length", "polyline"):
        for p in (pts[0], pts[-1]):
            painter.drawLine(QPointF(p.x() - 4, p.y() - 4), QPointF(p.x() + 4, p.y() + 4))
            painter.drawLine(QPointF(p.x() - 4, p.y() + 4), QPointF(p.x() + 4, p.y() - 4))

    if selected:
        painter.setBrush(color)
        for p in ann.handles():
            q = xform.map(QPointF(p[0], p[1]))
            painter.drawRect(QRectF(q.x() - HANDLE_RADIUS, q.y() - HANDLE_RADIUS,
                                    HANDLE_RADIUS * 2, HANDLE_RADIUS * 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)

    if show_labels:
        lines = ann.describe(scale, image)
        if ann.text and ann.kind not in ("text", "arrow"):
            lines = [ann.text] + lines
        if lines:
            anchor = xform.map(QPointF(*ann.anchor()))
            _draw_label(painter, anchor, ann.label_offset, lines, color)


def _draw_arrow(painter, tail, head, color):
    painter.drawLine(tail, head)
    ang = math.atan2(head.y() - tail.y(), head.x() - tail.x())
    size = 11.0
    for sign in (1, -1):
        a = ang + sign * math.radians(155)
        painter.drawLine(head, QPointF(head.x() + size * math.cos(a),
                                       head.y() + size * math.sin(a)))


def _draw_angle_arc(painter, pts, color):
    v, a, b = pts[1], pts[0], pts[2]
    r = min(28.0, max(14.0,
                      min(math.hypot(a.x() - v.x(), a.y() - v.y()),
                          math.hypot(b.x() - v.x(), b.y() - v.y())) * 0.45))
    a1 = math.degrees(math.atan2(-(a.y() - v.y()), a.x() - v.x()))
    a2 = math.degrees(math.atan2(-(b.y() - v.y()), b.x() - v.x()))
    span = (a2 - a1 + 540) % 360 - 180
    pen = painter.pen()
    dashed = QPen(pen)
    dashed.setStyle(Qt.PenStyle.DotLine)
    painter.setPen(dashed)
    painter.drawArc(QRectF(v.x() - r, v.y() - r, 2 * r, 2 * r),
                    int(a1 * 16), int(span * 16))
    painter.setPen(pen)


def _draw_cobb_extension(painter, pts, color):
    """Dotted perpendiculars that make the Cobb construction readable."""
    pen = QPen(color, 1.0)
    pen.setStyle(Qt.PenStyle.DotLine)
    pen.setCosmetic(True)
    old = painter.pen()
    painter.setPen(pen)
    mid1 = QPointF((pts[0].x() + pts[1].x()) / 2, (pts[0].y() + pts[1].y()) / 2)
    mid2 = QPointF((pts[2].x() + pts[3].x()) / 2, (pts[2].y() + pts[3].y()) / 2)
    painter.drawLine(mid1, mid2)
    painter.setPen(old)


def _draw_label(painter, anchor: QPointF, offset, lines, color: QColor):
    fm = painter.fontMetrics()
    w = max(fm.horizontalAdvance(t) for t in lines) + 8
    h = fm.height() * len(lines) + 6
    x = anchor.x() + offset[0]
    y = anchor.y() + offset[1] - h
    box = QRectF(x, y, w, h)
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 140))
    painter.drawRect(box)
    painter.setPen(QPen(color))
    ty = y + fm.ascent() + 3
    for line in lines:
        painter.drawText(QPointF(x + 4, ty), line)
        ty += fm.height()
    painter.restore()


def label_rect(fm, ann: Annotation, xform, scale, image) -> QRectF:
    """Screen rectangle occupied by an annotation's label (for hit testing).

    Takes a QFontMetrics rather than a QPainter so callers can measure outside
    a paint event, where constructing a QPainter on a widget is illegal.
    """
    lines = ann.describe(scale, image)
    if ann.text and ann.kind not in ("text", "arrow"):
        lines = [ann.text] + lines
    if not lines or not ann.points:
        return QRectF()
    w = max(fm.horizontalAdvance(t) for t in lines) + 8
    h = fm.height() * len(lines) + 6
    anchor = xform.map(QPointF(*ann.anchor()))
    return QRectF(anchor.x() + ann.label_offset[0],
                  anchor.y() + ann.label_offset[1] - h, w, h)
