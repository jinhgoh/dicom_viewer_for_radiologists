"""Vector tool icons drawn at runtime, so the app ships without image assets."""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QIcon, QPainter, QPainterPath,
                         QPen, QPixmap, QPolygonF)

SIZE = 22
STROKE = QColor("#c8d5e3")
DIM = QColor("#7d8fa3")
HILITE = QColor("#5cc0f2")

_CACHE: dict[str, QIcon] = {}


def _canvas():
    pm = QPixmap(SIZE, SIZE)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(STROKE, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    return pm, p


def _text_icon(letter: str, color: QColor = STROKE) -> QPixmap:
    pm, p = _canvas()
    f = QFont()
    f.setPixelSize(14)
    f.setBold(True)
    p.setFont(f)
    p.setPen(color)
    p.drawText(QRectF(0, 0, SIZE, SIZE), Qt.AlignmentFlag.AlignCenter, letter)
    p.end()
    return pm


def _handles(p: QPainter, points, r: float = 1.9):
    p.setBrush(QBrush(HILITE))
    p.setPen(QPen(HILITE, 1.0))
    for x, y in points:
        p.drawEllipse(QPointF(x, y), r, r)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(STROKE, 1.4))


# --------------------------------------------------------------------------
# individual icons
# --------------------------------------------------------------------------

def _window_level():
    pm, p = _canvas()
    rect = QRectF(3, 3, 16, 16)
    p.drawEllipse(rect)
    path = QPainterPath()
    path.moveTo(11, 3)
    path.arcTo(rect, 90, -180)
    path.closeSubpath()
    p.fillPath(path, QBrush(STROKE))
    p.end()
    return pm


def _select():
    pm, p = _canvas()
    arrow = QPolygonF([QPointF(6, 3), QPointF(6, 17), QPointF(10, 13),
                       QPointF(12.5, 18.5), QPointF(15, 17.3),
                       QPointF(12.5, 12), QPointF(17, 11.5)])
    p.setBrush(QBrush(STROKE))
    p.drawPolygon(arrow)
    p.end()
    return pm


def _pan():
    pm, p = _canvas()
    c = SIZE / 2
    p.drawLine(QPointF(c, 3), QPointF(c, 19))
    p.drawLine(QPointF(3, c), QPointF(19, c))
    p.setBrush(QBrush(STROKE))
    for dx, dy, ang in ((0, -1, 0), (0, 1, 180), (-1, 0, 270), (1, 0, 90)):
        tip = QPointF(c + dx * 8.5, c + dy * 8.5)
        a = math.radians(ang - 90)
        head = QPolygonF([
            tip,
            QPointF(tip.x() - 3.4 * math.cos(a - 0.5), tip.y() - 3.4 * math.sin(a - 0.5)),
            QPointF(tip.x() - 3.4 * math.cos(a + 0.5), tip.y() - 3.4 * math.sin(a + 0.5)),
        ])
        p.drawPolygon(head)
    p.end()
    return pm


def _zoom(sign: str = "+"):
    pm, p = _canvas()
    p.drawEllipse(QRectF(3, 3, 12, 12))
    p.setPen(QPen(STROKE, 2.0))
    p.drawLine(QPointF(13.5, 13.5), QPointF(19, 19))
    p.setPen(QPen(STROKE, 1.4))
    p.drawLine(QPointF(6, 9), QPointF(12, 9))
    if sign == "+":
        p.drawLine(QPointF(9, 6), QPointF(9, 12))
    p.end()
    return pm


def _stack():
    pm, p = _canvas()
    for i, y in enumerate((4, 8.5, 13)):
        p.setPen(QPen(STROKE if i == 1 else DIM, 1.4))
        p.drawRect(QRectF(4, y, 14, 4))
    p.end()
    return pm


def _crosshair():
    pm, p = _canvas()
    c = SIZE / 2
    p.drawEllipse(QRectF(4, 4, 14, 14))
    p.drawLine(QPointF(c, 1.5), QPointF(c, 7))
    p.drawLine(QPointF(c, 15), QPointF(c, 20.5))
    p.drawLine(QPointF(1.5, c), QPointF(7, c))
    p.drawLine(QPointF(15, c), QPointF(20.5, c))
    p.end()
    return pm


def _magnify():
    pm, p = _canvas()
    p.drawEllipse(QRectF(2.5, 2.5, 13, 13))
    p.setPen(QPen(STROKE, 2.2))
    p.drawLine(QPointF(14, 14), QPointF(19.5, 19.5))
    p.end()
    return pm


def _probe():
    pm, p = _canvas()
    c = SIZE / 2
    p.drawLine(QPointF(c, 3), QPointF(c, 19))
    p.drawLine(QPointF(3, c), QPointF(19, c))
    p.setBrush(QBrush(HILITE))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(c, c), 2.6, 2.6)
    p.end()
    return pm


def _length():
    pm, p = _canvas()
    p.drawLine(QPointF(4, 17), QPointF(18, 5))
    _handles(p, [(4, 17), (18, 5)])
    p.end()
    return pm


