"""Side panels: series browser, annotation list and study information."""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QByteArray, QMimeData, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QFont, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel, QListWidget,
                             QListWidgetItem, QMenu, QStyledItemDelegate,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import windowing as wl
from .measure import Scale

MIME_SERIES = "application/x-dicom-series"
THUMB = 78

ROLE_UID = Qt.ItemDataRole.UserRole
ROLE_TIP = int(Qt.ItemDataRole.UserRole) + 1     # tooltip without the hanging line
ROLE_HUNG = int(Qt.ItemDataRole.UserRole) + 2    # ([viewport numbers], is_active)

HUNG_ACTIVE = QColor(0, 170, 235)                # the active viewport's frame blue
HUNG_OTHER = QColor(78, 138, 176)
HUNG_EDGE = QColor(8, 13, 18)                    # keeps the badge off the row colour


def make_thumbnail(series, size: int = THUMB) -> QPixmap:
    """Render the middle slice of a series as a small pixmap."""
    inst = series[len(series) // 2]
    try:
        data = inst.pixels
    except Exception:
        data = None
    if data is None:                      # undecodable (e.g. missing codec)
        return QPixmap()
    dw = series.default_window()
    if dw:
        c, w = dw
    else:
        c, w = wl.auto_window(data)
    gray = wl.apply_window(data, c, w)
    # cheap decimation before handing the data to Qt
    h, wid = gray.shape
    step = max(1, min(h // size, wid // size))
    small = np.ascontiguousarray(gray[::step, ::step])
    img = QImage(small.data, small.shape[1], small.shape[0], small.shape[1],
                 QImage.Format.Format_Grayscale8).copy()
    return QPixmap.fromImage(img).scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)


class _HangingDelegate(QStyledItemDelegate):
    """Draws the "this series is on screen" marker over a series row.

    A coloured bar down the left edge and a badge on the thumbnail carrying
    the number of the viewport the series is hanging in, counted left to
    right and top to bottom.  The viewport holding focus is drawn in the same
    blue as its own frame so the list and the grid agree on what is active.
    """

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        hung = index.data(ROLE_HUNG)
        if not hung:
            return
        numbers, active = hung
        if not numbers:
            return
        color = HUNG_ACTIVE if active else HUNG_OTHER
        text_color = QColor(8, 15, 20) if active else QColor(240, 247, 253)
        r = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(QRect(r.left(), r.top() + 1, 3, r.height() - 2), color)
        label = ",".join(str(n) for n in numbers)
        font = QFont(option.font)
        font.setBold(True)
        painter.setFont(font)
        width = max(16, painter.fontMetrics().horizontalAdvance(label) + 9)
        badge = QRect(r.left() + 8, r.top() + 8, width, 16)
        painter.setPen(HUNG_EDGE)
        painter.setBrush(color)
        painter.drawRoundedRect(badge, 3, 3)
        painter.setPen(text_color)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()


class SeriesPanel(QListWidget):
    """Thumbnail list of every series in the study; drag onto a viewport."""

    seriesActivated = pyqtSignal(object)
    seriesDragged = pyqtSignal(object)
    mprRequested = pyqtSignal(object)
    tagsRequested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIconSize(QSize(THUMB, THUMB))
        self.setUniformItemSizes(False)
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setWordWrap(True)
        self.setSpacing(1)
        self.setItemDelegate(_HangingDelegate(self))
        self.itemDoubleClicked.connect(self._activated)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self._series: list = []
        self.veterinary = False

    def _menu(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return
        ser = self.series_by_uid(item.data(ROLE_UID))
        if ser is None:
            return
        menu = QMenu(self)
        menu.addAction("Open in the active viewport",
                       lambda: self.seriesActivated.emit(ser))
        menu.addSeparator()
        mpr = menu.addAction("Multiplanar reconstruction…",
                             lambda: self.mprRequested.emit(ser))
        mpr.setEnabled(ser.is_volume)
        if not ser.is_volume:
            mpr.setToolTip("Slices are not a uniformly spaced parallel stack")
        menu.addAction("DICOM tags…", lambda: self.tagsRequested.emit(ser))
        menu.exec(self.viewport().mapToGlobal(pos))

    def set_study(self, study, veterinary: bool = False):
        self.veterinary = veterinary
        self.clear()
        self._series = list(study.series) if study else []
        for ser in self._series:
            plane = ser.plane_label(veterinary)
            text = (f"{ser.number}  {ser.description or '(no description)'}\n"
                    f"{ser.modality} · {plane} · {len(ser)} images")
            item = QListWidgetItem(QIcon(make_thumbnail(ser)), text)
            item.setData(ROLE_UID, ser.uid)
            item.setData(ROLE_TIP, self._tooltip(ser))
            item.setToolTip(item.data(ROLE_TIP))
            item.setSizeHint(QSize(0, THUMB + 12))
            self.addItem(item)

    def _tooltip(self, ser) -> str:
        inst = ser.first
        rows = [
            f"<b>Series {ser.number}</b> &mdash; {ser.description}",
            f"{len(ser)} images &middot; {inst.cols}×{inst.rows}",
            f"Plane: {ser.plane_label(self.veterinary)}",
        ]
        tr = inst.num("RepetitionTime")
        te = inst.num("EchoTime")
        if tr is not None and te is not None:
            rows.append(f"TR {tr:.0f} / TE {te:.0f} ms")
        thk = inst.num("SliceThickness")
        if thk:
            sp = ser.slice_spacing
            rows.append(f"Thickness {thk:.1f} mm"
                        + (f", spacing {sp:.1f} mm" if sp else ""))
        s = Scale.from_instance(inst)
        if s.calibrated:
            rows.append(f"Pixel {s.d_col:.3f} × {s.d_row:.3f} mm")
        if ser.is_volume:
            rows.append("<i>Volume - MPR available</i>")
        return "<br>".join(rows)

    def series_by_uid(self, uid: str):
        for ser in self._series:
            if ser.uid == uid:
                return ser
        return None

    def selected_series(self):
        item = self.currentItem()
        return self.series_by_uid(item.data(ROLE_UID)) if item else None

    def _activated(self, item):
        ser = self.series_by_uid(item.data(ROLE_UID))
        if ser is not None:
            self.seriesActivated.emit(ser)

    def startDrag(self, actions):
        item = self.currentItem()
        if item is None:
            return
        uid = item.data(ROLE_UID)
        mime = QMimeData()
        mime.setData(MIME_SERIES, QByteArray(uid.encode("utf-8")))
        drag = QDrag(self)
        drag.setMimeData(mime)
        icon = item.icon().pixmap(THUMB, THUMB)
        drag.setPixmap(icon)
        drag.exec(Qt.DropAction.CopyAction)

    def mark_displayed(self, panes: dict, active_uid: str | None = None):
        """Mark the series currently hanging in a viewport.

        `panes` maps a series UID to the 1-based numbers of the viewports
        showing it; `active_uid` is the series in the viewport with focus.
        """
        for i in range(self.count()):
            item = self.item(i)
            uid = item.data(ROLE_UID)
            numbers = sorted(panes.get(uid, ()))
            active = bool(numbers) and uid == active_uid
            item.setData(ROLE_HUNG, (numbers, active) if numbers else None)
            item.setToolTip(item.data(ROLE_TIP) + _hanging_note(numbers, active))
        self.viewport().update()

    def mark_annotated(self, counts: dict):
        """Show an annotation count badge in each series entry."""
        for i in range(self.count()):
            item = self.item(i)
            uid = item.data(ROLE_UID)
            n = counts.get(uid, 0)
            base = item.text().split("  ⬤")[0]
            item.setText(base + (f"  ⬤ {n}" if n else ""))
            item.setForeground(QColor("#7fd4ff") if n else QColor("#d7e1eb"))


class AnnotationPanel(QTreeWidget):
    """Flat list of every measurement in the study."""

    annotationActivated = pyqtSignal(object, object, str)   # series, ann, sop
    deleteRequested = pyqtSignal(object)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setColumnCount(4)
        self.setHeaderLabels(["Type", "Measurement", "Se", "Im"])
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.itemDoubleClicked.connect(self._activated)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self._study = None

    def set_study(self, study):
        self._study = study
        self.refresh()

    def refresh(self):
        self.clear()
        if self._study is None:
            return
        by_uid = {s.uid: s for s in self._study.series}
        rows = []
        for ser_uid, sop_uid, ann in self.store.all_items():
            ser = by_uid.get(ser_uid)
            if ser is None:
                continue
            idx, inst = self._locate(ser, sop_uid)
            scale = Scale.from_instance(inst) if inst else Scale(1, 1, False)
            # Reading pixels for every ROI would be slow; only ROIs need them.
            image = inst.pixels if (inst is not None and ann.is_roi) else None
            desc = "; ".join(ann.describe(scale, image)) or ann.text
            rows.append((ser.number, idx, ann.name, desc, ser, ann, sop_uid, idx))
        rows.sort(key=lambda r: (r[0], r[1]))
        for se_no, idx, name, desc, ser, ann, sop_uid, i in rows:
            item = QTreeWidgetItem([name, desc, str(se_no),
                                    str(idx + 1) if idx >= 0 else "?"])
            item.setData(0, Qt.ItemDataRole.UserRole, (ser, ann, sop_uid))
            item.setForeground(0, QColor(ann.color))
            self.addTopLevelItem(item)

    @staticmethod
    def _locate(series, sop_uid):
        for i, inst in enumerate(series.instances):
            if inst.sop_uid == sop_uid:
                return i, inst
        return -1, None

    def _activated(self, item, _col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
            ser, ann, sop = data
            self.annotationActivated.emit(ser, ann, sop)

    def _menu(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction("Go to", lambda: self._activated(item, 0))
        menu.addAction("Delete", lambda: self.deleteRequested.emit(data[1]))
        menu.exec(self.viewport().mapToGlobal(pos))


class StudyInfoPanel(QWidget):
    """Static patient / study summary shown above the series list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.label)

    def set_study(self, study, veterinary: bool = False):
        if study is None:
            self.label.setText("")
            return
        p = study.patient_info()
        s = study.study_info()
        ident = " · ".join(x for x in [p["id"], p["sex"], p["age"]] if x)
        weight = f"{p['weight']:g} kg" if p.get("weight") else ""
        rows = [
            f"<div style='font-size:13px;font-weight:600;color:#e8eef5'>"
            f"{_esc(p['name']) or '(no name)'}</div>",
            f"<div style='color:#8fa3b8'>{_esc(ident)}"
            + (f" · {weight}" if weight else "") + "</div>",
        ]
        if p.get("breed") or p.get("species"):
            rows.append(f"<div style='color:#8fa3b8'>"
                        f"{_esc(p.get('breed') or p.get('species'))}</div>")
        rows.append("<div style='height:6px'></div>")
        rows.append(f"<div style='color:#cbd8e6'>{_esc(s['description'])}</div>")
        rows.append(f"<div style='color:#8fa3b8'>{s['date']} {s['time']}</div>")
        rows.append(f"<div style='color:#8fa3b8'>{_esc(s['modality'])} · "
                    f"{len(study.series)} series · {study.image_count} images</div>")
        if s.get("institution"):
            rows.append(f"<div style='color:#6f8296'>{_esc(s['institution'])}</div>")
        if s.get("model"):
            rows.append(f"<div style='color:#6f8296'>"
                        f"{_esc(s['manufacturer'])} {_esc(s['model'])}</div>")
        if veterinary:
            rows.append("<div style='color:#c8a24a;margin-top:4px'>"
                        "Veterinary orientation labels</div>")
        self.label.setText("".join(rows))


def _hanging_note(numbers, active: bool) -> str:
    if not numbers:
        return ""
    where = ("viewport " + str(numbers[0]) if len(numbers) == 1
             else "viewports " + ", ".join(str(n) for n in numbers))
    return (f"<br><b style='color:#4fc3f7'>Displayed in {where}"
            + (" (active)" if active else "") + "</b>")


def _esc(text) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
