"""The image viewport: rendering, mouse tools, overlays and annotations."""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import (QColor, QFont, QFontMetrics, QImage, QPainter,
                         QPainterPath, QPen, QTransform)
from PyQt6.QtWidgets import QInputDialog, QMenu, QWidget

from . import geometry as geo
from . import measure as ms
from . import windowing as wl

# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------

T_WINDOW = "window"
T_PAN = "pan"
T_ZOOM = "zoom"
T_SCROLL = "scroll"
T_SELECT = "select"
T_CROSSHAIR = "crosshair"
T_MAGNIFY = "magnify"
T_PROBE = "probe"
T_LENGTH = "length"
T_POLYLINE = "polyline"
T_ANGLE = "angle"
T_COBB = "cobb"
T_RECT = "rect"
T_ELLIPSE = "ellipse"
T_POLYGON = "polygon"
T_FREEHAND = "freehand"
T_ARROW = "arrow"
T_TEXT = "text"

ANNOTATION_TOOLS = {
    T_PROBE: ms.Probe, T_LENGTH: ms.Length, T_POLYLINE: ms.Polyline,
    T_ANGLE: ms.Angle, T_COBB: ms.CobbAngle, T_RECT: ms.Rectangle,
    T_ELLIPSE: ms.Ellipse, T_POLYGON: ms.Polygon, T_FREEHAND: ms.Freehand,
    T_ARROW: ms.Arrow, T_TEXT: ms.TextNote,
}

# tools built by clicking a sequence of points rather than one drag
CLICK_TOOLS = {T_POLYLINE, T_ANGLE, T_COBB, T_POLYGON}

CURSORS = {
    T_WINDOW: Qt.CursorShape.SizeAllCursor,
    T_PAN: Qt.CursorShape.OpenHandCursor,
    T_ZOOM: Qt.CursorShape.SizeVerCursor,
    T_SCROLL: Qt.CursorShape.SplitVCursor,
    T_SELECT: Qt.CursorShape.ArrowCursor,
    T_MAGNIFY: Qt.CursorShape.PointingHandCursor,
}

OVERLAY_COLOR = QColor(215, 225, 235)
ACCENT = QColor(0, 170, 235)
REFLINE_COLOR = QColor(255, 210, 60)