def _polyline():
    pm, p = _canvas()
    pts = [(3, 16), (8, 7), (14, 14), (19, 5)]
    p.drawPolyline(QPolygonF([QPointF(*q) for q in pts]))
    _handles(p, pts, 1.6)
    p.end()
    return pm


def _angle():
    pm, p = _canvas()
    p.drawLine(QPointF(4, 18), QPointF(18, 18))
    p.drawLine(QPointF(4, 18), QPointF(16, 5))
    pen = QPen(DIM, 1.0, Qt.PenStyle.DotLine)
    p.setPen(pen)
    p.drawArc(QRectF(-1, 13, 14, 14), 0, 47 * 16)
    p.setPen(QPen(STROKE, 1.4))
    _handles(p, [(4, 18), (18, 18), (16, 5)], 1.6)
    p.end()
    return pm


def _cobb():
    pm, p = _canvas()
    p.drawLine(QPointF(3, 6), QPointF(15, 4))
    p.drawLine(QPointF(6, 18), QPointF(19, 15))
    pen = QPen(DIM, 1.0, Qt.PenStyle.DotLine)
    p.setPen(pen)
    p.drawLine(QPointF(9, 5), QPointF(12.5, 16.5))
    p.setPen(QPen(STROKE, 1.4))
    _handles(p, [(3, 6), (15, 4), (6, 18), (19, 15)], 1.5)
    p.end()
    return pm


def _rect():
    pm, p = _canvas()
    p.drawRect(QRectF(4, 6, 14, 11))
    _handles(p, [(4, 6), (18, 17)], 1.6)
    p.end()
    return pm


def _ellipse():
    pm, p = _canvas()
    p.drawEllipse(QRectF(3, 6, 16, 11))
    _handles(p, [(3, 6), (19, 17)], 1.6)
    p.end()
    return pm


def _polygon():
    pm, p = _canvas()
    pts = [(11, 3), (19, 9), (16, 18), (6, 18), (3, 9)]
    p.drawPolygon(QPolygonF([QPointF(*q) for q in pts]))
    _handles(p, pts, 1.4)
    p.end()
    return pm


def _freehand():
    pm, p = _canvas()
    path = QPainterPath()
    path.moveTo(6, 15)
    path.cubicTo(2, 8, 9, 2, 13, 5)
    path.cubicTo(19, 8, 20, 15, 14, 18)
    path.cubicTo(11, 19.5, 8, 18, 6, 15)
    p.drawPath(path)
    p.end()
    return pm


def _arrow():
    pm, p = _canvas()
    p.drawLine(QPointF(4, 18), QPointF(16, 6))
    p.setBrush(QBrush(STROKE))
    p.drawPolygon(QPolygonF([QPointF(18, 4), QPointF(11, 6), QPointF(16, 11)]))
    p.end()
    return pm


def _invert():
    pm, p = _canvas()
    rect = QRectF(3, 3, 16, 16)
    p.drawEllipse(rect)
    path = QPainterPath()
    path.moveTo(11, 3)
    path.arcTo(rect, 90, 180)
    path.closeSubpath()
    p.fillPath(path, QBrush(STROKE))
    p.end()
    return pm


def _rotate(clockwise: bool = True):
    pm, p = _canvas()
    rect = QRectF(4, 4, 14, 14)
    p.drawArc(rect, 40 * 16, 260 * 16)
    p.setBrush(QBrush(STROKE))
    if clockwise:
        p.drawPolygon(QPolygonF([QPointF(19, 8), QPointF(13.5, 8.5),
                                 QPointF(17, 13)]))
    else:
        p.drawPolygon(QPolygonF([QPointF(3, 8), QPointF(8.5, 8.5),
                                 QPointF(5, 13)]))
    p.end()
    return pm


def _flip(horizontal: bool = True):
    pm, p = _canvas()
    c = SIZE / 2
    pen = QPen(DIM, 1.0, Qt.PenStyle.DashLine)
    p.setPen(pen)
    if horizontal:
        p.drawLine(QPointF(c, 2), QPointF(c, 20))
    else:
        p.drawLine(QPointF(2, c), QPointF(20, c))
    p.setPen(QPen(STROKE, 1.4))
    p.setBrush(QBrush(STROKE))
    if horizontal:
        p.drawPolygon(QPolygonF([QPointF(3, 6), QPointF(9, 11), QPointF(3, 16)]))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(QPolygonF([QPointF(19, 6), QPointF(13, 11), QPointF(19, 16)]))
    else:
        p.drawPolygon(QPolygonF([QPointF(6, 3), QPointF(11, 9), QPointF(16, 3)]))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(QPolygonF([QPointF(6, 19), QPointF(11, 13), QPointF(16, 19)]))
    p.end()
    return pm


def _fit():
    pm, p = _canvas()
    p.drawRect(QRectF(3, 4, 16, 14))
    p.setPen(QPen(HILITE, 1.4))
    for x0, y0, x1, y1 in ((6, 7, 10, 7), (6, 7, 6, 11),
                           (16, 15, 12, 15), (16, 15, 16, 11)):
        p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    p.end()
    return pm


