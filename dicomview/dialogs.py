"""Auxiliary windows: DICOM tag browser, MPR, window/level editor, help."""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                             QDoubleSpinBox, QFormLayout, QGridLayout,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QPushButton, QSlider, QTextBrowser, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

from . import windowing as wl
from .dicom_io import fix_text

# --------------------------------------------------------------------------
# DICOM tag browser
# --------------------------------------------------------------------------


class TagBrowser(QDialog):
    """Full DICOM header inspector, equivalent to RadiAnt's tag panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DICOM tags")
        self.resize(880, 720)
        layout = QVBoxLayout(self)

        self.path_label = QLabel()
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by tag, name or value…")
        self.search.textChanged.connect(self._filter)
        row.addWidget(self.search)
        self.hide_empty = QCheckBox("Hide empty")
        self.hide_empty.toggled.connect(self._filter)
        row.addWidget(self.hide_empty)
        layout.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Tag", "VR", "VM", "Description", "Value"])
        self.tree.setAlternatingRowColors(True)
        mono = QFont("Consolas")
        mono.setPixelSize(12)
        self.tree.setFont(mono)
        h = self.tree.header()
        for i in range(4):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tree, 1)

        buttons = QDialogButtonBox()
        copy_btn = buttons.addButton("Copy value",
                                     QDialogButtonBox.ButtonRole.ActionRole)
        copy_btn.clicked.connect(self._copy)
        export_btn = buttons.addButton("Save as text…",
                                       QDialogButtonBox.ButtonRole.ActionRole)
        export_btn.clicked.connect(self._save)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def show_instance(self, instance):
        self.path_label.setText(f"<b>{_esc(instance.path)}</b>")
        ds = instance.full_dataset()
        self.tree.clear()
        self._populate(self.tree.invisibleRootItem(), ds)
        self.tree.expandToDepth(0)
        self._filter()

    def _populate(self, parent, ds):
        for elem in ds:
            if elem.tag.group == 0x7FE0 and elem.tag.element == 0x0010:
                value = f"<pixel data, {len(elem.value or b'')} bytes>"
                item = QTreeWidgetItem(parent, [str(elem.tag), elem.VR or "",
                                                "1", "Pixel Data", value])
                continue
            if elem.VR == "SQ":
                item = QTreeWidgetItem(parent, [
                    str(elem.tag), "SQ", str(len(elem.value or [])),
                    elem.name, f"<sequence, {len(elem.value or [])} item(s)>"])
                for i, sub in enumerate(elem.value or []):
                    node = QTreeWidgetItem(item, ["", "", "", f"Item {i + 1}", ""])
                    self._populate(node, sub)
                continue
            value = _format_value(elem)
            vm = str(elem.VM) if hasattr(elem, "VM") else "1"
            QTreeWidgetItem(parent, [str(elem.tag), elem.VR or "", vm,
                                     elem.name, value])

    def _filter(self):
        text = self.search.text().strip().lower()
        hide_empty = self.hide_empty.isChecked()

        def visit(item) -> bool:
            visible_child = False
            for i in range(item.childCount()):
                visible_child |= visit(item.child(i))
            haystack = " ".join(item.text(c) for c in range(5)).lower()
            # Match "EchoTime" as well as the spaced element name "Echo Time".
            match = (not text) or (text in haystack)
            if not match and " " in haystack:
                match = text.replace(" ", "") in haystack.replace(" ", "")
            if hide_empty and item.childCount() == 0 and not item.text(4).strip():
                match = False
            ok = match or visible_child
            item.setHidden(not ok)
            return ok

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            visit(root.child(i))

    def _copy(self):
        item = self.tree.currentItem()
        if item is not None:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(item.text(4))

    def _save(self):
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getSaveFileName(self, "Save DICOM header",
                                              "dicom_tags.txt",
                                              "Text files (*.txt)")
        if not path:
            return
        lines = []

        def walk(item, depth):
            lines.append("  " * depth + " | ".join(
                item.text(c) for c in (0, 1, 3, 4)))
            for i in range(item.childCount()):
                walk(item.child(i), depth + 1)

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            walk(root.child(i), 0)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", str(exc))


def _format_value(elem) -> str:
    try:
        v = elem.value
    except Exception:
        return "<unreadable>"
    if v is None:
        return ""
    if isinstance(v, bytes):
        return f"<binary, {len(v)} bytes>"
    if elem.VR in ("PN", "LO", "SH", "ST", "LT", "UT", "CS"):
        if isinstance(v, (list, tuple)) or hasattr(v, "__iter__") and not isinstance(v, str):
            try:
                return "\\".join(fix_text(x) for x in v)
            except TypeError:
                pass
        return fix_text(v)
    try:
        if isinstance(v, (list, tuple)) or (hasattr(v, "__iter__")
                                            and not isinstance(v, str)):
            return "\\".join(str(x) for x in v)
    except TypeError:
        pass
    return str(v)


def _esc(t) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------
# window / level editor
# --------------------------------------------------------------------------

class WindowLevelDialog(QDialog):
    def __init__(self, center: float, width: float, data_range, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Window / Level")
        lo, hi = data_range
        form = QFormLayout(self)
        self.f_center = QDoubleSpinBox()
        self.f_center.setRange(lo - abs(lo) - 10000, hi + abs(hi) + 10000)
        self.f_center.setDecimals(1)
        self.f_center.setValue(center)
        self.f_width = QDoubleSpinBox()
        self.f_width.setRange(1, (hi - lo) * 4 + 10000)
        self.f_width.setDecimals(1)
        self.f_width.setValue(width)
        form.addRow("Level (centre)", self.f_center)
        form.addRow("Window (width)", self.f_width)
        form.addRow(QLabel(f"Data range: {lo:.0f} … {hi:.0f}"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return self.f_center.value(), self.f_width.value()


# --------------------------------------------------------------------------
# multiplanar reconstruction
# --------------------------------------------------------------------------

class MprPane(QWidget):
    """One reconstructed plane with a crosshair."""

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        self.setMinimumSize(180, 180)
        self.data = None
        self.aspect = (1.0, 1.0)     # mm per pixel (x, y)
        self.wl_c = 0.0
        self.wl_w = 1.0
        self.cross = (0.0, 0.0)
        self._buf = None
        self.setMouseTracking(True)
        self.clicked = None          # callback(fx, fy) in 0..1 image fractions

    def set_data(self, data, aspect, center, width, cross):
        self.data = data
        self.aspect = aspect
        self.wl_c = center
        self.wl_w = width
        self.cross = cross
        self.update()

    def _transform(self):
        if self.data is None:
            return None
        h, w = self.data.shape
        sx, sy = self.aspect
        base = min(sx, sy) or 1.0
        pw, ph = w * sx / base, h * sy / base
        z = min((self.width_i() - 8) / pw, (self.height_i() - 8) / ph)
        from PyQt6.QtGui import QTransform
        t = QTransform()
        t.translate(self.width_i() / 2, self.height_i() / 2)
        t.scale(z * sx / base, z * sy / base)
        t.translate(-w / 2, -h / 2)
        return t

    def width_i(self) -> int:
        return max(1, self.width())

    def height_i(self) -> int:
        return max(1, self.height())

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        if self.data is None:
            painter.end()
            return
        gray = np.ascontiguousarray(
            wl.apply_window(self.data, self.wl_c, self.wl_w))
        self._buf = gray
        img = QImage(gray.data, gray.shape[1], gray.shape[0], gray.shape[1],
                     QImage.Format.Format_Grayscale8)
        t = self._transform()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.save()
        painter.setTransform(t, True)
        painter.drawImage(QPointF(0, 0), img)
        painter.restore()

        cx, cy = self.cross
        p = t.map(QPointF(cx, cy))
        pen = QPen(QColor(255, 200, 60), 1)
        painter.setPen(pen)
        painter.drawLine(QPointF(0, p.y()), QPointF(self.width_i(), p.y()))
        painter.drawLine(QPointF(p.x(), 0), QPointF(p.x(), self.height_i()))
        painter.setPen(QColor(200, 215, 230))
        painter.drawText(6, 16, self.name)
        painter.end()

    def mousePressEvent(self, event):
        self._pick(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event)

    def _pick(self, event):
        if self.data is None or self.clicked is None:
            return
        t = self._transform()
        inv, ok = t.inverted()
        if not ok:
            return
        q = inv.map(QPointF(event.position()))
        h, w = self.data.shape
        self.clicked(max(0.0, min(1.0, q.x() / w)),
                     max(0.0, min(1.0, q.y() / h)))


class MprWindow(QDialog):
    """Orthogonal multiplanar reconstruction from a parallel-slice series.

    Reconstruction quality is bounded by the slice spacing; with thick slices
    the two reconstructed planes are coarse.  That is stated in the window.
    """

    def __init__(self, series, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"MPR - Series {series.number}: {series.description}")
        self.resize(1000, 720)
        self.series = series

        vol_data = self._build(series)
        layout = QVBoxLayout(self)
        if vol_data is None:
            layout.addWidget(QLabel(
                "This series is not a uniformly spaced parallel stack, "
                "so it cannot be reconstructed."))
            return
        self.volume, self.spacing = vol_data
        ns, nr, nc = self.volume.shape
        sp_s, sp_r, sp_c = self.spacing

        dw = series.default_window()
        self.wl_c, self.wl_w = dw if dw else wl.auto_window(self.volume)

        self.pos = [ns // 2, nr // 2, nc // 2]

        note = QLabel(
            f"Volume {nc} × {nr} × {ns} · voxel "
            f"{sp_c:.2f} × {sp_r:.2f} × {sp_s:.2f} mm — "
            f"reconstructed planes are limited by the {sp_s:.1f} mm slice spacing.")
        note.setStyleSheet("color:#8fa3b8")
        layout.addWidget(note)

        grid = QGridLayout()
        self.pane_native = MprPane("Acquired plane")
        self.pane_a = MprPane("Reconstruction A")
        self.pane_b = MprPane("Reconstruction B")
        grid.addWidget(self.pane_native, 0, 0)
        grid.addWidget(self.pane_a, 0, 1)
        grid.addWidget(self.pane_b, 1, 0)

        side = QWidget()
        form = QFormLayout(side)
        self.s_slice = self._slider(ns - 1, self.pos[0], 0)
        self.s_row = self._slider(nr - 1, self.pos[1], 1)
        self.s_col = self._slider(nc - 1, self.pos[2], 2)
        form.addRow("Slice", self.s_slice)
        form.addRow("Row", self.s_row)
        form.addRow("Column", self.s_col)
        self.sp_center = QDoubleSpinBox()
        self.sp_center.setRange(-1e6, 1e6)
        self.sp_center.setValue(self.wl_c)
        self.sp_center.valueChanged.connect(self._window_changed)
        self.sp_width = QDoubleSpinBox()
        self.sp_width.setRange(1, 1e6)
        self.sp_width.setValue(self.wl_w)
        self.sp_width.valueChanged.connect(self._window_changed)
        form.addRow("Level", self.sp_center)
        form.addRow("Window", self.sp_width)
        reset = QPushButton("Auto window")
        reset.clicked.connect(self._auto)
        form.addRow(reset)
        grid.addWidget(side, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        layout.addLayout(grid, 1)

        self.pane_native.clicked = lambda fx, fy: self._pick(0, fx, fy)
        self.pane_a.clicked = lambda fx, fy: self._pick(1, fx, fy)
        self.pane_b.clicked = lambda fx, fy: self._pick(2, fx, fy)
        self._refresh()

    def _slider(self, maximum, value, axis):
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(0, max(0, maximum))
        s.setValue(value)
        s.valueChanged.connect(lambda v, a=axis: self._set_axis(a, v))
        return s

    @staticmethod
    def _build(series):
        from .geometry import build_volume
        built = build_volume(series)
        if built is None:
            return None
        vol, spacing, _geo = built
        return vol, spacing

    def _set_axis(self, axis, value):
        self.pos[axis] = int(value)
        self._refresh()

    def _pick(self, pane, fx, fy):
        ns, nr, nc = self.volume.shape
        if pane == 0:            # native: x=col, y=row
            self.pos[2] = int(fx * nc)
            self.pos[1] = int(fy * nr)
        elif pane == 1:          # A: x=col, y=slice
            self.pos[2] = int(fx * nc)
            self.pos[0] = int(fy * ns)
        else:                    # B: x=row, y=slice
            self.pos[1] = int(fx * nr)
            self.pos[0] = int(fy * ns)
        self.pos = [max(0, min(self.pos[0], ns - 1)),
                    max(0, min(self.pos[1], nr - 1)),
                    max(0, min(self.pos[2], nc - 1))]
        for slider, v in ((self.s_slice, self.pos[0]), (self.s_row, self.pos[1]),
                          (self.s_col, self.pos[2])):
            slider.blockSignals(True)
            slider.setValue(v)
            slider.blockSignals(False)
        self._refresh()

    def _window_changed(self):
        self.wl_c = self.sp_center.value()
        self.wl_w = max(1.0, self.sp_width.value())
        self._refresh()

    def _auto(self):
        self.wl_c, self.wl_w = wl.auto_window(self.volume)
        self.sp_center.setValue(self.wl_c)
        self.sp_width.setValue(self.wl_w)

    def _refresh(self):
        s, r, c = self.pos
        sp_s, sp_r, sp_c = self.spacing
        self.pane_native.set_data(self.volume[s], (sp_c, sp_r),
                                  self.wl_c, self.wl_w, (c, r))
        self.pane_a.set_data(self.volume[:, r, :], (sp_c, sp_s),
                             self.wl_c, self.wl_w, (c, s))
        self.pane_b.set_data(self.volume[:, :, c], (sp_r, sp_s),
                             self.wl_c, self.wl_w, (r, s))


# --------------------------------------------------------------------------
# help
# --------------------------------------------------------------------------

SHORTCUT_HTML = """
<style>
 body{font-family:Segoe UI,sans-serif;font-size:13px}
 h3{color:#4bb6e8;margin:14px 0 4px 0}
 td{padding:2px 14px 2px 0;vertical-align:top}
 .k{color:#e2c069;font-family:Consolas,monospace;white-space:nowrap}
</style>
<h3>Mouse</h3>
<table>
<tr><td class=k>Left drag</td><td>Active tool (window/level by default)</td></tr>
<tr><td class=k>Middle drag</td><td>Pan</td></tr>
<tr><td class=k>Right drag</td><td>Zoom</td></tr>
<tr><td class=k>Right click</td><td>Context menu / finish multi-point measurement</td></tr>
<tr><td class=k>Wheel</td><td>Scroll through slices</td></tr>
<tr><td class=k>Shift + wheel</td><td>Scroll 10 slices at a time</td></tr>
<tr><td class=k>Ctrl + wheel</td><td>Zoom about the cursor</td></tr>
<tr><td class=k>Double click</td><td>Maximise / restore the viewport</td></tr>
</table>

<h3>Tools</h3>
<table>
<tr><td class=k>W</td><td>Window / level</td></tr>
<tr><td class=k>S</td><td>Select &amp; edit annotations</td></tr>
<tr><td class=k>P</td><td>Pan</td></tr>
<tr><td class=k>Z</td><td>Zoom</td></tr>
<tr><td class=k>B</td><td>Stack scroll (browse)</td></tr>
<tr><td class=k>X</td><td>Cross-reference cursor</td></tr>
<tr><td class=k>G</td><td>Magnifying glass</td></tr>
<tr><td class=k>D</td><td>Probe (pixel value)</td></tr>
<tr><td class=k>L</td><td>Length</td></tr>
<tr><td class=k>Shift+L</td><td>Polyline length</td></tr>
<tr><td class=k>A</td><td>Angle</td></tr>
<tr><td class=k>C</td><td>Cobb angle</td></tr>
<tr><td class=k>R</td><td>Rectangle ROI</td></tr>
<tr><td class=k>E</td><td>Ellipse ROI</td></tr>
<tr><td class=k>Y</td><td>Polygon ROI</td></tr>
<tr><td class=k>F</td><td>Freehand ROI</td></tr>
<tr><td class=k>K</td><td>Arrow</td></tr>
<tr><td class=k>T</td><td>Text note</td></tr>
<tr><td class=k>Delete</td><td>Delete the selected annotation</td></tr>
<tr><td class=k>Esc</td><td>Cancel the measurement in progress</td></tr>
</table>

<h3>Display</h3>
<table>
<tr><td class=k>&larr; &rarr; &uarr; &darr;</td><td>Previous / next image</td></tr>
<tr><td class=k>Page Up / Down</td><td>Jump 10 images</td></tr>
<tr><td class=k>Home / End</td><td>First / last image</td></tr>
<tr><td class=k>Ctrl+0</td><td>Fit to window</td></tr>
<tr><td class=k>Ctrl+1</td><td>Actual size (100%)</td></tr>
<tr><td class=k>I</td><td>Invert greyscale</td></tr>
<tr><td class=k>Ctrl+L / Ctrl+Shift+L</td><td>Rotate left / right</td></tr>
<tr><td class=k>H / V</td><td>Flip horizontal / vertical</td></tr>
<tr><td class=k>O</td><td>Show or hide the text overlay</td></tr>
<tr><td class=k>M</td><td>Show or hide annotations</td></tr>
<tr><td class=k>N</td><td>Show or hide cross-reference lines</td></tr>
<tr><td class=k>Space</td><td>Play / pause cine</td></tr>
<tr><td class=k>F11</td><td>Full screen</td></tr>
<tr><td class=k>Ctrl+R</td><td>Reset the viewport</td></tr>
</table>

<h3>Layout &amp; study</h3>
<table>
<tr><td class=k>Alt+1 … Alt+6</td><td>1×1, 1×2, 2×1, 2×2, 2×3, 3×3 layout</td></tr>
<tr><td class=k>1×3</td><td>Orthogonal hang: coronal, sagittal and axial panes, each showing the first series of that plane</td></tr>
<tr><td class=k>Ctrl+O</td><td>Open a DICOM folder</td></tr>
<tr><td class=k>Ctrl+S</td><td>Save annotations</td></tr>
<tr><td class=k>Ctrl+E</td><td>Export the active viewport as an image</td></tr>
<tr><td class=k>Ctrl+T</td><td>DICOM tag browser</td></tr>
<tr><td class=k>Ctrl+M</td><td>MPR of the active series</td></tr>
<tr><td class=k>F1</td><td>This help</td></tr>
</table>
"""


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard and mouse reference")
        self.resize(620, 760)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setHtml(SHORTCUT_HTML)
        layout.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