class Viewport(QWidget):
    """Displays one series; the fundamental unit of the viewing layout."""

    activated = pyqtSignal(object)
    sliceChanged = pyqtSignal(object, int)
    windowChanged = pyqtSignal(object, float, float)
    annotationsChanged = pyqtSignal(object)
    crosshairMoved = pyqtSignal(object, object)      # viewport, 3-D point
    seriesDropped = pyqtSignal(object, object)
    statusMessage = pyqtSignal(str)
    maximizeRequested = pyqtSignal(object)
    seriesChanged = pyqtSignal(object)
    transformChanged = pyqtSignal(object)   # zoom / pan altered

    def __init__(self, store, settings, parent=None):
        super().__init__(parent)
        self.setMinimumSize(120, 120)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setAutoFillBackground(False)

        self.store = store
        self.settings = settings

        self.series = None
        self.index = 0
        self.active = False
        self.empty_hint = ""      # shown instead of the drop prompt when set

        # display state
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.rotation = 0
        self.flip_h = False
        self.flip_v = False
        self.invert = False
        self.colormap = "Grayscale"
        self.smooth = True
        self.win_center = 0.0
        self.win_width = 1.0
        self.fit_pending = True

        # overlay switches
        self.show_overlay = True
        self.show_annotations = True
        self.show_reference_lines = True
        self.show_orientation = True
        self.show_scale_bar = True
        self.veterinary = False

        # interaction state
        self.tool = T_WINDOW
        self._drag_button = None
        self._drag_start = QPointF()
        self._drag_origin = None
        self._pending: ms.Annotation | None = None
        self._pending_preview = False
        self.selected: ms.Annotation | None = None
        self._hover: ms.Annotation | None = None
        self._grab_handle = -1
        self._grab_label = False
        self._moving = False
        self._magnifier_pos: QPointF | None = None
        self.crosshair: np.ndarray | None = None

        # render cache
        self._qimage = None
        self._qimage_buf = None
        self._cache_key = None

        # callbacks supplied by the main window
        self.reference_provider = None      # () -> list[Viewport]

        self._font = QFont("Consolas")
        self._font.setPixelSize(11)
        if not self._font.exactMatch():
            self._font = QFont("Courier New")
            self._font.setPixelSize(11)

    # ------------------------------------------------------------------
    # series binding
    # ------------------------------------------------------------------
    def set_series(self, series, index: int = 0, reset: bool = True):
        self.series = series
        self.empty_hint = ""
        self.index = max(0, min(index, len(series) - 1)) if series else 0
        if series and reset:
            self.reset_display()
            dw = series.default_window()
            if dw:
                self.win_center, self.win_width = dw
            else:
                img = self.image
                if img is not None:
                    self.win_center, self.win_width = wl.auto_window(img)
        self._cache_key = None
        self.fit_pending = True
        self.update()
        self.seriesChanged.emit(self)

    def clear(self, hint: str = ""):
        self.series = None
        self.index = 0
        self.empty_hint = hint
        self._qimage = None
        self.selected = None
        self._pending = None
        self.update()
        self.seriesChanged.emit(self)

    @property
    def instance(self):
        if not self.series or not len(self.series):
            return None
        return self.series[self.index]

    @property
    def image(self) -> np.ndarray | None:
        inst = self.instance
        return inst.pixels if inst else None

    @property
    def scale(self) -> ms.Scale:
        inst = self.instance
        return ms.Scale.from_instance(inst) if inst else ms.Scale(1, 1, False)

    @property
    def slice_count(self) -> int:
        return len(self.series) if self.series else 0

    # ------------------------------------------------------------------
    # display state
    # ------------------------------------------------------------------
    def reset_display(self):
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.rotation = 0
        self.flip_h = False
        self.flip_v = False
        self.invert = False
        self.colormap = "Grayscale"
        self.fit_pending = True

    def set_index(self, index: int, notify: bool = True):
        if not self.series:
            return
        index = max(0, min(int(index), len(self.series) - 1))
        if index == self.index:
            return
        self.index = index
        self._cache_key = None
        self.selected = None
        self.update()
        if notify:
            self.sliceChanged.emit(self, index)

    def step(self, delta: int):
        self.set_index(self.index + delta)

    def set_window(self, center: float, width: float, notify: bool = True):
        self.win_center = float(center)
        self.win_width = max(1e-6, float(width))
        self._cache_key = None
        self.update()
        if notify:
            self.windowChanged.emit(self, self.win_center, self.win_width)

    def auto_window(self):
        img = self.image
        if img is not None:
            self.set_window(*wl.auto_window(img))

    def full_window(self):
        img = self.image
        if img is not None:
            self.set_window(*wl.full_window(img))

    def default_window(self):
        if not self.series:
            return
        dw = self.series.default_window()
        if dw:
            self.set_window(*dw)
        else:
            self.auto_window()

    def rotate(self, degrees: int):
        self.rotation = (self.rotation + degrees) % 360
        self.update()

    def flip(self, horizontal: bool):
        if horizontal:
            self.flip_h = not self.flip_h
        else:
            self.flip_v = not self.flip_v
        self.update()

    def toggle_invert(self):
        self.invert = not self.invert
        self._cache_key = None
        self.update()

    def set_colormap(self, name: str):
        self.colormap = name
        self._cache_key = None
        self.update()

    def fit_to_window(self):
        img = self.image
        if img is None:
            return
        sx, sy = self._aspect()
        rot = (self.rotation // 90) % 2 == 1
        w = img.shape[1] * sx
        h = img.shape[0] * sy
        if rot:
            w, h = h, w
        if w <= 0 or h <= 0:
            return
        margin = 8
        self.zoom = min((self.width_px() - margin) / w, (self.height_px() - margin) / h)
        self.pan = QPointF(0, 0)
        self.fit_pending = False
        self.update()
        self.transformChanged.emit(self)

    def zoom_actual(self):
        """1 image pixel = 1 screen pixel."""
        sx, _ = self._aspect()
        self.zoom = 1.0 / sx if sx else 1.0
        self.pan = QPointF(0, 0)
        self.fit_pending = False
        self.update()
        self.transformChanged.emit(self)

    def zoom_by(self, factor: float, anchor: QPointF | None = None):
        old = self.zoom
        new = max(0.02, min(80.0, old * factor))
        if abs(new - old) < 1e-9:
            return
        if anchor is not None:
            # keep the anatomy under the cursor stationary
            before = self.widget_to_image(anchor)
            self.zoom = new
            after = self.image_to_widget(QPointF(*before))
            self.pan += anchor - after
        else:
            self.zoom = new
        self.fit_pending = False
        self.update()
        self.transformChanged.emit(self)

    def apply_transform_from(self, other: "Viewport"):
        """Copy another viewport's zoom and pan (used by linked zoom/pan)."""
        self.zoom = other.zoom
        self.pan = QPointF(other.pan)
        self.fit_pending = False
        self.update()

    def width_px(self) -> int:
        return max(1, self.width())

    def height_px(self) -> int:
        return max(1, self.height())

    def _aspect(self):
        """Screen units per image pixel, correcting non-square pixel spacing."""
        s = self.scale
        base = min(s.d_col, s.d_row) or 1.0
        return s.d_col / base, s.d_row / base

    # ------------------------------------------------------------------
    # coordinate transforms
    # ------------------------------------------------------------------
    def image_transform(self) -> QTransform:
        img = self.image
        t = QTransform()
        if img is None:
            return t
        sx, sy = self._aspect()
        t.translate(self.width_px() / 2 + self.pan.x(),
                    self.height_px() / 2 + self.pan.y())
        t.rotate(self.rotation)
        t.scale(self.zoom * (-1 if self.flip_h else 1),
                self.zoom * (-1 if self.flip_v else 1))
        t.scale(sx, sy)
        t.translate(-img.shape[1] / 2.0, -img.shape[0] / 2.0)
        return t

    def image_to_widget(self, p: QPointF) -> QPointF:
        return self.image_transform().map(p)

    def widget_to_image(self, p: QPointF) -> tuple[float, float]:
        inv, ok = self.image_transform().inverted()
        if not ok:
            return (0.0, 0.0)
        q = inv.map(p)
        return (q.x(), q.y())

    def pick_tolerance(self) -> float:
        """Selection tolerance converted from screen pixels to image pixels."""
        eff = max(self.zoom, 1e-6)
        return ms.PICK_TOLERANCE / eff

    def displayed_scale(self) -> float:
        """Screen pixels per image pixel along x, for the zoom readout."""
        sx, _ = self._aspect()
        return self.zoom * sx

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------
    def _build_qimage(self):
        img = self.image
        if img is None:
            self._qimage = None
            return
        key = (id(img), round(self.win_center, 4), round(self.win_width, 4),
               self.invert, self.colormap)
        if key == self._cache_key and self._qimage is not None:
            return
        gray = wl.apply_window(img, self.win_center, self.win_width, self.invert)
        gray = np.ascontiguousarray(gray)
        rgb = wl.colorize(gray, self.colormap)
        if rgb is None:
            self._qimage_buf = gray
            h, w = gray.shape
            self._qimage = QImage(self._qimage_buf.data, w, h, w,
                                  QImage.Format.Format_Grayscale8)
        else:
            self._qimage_buf = np.ascontiguousarray(rgb)
            h, w = rgb.shape[:2]
            self._qimage = QImage(self._qimage_buf.data, w, h, 3 * w,
                                  QImage.Format.Format_RGB888)
        self._cache_key = key

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self._font)
        painter.fillRect(self.rect(), QColor(0, 0, 0))

        if self.series is None:
            self._paint_empty(painter)
            self._paint_frame(painter)
            painter.end()
            return

        inst = self.instance
        if inst is not None and self.image is None:
            self._paint_decode_error(painter, inst)
            self._paint_frame(painter)
            painter.end()
            return

        if self.fit_pending:
            self.fit_to_window()

        self._build_qimage()
        if self._qimage is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                                  self.smooth and self.displayed_scale() < 4.0)
            painter.save()
            painter.setTransform(self.image_transform(), True)
            painter.drawImage(QPointF(0, 0), self._qimage)
            painter.restore()

        if self.show_reference_lines:
            self._paint_reference_lines(painter)
        if self.show_annotations:
            self._paint_annotations(painter)
        if self.crosshair is not None:
            self._paint_crosshair(painter)
        if self._magnifier_pos is not None:
            self._paint_magnifier(painter)
        if self.show_overlay:
            self._paint_overlay(painter)
        self._paint_frame(painter)
        painter.end()

    def _paint_empty(self, painter):
        painter.setPen(QColor(70, 78, 88))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                         "Drop a series here\nor double-click one in the list")

    def _paint_decode_error(self, painter, inst):
        """Show why an image could not be read instead of a blank viewport."""
        painter.setPen(QColor(226, 140, 120))
        text = inst.decode_error or "This image could not be read."
        rect = self.rect().adjusted(16, 16, -16, -16)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter)
                         | int(Qt.TextFlag.TextWordWrap),
                         f"Image {self.index + 1} of {self.slice_count}\n\n{text}")

    def _paint_frame(self, painter):
        pen = QPen(ACCENT if self.active else QColor(38, 44, 52), 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

    # -- annotations ---------------------------------------------------
    def current_annotations(self) -> list[ms.Annotation]:
        inst = self.instance
        if inst is None or self.series is None:
            return []
        return self.store.get(self.series.uid, inst.sop_uid)

    def _paint_annotations(self, painter):
        xform = self.image_transform()
        scale = self.scale
        img = self.image
        for ann in self.current_annotations():
            ms.paint_annotation(painter, ann, xform, ann is self.selected,
                                scale, img, hovered=ann is self._hover)
        if self._pending is not None and self._pending.points:
            ms.paint_annotation(painter, self._pending, xform, False, scale, img)

    # -- reference lines -----------------------------------------------
    def _paint_reference_lines(self, painter):
        if self.reference_provider is None or self.instance is None:
            return
        dst = self.instance.geometry
        if not dst.valid:
            return
        painter.save()
        xform = self.image_transform()
        for vp in self.reference_provider():
            if vp is self or vp.series is None or vp.instance is None:
                continue
            src = vp.instance.geometry
            if not src.valid or src is dst:
                continue
            line = geo.plane_intersection_line(src, dst)
            if line is None:
                continue
            (x0, y0), (x1, y1) = line
            pen = QPen(REFLINE_COLOR if vp.active else QColor(150, 160, 175),
                       1.4 if vp.active else 1.0)
            pen.setCosmetic(True)
            if not vp.active:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            p0 = xform.map(QPointF(x0, y0))
            p1 = xform.map(QPointF(x1, y1))
            painter.drawLine(p0, p1)
            if vp.active and vp.series is not None:
                label = f"{vp.series.number}"
                mid = QPointF((p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2)
                painter.drawText(mid + QPointF(4, -4), label)
        painter.restore()

    def _paint_crosshair(self, painter):
        inst = self.instance
        if inst is None or not inst.geometry.valid:
            return
        x, y = inst.geometry.to_pixel(self.crosshair)
        p = self.image_to_widget(QPointF(x, y))
        pen = QPen(QColor(255, 90, 90), 1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        r = 9
        painter.drawLine(QPointF(p.x() - r, p.y()), QPointF(p.x() - 3, p.y()))
        painter.drawLine(QPointF(p.x() + 3, p.y()), QPointF(p.x() + r, p.y()))
        painter.drawLine(QPointF(p.x(), p.y() - r), QPointF(p.x(), p.y() - 3))
        painter.drawLine(QPointF(p.x(), p.y() + 3), QPointF(p.x(), p.y() + r))

    def _paint_magnifier(self, painter):
        if self._qimage is None:
            return
        pos = self._magnifier_pos
        radius = 90
        factor = 3.0
        path = QPainterPath()
        path.addEllipse(pos, radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        lens = QTransform()
        lens.translate(pos.x(), pos.y())
        lens.scale(factor, factor)
        lens.translate(-pos.x(), -pos.y())
        # QTransform multiplication applies the left operand first.
        painter.setTransform(self.image_transform() * lens, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(QPointF(0, 0), self._qimage)
        painter.restore()
        pen = QPen(ACCENT, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(pos, radius, radius)
        painter.drawText(QPointF(pos.x() - 14, pos.y() + radius + 14),
                         f"{factor:.0f}×")

    # -- text overlay ---------------------------------------------------
    def _paint_overlay(self, painter):
        inst = self.instance
        if inst is None or self.series is None:
            return
        painter.setPen(OVERLAY_COLOR)
        fm = QFontMetrics(self._font)
        lh = fm.height()
        pad = 6
        w, h = self.width_px(), self.height_px()

        study = _study_of(self.series)
        pat = study.patient_info() if study else {}
        sinfo = study.study_info() if study else {}

        # top-left: patient
        tl = []
        if pat.get("name"):
            tl.append(pat["name"])
        ident = " ".join(x for x in [pat.get("id", ""), pat.get("sex", ""),
                                     pat.get("age", "")] if x)
        if ident:
            tl.append(ident)
        if pat.get("breed"):
            tl.append(pat["breed"])
        if sinfo.get("institution"):
            tl.append(sinfo["institution"])

        # top-right: study / series
        tr = []
        if sinfo.get("description"):
            tr.append(sinfo["description"])
        tr.append(f"{sinfo.get('date', '')} {sinfo.get('time', '')}".strip())
        tr.append(f"Se {self.series.number}: {self.series.description}")
        tr.append(f"{self.series.modality}  "
                  f"{self.series.plane_label(self.veterinary)}")

        # bottom-left: display state
        bl = []
        bl.append(f"Im {self.index + 1}/{self.slice_count}"
                  f"   #{inst.number}")
        bl.append(f"W {self.win_width:.0f}  L {self.win_center:.0f}")
        bl.append(f"Zoom {self.displayed_scale() * 100:.0f}%")
        flags = []
        if self.invert:
            flags.append("INV")
        if self.rotation:
            flags.append(f"R{self.rotation}")
        if self.flip_h:
            flags.append("FH")
        if self.flip_v:
            flags.append("FV")
        if self.colormap != "Grayscale":
            flags.append(self.colormap)
        if flags:
            bl.append(" ".join(flags))

        # bottom-right: acquisition
        br = []
        thk = inst.num("SliceThickness")
        loc = inst.slice_location
        if thk is not None:
            line = f"Thk {thk:.1f} mm"
            sp = self.series.slice_spacing
            if sp:
                line += f"  Sp {sp:.1f}"
            br.append(line)
        if loc is not None:
            br.append(f"Loc {loc:+.1f} mm")
        tr_ = inst.num("RepetitionTime")
        te = inst.num("EchoTime")
        if tr_ is not None and te is not None:
            br.append(f"TR {tr_:.0f}  TE {te:.0f}")
        fs = inst.num("MagneticFieldStrength")
        kvp = inst.num("KVP")
        if kvp is not None:
            ma = inst.num("XRayTubeCurrent")
            br.append(f"{kvp:.0f} kVp" + (f"  {ma:.0f} mA" if ma else ""))
        elif fs is not None:
            br.append(f"{fs:.1f} T")
        s = self.scale
        if s.calibrated:
            br.append(f"{inst.cols}×{inst.rows}  {s.d_col:.3f} mm/px")
        else:
            br.append(f"{inst.cols}×{inst.rows}  uncalibrated")

        def draw_block(lines, right: bool, bottom: bool):
            lines = [t for t in lines if t]
            if not lines:
                return
            y = (h - pad - lh * len(lines) + fm.ascent()) if bottom else (pad + fm.ascent())
            for line in lines:
                x = (w - pad - fm.horizontalAdvance(line)) if right else pad
                painter.drawText(QPointF(x, y), line)
                y += lh

        draw_block(tl, False, False)
        draw_block(tr, True, False)
        draw_block(bl, False, True)
        draw_block(br, True, True)

        if self.show_orientation:
            self._paint_orientation(painter, fm)
        if self.show_scale_bar:
            self._paint_scale_bar(painter, fm)

    def _paint_orientation(self, painter, fm):
        inst = self.instance
        if inst is None:
            return
        labels = geo.edge_labels(inst.geometry, self.veterinary)
        if not labels:
            return
        labels = geo.transform_edge_labels(labels, self.rotation,
                                           self.flip_h, self.flip_v)
        painter.setPen(QColor(255, 235, 130))
        w, h = self.width_px(), self.height_px()
        cx, cy = w / 2, h / 2
        m = 5
        for edge, text in labels.items():
            if not text:
                continue
            if edge == "left":
                pos = QPointF(m, cy + fm.ascent() / 2)
            elif edge == "right":
                pos = QPointF(w - m - fm.horizontalAdvance(text), cy + fm.ascent() / 2)
            elif edge == "top":
                pos = QPointF(cx - fm.horizontalAdvance(text) / 2, m + fm.ascent())
            else:
                pos = QPointF(cx - fm.horizontalAdvance(text) / 2, h - m)
            painter.drawText(pos, text)

    def _paint_scale_bar(self, painter, fm):
        s = self.scale
        if not s.calibrated:
            return
        px_per_mm = self.displayed_scale() / (s.d_col or 1.0)
        if px_per_mm <= 0:
            return
        target = self.height_px() * 0.30
        candidates = [1, 2, 5, 10, 20, 50, 100, 200, 500]
        length_mm = min(candidates, key=lambda c: abs(c * px_per_mm - target))
        bar = length_mm * px_per_mm
        if bar < 18 or bar > self.height_px() * 0.85:
            return
        x = self.width_px() - 16
        y1 = self.height_px() / 2 + bar / 2
        y0 = y1 - bar
        painter.setPen(QPen(OVERLAY_COLOR, 1))
        painter.drawLine(QPointF(x, y0), QPointF(x, y1))
        ticks = 10 if length_mm >= 10 else length_mm
        for i in range(int(ticks) + 1):
            yy = y0 + (bar * i / ticks)
            long = (i % 5 == 0)
            painter.drawLine(QPointF(x - (6 if long else 3), yy), QPointF(x, yy))
        text = f"{length_mm} mm"
        painter.drawText(QPointF(x - 8 - fm.horizontalAdvance(text), y0 - 3), text)

    # ------------------------------------------------------------------
    # mouse handling
    # ------------------------------------------------------------------
    def _activate(self):
        if not self.active:
            self.activated.emit(self)

    def mousePressEvent(self, event):
        self._activate()
        self.setFocus()
        pos = QPointF(event.position())
        btn = event.button()
        self._drag_button = btn
        self._drag_start = pos
        self._drag_origin = (self.win_center, self.win_width, QPointF(self.pan), self.zoom,
                             self.index)
        if self.series is None:
            return

        mods = event.modifiers()
        if btn == Qt.MouseButton.MiddleButton:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if btn == Qt.MouseButton.RightButton:
            return
        if btn != Qt.MouseButton.LeftButton:
            return

        if mods & Qt.KeyboardModifier.ControlModifier:
            self._drag_button = "ctrl-zoom"
            return

        tool = self.tool
        if tool in ANNOTATION_TOOLS:
            self._begin_annotation(pos, tool)
        elif tool == T_SELECT:
            self._begin_select(pos)
        elif tool == T_CROSSHAIR:
            self._emit_crosshair(pos)
        elif tool == T_MAGNIFY:
            self._magnifier_pos = pos
            self.update()
        elif tool == T_PAN:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        pos = QPointF(event.position())
        if self.series is None:
            return
        btn = self._drag_button
        delta = pos - self._drag_start

        if btn is None:
            self._update_hover(pos)
            self._report_position(pos)
            if self.tool == T_MAGNIFY and self._magnifier_pos is not None:
                self._magnifier_pos = pos
                self.update()
            return

        if btn == Qt.MouseButton.MiddleButton or (btn == Qt.MouseButton.LeftButton
                                                  and self.tool == T_PAN):
            self.pan = self._drag_origin[2] + delta
            self.fit_pending = False
            self.update()
            self.transformChanged.emit(self)
            return
        if btn == Qt.MouseButton.RightButton or btn == "ctrl-zoom":
            factor = math.exp(-delta.y() / 180.0)
            self.zoom = max(0.02, min(80.0, self._drag_origin[3] * factor))
            self.fit_pending = False
            self.update()
            self.transformChanged.emit(self)
            return
        if btn != Qt.MouseButton.LeftButton:
            return

        tool = self.tool
        if tool == T_WINDOW:
            c0, w0 = self._drag_origin[0], self._drag_origin[1]
            span = max(abs(w0), 1.0)
            sens = span / 250.0
            self.set_window(c0 + delta.y() * sens, max(1.0, w0 + delta.x() * sens))
        elif tool == T_ZOOM:
            factor = math.exp(-delta.y() / 180.0)
            self.zoom = max(0.02, min(80.0, self._drag_origin[3] * factor))
            self.fit_pending = False
            self.update()
            self.transformChanged.emit(self)
        elif tool == T_SCROLL:
            self.set_index(self._drag_origin[4] + int(delta.y() / 6))
        elif tool == T_MAGNIFY:
            self._magnifier_pos = pos
            self.update()
        elif tool == T_CROSSHAIR:
            self._emit_crosshair(pos)
        elif tool == T_SELECT:
            self._drag_select(pos)
        elif tool in ANNOTATION_TOOLS:
            self._drag_annotation(pos)

    def mouseReleaseEvent(self, event):
        pos = QPointF(event.position())
        btn = event.button()
        moved = (pos - self._drag_start).manhattanLength() > 3

        if btn == Qt.MouseButton.RightButton and not moved:
            self._drag_button = None
            if self._pending is not None and self.tool in CLICK_TOOLS:
                self._finish_pending()
            else:
                self._context_menu(event.globalPosition().toPoint())
            return

        if btn == Qt.MouseButton.LeftButton and self.series is not None:
            if self.tool in ANNOTATION_TOOLS and self.tool not in CLICK_TOOLS:
                self._end_annotation(moved)
            elif self.tool == T_MAGNIFY:
                self._magnifier_pos = None
                self.update()
            elif self.tool == T_SELECT and self._moving:
                self._moving = False
                self._grab_handle = -1
                self._grab_label = False
                self.annotationsChanged.emit(self)

        self._drag_button = None
        self.setCursor(CURSORS.get(self.tool, Qt.CursorShape.CrossCursor))

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._pending is not None and self.tool in CLICK_TOOLS:
            self._finish_pending()
            return
        if self.tool == T_SELECT and self.selected is not None:
            self._edit_text(self.selected)
            return
        self.maximizeRequested.emit(self)

    def wheelEvent(self, event):
        self._activate()
        if self.series is None:
            return
        steps = event.angleDelta().y() / 120.0
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(1.15 ** steps, QPointF(event.position()))
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            self.step(int(-steps) * 10)
        else:
            self.step(int(-steps) if steps else 0)
        event.accept()

    def leaveEvent(self, event):
        if self._magnifier_pos is not None:
            self._magnifier_pos = None
            self.update()
        self._hover = None
        super().leaveEvent(event)

    def _report_position(self, pos: QPointF):
        img = self.image
        if img is None:
            return
        x, y = self.widget_to_image(pos)
        xi, yi = int(math.floor(x)), int(math.floor(y))
        if 0 <= yi < img.shape[0] and 0 <= xi < img.shape[1]:
            v = img[yi, xi]
            val = f"{v:.1f}" if isinstance(v, (float, np.floating)) else f"{int(v)}"
            inst = self.instance
            extra = ""
            if inst is not None and inst.geometry.valid:
                p = inst.geometry.to_patient(x, y)
                extra = f"   LPS ({p[0]:+.1f}, {p[1]:+.1f}, {p[2]:+.1f}) mm"
            self.statusMessage.emit(f"({xi}, {yi})  value {val}{extra}")

    # -- annotation interaction ----------------------------------------
    def _begin_annotation(self, pos: QPointF, tool: str):
        cls = ANNOTATION_TOOLS[tool]
        pt = self.widget_to_image(pos)
        if tool == T_TEXT:
            text, ok = QInputDialog.getText(self, "Text annotation", "Text:")
            if ok and text.strip():
                ann = cls(points=[list(pt)], color=self.settings["annotation_color"],
                          text=text.strip())
                self._commit(ann)
            return
        if tool == T_PROBE:
            ann = cls(points=[list(pt)], color=self.settings["annotation_color"])
            self._commit(ann)
            return
        if tool in CLICK_TOOLS:
            if self._pending is None:
                self._pending = cls(points=[list(pt), list(pt)],
                                    color=self.settings["annotation_color"])
                self._pending_preview = True
            else:
                # fix the preview vertex and start a new one
                self._pending.points[-1] = list(pt)
                if len(self._pending.points) >= self._pending.max_points:
                    self._finish_pending()
                    return
                self._pending.points.append(list(pt))
            self.update()
            return
        # drag tools
        self._pending = cls(points=[list(pt), list(pt)],
                            color=self.settings["annotation_color"])
        self.update()

    def _drag_annotation(self, pos: QPointF):
        if self._pending is None:
            return
        pt = self.widget_to_image(pos)
        if self.tool == T_FREEHAND:
            last = self._pending.points[-1]
            if math.hypot(pt[0] - last[0], pt[1] - last[1]) > self.pick_tolerance() / 3:
                self._pending.points.append(list(pt))
        else:
            self._pending.points[-1] = list(pt)
        self.update()

    def _end_annotation(self, moved: bool):
        ann = self._pending
        if ann is None:
            return
        self._pending = None
        if not moved and ann.kind not in ("probe", "text"):
            self.update()
            return
        if ann.kind in ("rect", "ellipse"):
            r = ann.bounds()
            if r.width() < 1 or r.height() < 1:
                self.update()
                return
        if ann.is_complete():
            self._commit(ann)
        else:
            self.update()

    def _finish_pending(self):
        ann = self._pending
        self._pending = None
        if ann is None:
            return
        if self._pending_preview and len(ann.points) > ann.min_points:
            ann.points.pop()          # drop the un-placed preview vertex
        self._pending_preview = False
        if ann.is_complete():
            self._commit(ann)
        else:
            self.update()

    def _commit(self, ann: ms.Annotation):
        inst = self.instance
        if inst is None:
            return
        self.store.add(self.series.uid, inst.sop_uid, ann)
        self.selected = ann
        self.annotationsChanged.emit(self)
        self.update()

    def _begin_select(self, pos: QPointF):
        pt = self.widget_to_image(pos)
        tol = self.pick_tolerance()
        anns = self.current_annotations()
        # handles of the current selection win over other objects
        if self.selected is not None and self.selected in anns:
            idx = self.selected.handle_at(pt, tol)
            if idx >= 0 and not self.selected.locked:
                self._grab_handle = idx
                self._moving = True
                return
        for ann in reversed(anns):
            if ann.hit_test(pt, tol):
                self.selected = ann
                self._grab_handle = -1
                self._moving = not ann.locked
                self._move_anchor = pt
                self.update()
                return
        # label drag - measured with font metrics, never a live QPainter
        fm = QFontMetrics(self._font)
        xform = self.image_transform()
        for ann in reversed(anns):
            r = ms.label_rect(fm, ann, xform, self.scale, self.image)
            if r.isValid() and r.contains(pos):
                self.selected = ann
                self._grab_label = True
                self._moving = True
                self.update()
                return
        self.selected = None
        self.update()

    def _drag_select(self, pos: QPointF):
        if not self._moving or self.selected is None:
            return
        pt = self.widget_to_image(pos)
        if self._grab_label:
            anchor = self.image_to_widget(QPointF(*self.selected.anchor()))
            self.selected.label_offset = [pos.x() - anchor.x(),
                                          pos.y() - anchor.y()]
        elif self._grab_handle >= 0:
            self.selected.move_handle(self._grab_handle, pt)
        else:
            prev = getattr(self, "_move_anchor", pt)
            self.selected.translate(pt[0] - prev[0], pt[1] - prev[1])
            self._move_anchor = pt
        self.store.dirty = True
        self.update()

    def _update_hover(self, pos: QPointF):
        if self.tool != T_SELECT:
            if self._hover is not None:
                self._hover = None
                self.update()
            return
        pt = self.widget_to_image(pos)
        tol = self.pick_tolerance()
        found = None
        for ann in reversed(self.current_annotations()):
            if ann.hit_test(pt, tol):
                found = ann
                break
        if found is not self._hover:
            self._hover = found
            self.setCursor(Qt.CursorShape.SizeAllCursor if found
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def _edit_text(self, ann):
        text, ok = QInputDialog.getMultiLineText(self, "Edit annotation",
                                                 "Text:", ann.text)
        if ok:
            ann.text = text.strip()
            self.store.dirty = True
            self.annotationsChanged.emit(self)
            self.update()

    def delete_selected(self):
        if self.selected is None:
            return
        self.store.remove(self.selected)
        self.selected = None
        self.annotationsChanged.emit(self)
        self.update()

    def clear_image_annotations(self):
        inst = self.instance
        if inst is None or self.series is None:
            return
        self.store.clear_image(self.series.uid, inst.sop_uid)
        self.selected = None
        self.annotationsChanged.emit(self)
        self.update()

    # -- crosshair ------------------------------------------------------
    def _emit_crosshair(self, pos: QPointF):
        inst = self.instance
        if inst is None or not inst.geometry.valid:
            return
        x, y = self.widget_to_image(pos)
        point = inst.geometry.to_patient(x, y)
        self.crosshair = point
        self.update()
        self.crosshairMoved.emit(self, point)

    def set_crosshair(self, point):
        self.crosshair = np.asarray(point, dtype=float) if point is not None else None
        self.update()

    # -- context menu ---------------------------------------------------
    def _context_menu(self, global_pos: QPoint):
        menu = QMenu(self)
        if self.selected is not None:
            menu.addAction("Edit label…", lambda: self._edit_text(self.selected))
            lock = menu.addAction("Locked")
            lock.setCheckable(True)
            lock.setChecked(self.selected.locked)
            lock.triggered.connect(self._toggle_lock)
            menu.addAction("Delete annotation", self.delete_selected)
            menu.addSeparator()
        menu.addAction("Fit to window", self.fit_to_window)
        menu.addAction("Actual size (100%)", self.zoom_actual)
        menu.addAction("Reset display", lambda: (self.reset_display(),
                                                 self.default_window(),
                                                 self.update()))
        menu.addSeparator()
        menu.addAction("Invert", self.toggle_invert)
        menu.addAction("Auto window", self.auto_window)
        menu.addAction("Default window", self.default_window)
        menu.addSeparator()
        menu.addAction("Clear annotations on this image",
                       self.clear_image_annotations)
        menu.exec(global_pos)

    def _toggle_lock(self, checked):
        if self.selected is not None:
            self.selected.locked = checked
            self.store.dirty = True

    # ------------------------------------------------------------------
    # drag and drop of series
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-dicom-series"):
            event.acceptProposedAction()

    def dropEvent(self, event):
        data = event.mimeData().data("application/x-dicom-series")
        uid = bytes(data).decode("utf-8", "ignore")
        self.seriesDropped.emit(self, uid)
        event.acceptProposedAction()

    # ------------------------------------------------------------------
    def set_tool(self, tool: str):
        self.tool = tool
        self._pending = None
        self._pending_preview = False
        if tool != T_MAGNIFY:
            self._magnifier_pos = None
        self.setCursor(CURSORS.get(tool, Qt.CursorShape.CrossCursor))
        self.update()

    def render_image(self, with_overlay: bool = True,
                     scale: float = 1.0) -> QImage | None:
        """Render the viewport to an off-screen image for export."""
        w = int(self.width_px() * scale)
        h = int(self.height_px() * scale)
        if w <= 0 or h <= 0:
            return None
        out = QImage(w, h, QImage.Format.Format_RGB32)
        out.fill(QColor(0, 0, 0))
        saved = self.show_overlay
        self.show_overlay = with_overlay
        painter = QPainter(out)
        painter.scale(scale, scale)
        painter.setFont(self._font)
        self._build_qimage()
        if self._qimage is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.smooth)
            painter.save()
            painter.setTransform(self.image_transform(), True)
            painter.drawImage(QPointF(0, 0), self._qimage)
            painter.restore()
        if self.show_reference_lines:
            self._paint_reference_lines(painter)
        if self.show_annotations:
            self._paint_annotations(painter)
        if with_overlay:
            self._paint_overlay(painter)
        painter.end()
        self.show_overlay = saved
        return out


def _study_of(series):
    """Backlink from a series to its study (set by the loader)."""
    return getattr(series, "study", None)