def _reset():
    pm, p = _canvas()
    p.drawArc(QRectF(4, 4, 14, 14), 60 * 16, 280 * 16)
    p.setBrush(QBrush(STROKE))
    p.drawPolygon(QPolygonF([QPointF(11, 1.5), QPointF(11, 7.5), QPointF(15.5, 4.5)]))
    p.end()
    return pm


def _reference():
    pm, p = _canvas()
    p.setPen(QPen(DIM, 1.3))
    p.drawRect(QRectF(3, 3, 16, 16))
    p.setPen(QPen(HILITE, 1.5, Qt.PenStyle.DashLine))
    p.drawLine(QPointF(3.5, 15), QPointF(18.5, 7))
    p.end()
    return pm


def _tags():
    pm, p = _canvas()
    path = QPainterPath()
    path.moveTo(3, 10)
    path.lineTo(10, 3)
    path.lineTo(19, 3)
    path.lineTo(19, 12)
    path.lineTo(12, 19)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(QBrush(STROKE))
    p.drawEllipse(QPointF(15, 7), 1.7, 1.7)
    p.end()
    return pm


def _mpr():
    pm, p = _canvas()
    p.setPen(QPen(DIM, 1.3))
    p.drawRect(QRectF(2.5, 2.5, 17, 17))
    p.setPen(QPen(STROKE, 1.4))
    p.drawLine(QPointF(11, 2.5), QPointF(11, 19.5))
    p.drawLine(QPointF(2.5, 11), QPointF(19.5, 11))
    p.setPen(QPen(HILITE, 1.2))
    p.drawLine(QPointF(4, 17), QPointF(18, 5))
    p.end()
    return pm


def _cine():
    pm, p = _canvas()
    p.setBrush(QBrush(STROKE))
    p.drawPolygon(QPolygonF([QPointF(6, 4), QPointF(18, 11), QPointF(6, 18)]))
    p.end()
    return pm


def _open():
    pm, p = _canvas()
    path = QPainterPath()
    path.moveTo(2, 17)
    path.lineTo(4.5, 8)
    path.lineTo(20, 8)
    path.lineTo(17.5, 17)
    path.closeSubpath()
    p.drawPath(path)
    p.drawPolyline(QPolygonF([QPointF(2, 17), QPointF(2, 5), QPointF(8, 5),
                              QPointF(10, 8)]))
    p.end()
    return pm


def _save():
    pm, p = _canvas()
    p.drawRect(QRectF(3, 3, 16, 16))
    p.drawRect(QRectF(7, 3, 8, 6))
    p.drawRect(QRectF(6, 13, 10, 6))
    p.end()
    return pm


def _export():
    pm, p = _canvas()
    p.drawRect(QRectF(3, 6, 16, 13))
    p.setPen(QPen(HILITE, 1.6))
    p.drawLine(QPointF(11, 15), QPointF(11, 2.5))
    p.setBrush(QBrush(HILITE))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF([QPointF(11, 1.5), QPointF(7.5, 6), QPointF(14.5, 6)]))
    p.end()
    return pm


def _layout_icon(rows: int, cols: int):
    pm, p = _canvas()
    p.setPen(QPen(STROKE, 1.2))
    m, gap = 2.5, 1.4
    w = (SIZE - 2 * m - gap * (cols - 1)) / cols
    h = (SIZE - 2 * m - gap * (rows - 1)) / rows
    for r in range(rows):
        for c in range(cols):
            p.drawRect(QRectF(m + c * (w + gap), m + r * (h + gap), w, h))
    p.end()
    return pm


_BUILDERS = {
    "window": _window_level, "select": _select, "pan": _pan,
    "zoom": _zoom, "scroll": _stack, "crosshair": _crosshair,
    "magnify": _magnify, "probe": _probe, "length": _length,
    "polyline": _polyline, "angle": _angle, "cobb": _cobb,
    "rect": _rect, "ellipse": _ellipse, "polygon": _polygon,
    "freehand": _freehand, "arrow": _arrow,
    "text": lambda: _text_icon("A"),
    "invert": _invert,
    "rotate_cw": lambda: _rotate(True), "rotate_ccw": lambda: _rotate(False),
    "flip_h": lambda: _flip(True), "flip_v": lambda: _flip(False),
    "fit": _fit, "actual": lambda: _text_icon("1:1"), "reset": _reset,
    "reference": _reference, "tags": _tags, "mpr": _mpr, "cine": _cine,
    "open": _open, "save": _save, "export": _export,
}


def icon(name: str) -> QIcon:
    """Return (and cache) a tool icon by name."""
    if name in _CACHE:
        return _CACHE[name]
    builder = _BUILDERS.get(name)
    if builder is None:
        if name.startswith("layout"):
            _, r, c = name.split("_")
            pm = _layout_icon(int(r), int(c))
        else:
            pm = _text_icon("?")
    else:
        pm = builder()
    ic = QIcon(pm)
    _CACHE[name] = ic
    return ic


def layout_icon(rows: int, cols: int) -> QIcon:
    return icon(f"layout_{rows}_{cols}")
