"""Main application window: layout, toolbars, synchronisation and export."""
from __future__ import annotations

import csv
import os

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence
from PyQt6.QtWidgets import (QApplication, QComboBox, QDockWidget, QFileDialog,
                             QGridLayout, QHBoxLayout, QLabel, QMainWindow,
                             QMenu, QMessageBox, QProgressDialog, QSlider,
                             QSpinBox, QToolBar, QToolButton, QVBoxLayout,
                             QWidget)

from . import dicom_io, geometry as geo, icons, viewport as vp, windowing as wl
from .dialogs import HelpDialog, MprWindow, TagBrowser, WindowLevelDialog
from .panels import AnnotationPanel, SeriesPanel, StudyInfoPanel
from .session import AnnotationStore, Settings
from .theme import STYLESHEET

APP_NAME = "DicomView"

LAYOUTS = [
    ("1 × 1", 1, 1, "Alt+1"), ("1 × 2", 1, 2, "Alt+2"), ("2 × 1", 2, 1, "Alt+3"),
    ("2 × 2", 2, 2, "Alt+4"), ("2 × 3", 2, 3, "Alt+5"), ("3 × 3", 3, 3, "Alt+6"),
    ("1 × 3", 1, 3, ""), ("3 × 2", 3, 2, ""), ("4 × 4", 4, 4, ""),
]

# 1 x 3 hangs one pane per orthogonal plane, in this order.
ORTHO_PLANES = (dicom_io.PLANE_CORONAL, dicom_io.PLANE_SAGITTAL,
                dicom_io.PLANE_AXIAL)

TOOLS = [
    ("Window / Level", vp.T_WINDOW, "W", "window"),
    ("Select & edit", vp.T_SELECT, "S", "select"),
    ("Pan", vp.T_PAN, "P", "pan"),
    ("Zoom", vp.T_ZOOM, "Z", "zoom"),
    ("Browse stack", vp.T_SCROLL, "B", "scroll"),
    ("Cross-reference", vp.T_CROSSHAIR, "X", "crosshair"),
    ("Magnifier", vp.T_MAGNIFY, "G", "magnify"),
    None,
    ("Probe", vp.T_PROBE, "D", "probe"),
    ("Length", vp.T_LENGTH, "L", "length"),
    ("Polyline", vp.T_POLYLINE, "Shift+L", "polyline"),
    ("Angle", vp.T_ANGLE, "A", "angle"),
    ("Cobb angle", vp.T_COBB, "C", "cobb"),
    ("Rectangle ROI", vp.T_RECT, "R", "rect"),
    ("Ellipse ROI", vp.T_ELLIPSE, "E", "ellipse"),
    ("Polygon ROI", vp.T_POLYGON, "Y", "polygon"),
    ("Freehand ROI", vp.T_FREEHAND, "F", "freehand"),
    ("Arrow", vp.T_ARROW, "K", "arrow"),
    ("Text", vp.T_TEXT, "T", "text"),
]


class MainWindow(QMainWindow):
    def __init__(self, folder: str | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1600, 980)

        self.settings = Settings()
        self.store = AnnotationStore()
        self.studies: list = []
        self.study = None
        self.folder = None
        self.veterinary = False

        self._pool: list[vp.Viewport] = []
        self.viewports: list[vp.Viewport] = []
        self.active: vp.Viewport | None = None
        self._maximized_state = None
        self._grid_shape = (1, 1)
        self._syncing = False

        self.link_scroll = False
        self.link_window = False
        self.link_zoom = False

        self._tag_browser = None
        self._help = None

        self._build_ui()
        self._build_actions()
        self._set_layout(1, 1)

        self.cine_timer = QTimer(self)
        self.cine_timer.timeout.connect(self._cine_tick)

        self._autosave = QTimer(self)
        self._autosave.setInterval(4000)
        self._autosave.timeout.connect(self._autosave_tick)
        self._autosave.start()

        if folder:
            self.open_folder(folder)

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(2)
        outer.addWidget(self.grid_host, 1)

        outer.addWidget(self._build_cine_bar())
        self.setCentralWidget(central)

        # left dock -----------------------------------------------------
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        self.info_panel = StudyInfoPanel()
        self.series_panel = SeriesPanel()
        self.series_panel.seriesActivated.connect(self._series_activated)
        self.series_panel.mprRequested.connect(self._mpr_for_series)
        self.series_panel.tagsRequested.connect(self._tags_for_series)
        lv.addWidget(self.info_panel)
        lv.addWidget(self.series_panel, 1)

        dock = QDockWidget("Study", self)
        dock.setObjectName("studyDock")
        dock.setWidget(left)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        dock.setMinimumWidth(230)
        self.study_dock = dock

        # right dock ----------------------------------------------------
        self.annotation_panel = AnnotationPanel(self.store)
        self.annotation_panel.annotationActivated.connect(self._goto_annotation)
        self.annotation_panel.deleteRequested.connect(self._delete_annotation)
        adock = QDockWidget("Measurements", self)
        adock.setObjectName("measurementDock")
        adock.setWidget(self.annotation_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, adock)
        adock.setMinimumWidth(260)
        self.annotation_dock = adock

        # status bar ----------------------------------------------------
        self.status_pixel = QLabel("")
        self.status_pixel.setMinimumWidth(420)
        self.statusBar().addWidget(self.status_pixel, 1)
        self.status_series = QLabel("")
        self.statusBar().addPermanentWidget(self.status_series)

    def _build_cine_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(30)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(8)

        self.btn_play = QToolButton()
        self.btn_play.setText("▶")
        self.btn_play.setCheckable(True)
        self.btn_play.setToolTip("Play / pause cine (Space)")
        self.btn_play.toggled.connect(self.toggle_cine)
        layout.addWidget(self.btn_play)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(12)
        self.fps_spin.setSuffix(" fps")
        self.fps_spin.setFixedWidth(74)
        self.fps_spin.valueChanged.connect(self._fps_changed)
        layout.addWidget(self.fps_spin)

        self.slice_slider = QSlider(Qt.Orientation.Horizontal)
        self.slice_slider.setRange(0, 0)
        self.slice_slider.valueChanged.connect(self._slider_changed)
        layout.addWidget(self.slice_slider, 1)

        self.slice_label = QLabel("—")
        self.slice_label.setFixedWidth(96)
        self.slice_label.setAlignment(Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.slice_label)
        return bar

    # ------------------------------------------------------------------
    def _build_actions(self):
        mb = self.menuBar()

        # ---- File -----------------------------------------------------
        m_file = mb.addMenu("&File")
        self._act(m_file, "Open DICOM folder…", self.action_open, "Ctrl+O")
        self._act(m_file, "Open DICOM file(s)…", self.action_open_files, "Ctrl+Shift+O")
        self.recent_menu = m_file.addMenu("Open recent")
        self._refresh_recent()
        m_file.addSeparator()
        self._act(m_file, "Save annotations", self.action_save, "Ctrl+S")
        self._act(m_file, "Save annotations as…", self.action_save_as)
        self._act(m_file, "Load annotations…", self.action_load_annotations)
        m_file.addSeparator()
        self._act(m_file, "Export image…", self.action_export_image, "Ctrl+E")
        self._act(m_file, "Export series as images…", self.action_export_series)
        self._act(m_file, "Copy image to clipboard", self.action_copy_clipboard,
                  "Ctrl+C")
        self._act(m_file, "Export measurement report…", self.action_export_report)
        m_file.addSeparator()
        self._act(m_file, "Exit", self.close, "Ctrl+Q")

        # ---- Edit -----------------------------------------------------
        m_edit = mb.addMenu("&Edit")
        self._act(m_edit, "Delete selected annotation", self.action_delete,
                  "Delete")
        self._act(m_edit, "Cancel measurement in progress", self.action_escape,
                  "Esc")
        m_edit.addSeparator()
        self._act(m_edit, "Clear annotations on this image",
                  lambda: self.active and self.active.clear_image_annotations())
        self._act(m_edit, "Clear annotations in this series",
                  self.action_clear_series)
        self._act(m_edit, "Clear all annotations", self.action_clear_all)
        m_edit.addSeparator()
        self._act(m_edit, "Annotation colour…", self.action_annotation_color)

        # ---- View -----------------------------------------------------
        m_view = mb.addMenu("&View")
        self._act(m_view, "Fit to window", lambda: self._apply(lambda v: v.fit_to_window()),
                  "Ctrl+0")
        self._act(m_view, "Actual size (100%)",
                  lambda: self._apply(lambda v: v.zoom_actual()), "Ctrl+1")
        self._act(m_view, "Zoom in", lambda: self._apply(lambda v: v.zoom_by(1.25)),
                  "Ctrl++")
        self._act(m_view, "Zoom out", lambda: self._apply(lambda v: v.zoom_by(1 / 1.25)),
                  "Ctrl+-")
        m_view.addSeparator()
        self._act(m_view, "Rotate left", lambda: self._apply(lambda v: v.rotate(-90)),
                  "Ctrl+L")
        self._act(m_view, "Rotate right", lambda: self._apply(lambda v: v.rotate(90)),
                  "Ctrl+Shift+L")
        self._act(m_view, "Flip horizontal", lambda: self._apply(lambda v: v.flip(True)),
                  "H")
        self._act(m_view, "Flip vertical", lambda: self._apply(lambda v: v.flip(False)),
                  "V")
        self._act(m_view, "Invert greyscale",
                  lambda: self._apply(lambda v: v.toggle_invert()), "I")
        self._act(m_view, "Reset viewport", self.action_reset, "Ctrl+R")
        m_view.addSeparator()

        self.act_overlay = self._toggle(m_view, "Text overlay", True,
                                        self._update_overlay_flags, "O")
        self.act_annotations = self._toggle(m_view, "Annotations", True,
                                            self._update_overlay_flags, "M")
        self.act_reflines = self._toggle(m_view, "Cross-reference lines", True,
                                         self._update_overlay_flags, "N")
        self.act_orientation = self._toggle(m_view, "Orientation markers", True,
                                            self._update_overlay_flags)
        self.act_scalebar = self._toggle(m_view, "Scale bar", True,
                                         self._update_overlay_flags)
        self.act_smooth = self._toggle(m_view, "Smooth interpolation", True,
                                       self._update_overlay_flags)
        self.act_vet = self._toggle(m_view, "Veterinary orientation labels", False,
                                    self._vet_changed)
        self.act_vet.setToolTip(
            "Label edges Cr/Cd and D/V instead of H/F and P/A.\n"
            "Assumes sternal (prone) recumbency.")
        m_view.addSeparator()
        self._act(m_view, "Full screen", self.action_fullscreen, "F11")
        m_view.addAction(self.study_dock.toggleViewAction())
        m_view.addAction(self.annotation_dock.toggleViewAction())

        # ---- Layout ---------------------------------------------------
        m_layout = mb.addMenu("&Layout")
        group = QActionGroup(self)
        group.setExclusive(True)
        for name, r, c, key in LAYOUTS:
            act = QAction(icons.layout_icon(r, c), name, self, checkable=True)
            if key:
                act.setShortcut(QKeySequence(key))
            act.triggered.connect(lambda _=False, rr=r, cc=c: self._set_layout(rr, cc))
            group.addAction(act)
            m_layout.addAction(act)
            if (r, c) == (1, 1):
                act.setChecked(True)
        self.layout_group = group
        m_layout.addSeparator()
        self._act(m_layout, "Maximise / restore viewport",
                  lambda: self.active and self.toggle_maximize(self.active))
        self._act(m_layout, "Fill layout with series", self.action_autohang)

        # ---- Tools ----------------------------------------------------
        m_tools = mb.addMenu("&Tools")
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_actions = {}
        for entry in TOOLS:
            if entry is None:
                m_tools.addSeparator()
                continue
            name, tool, key, icon_name = entry
            act = QAction(icons.icon(icon_name), name, self, checkable=True)
            if key:
                act.setShortcut(QKeySequence(key))
                act.setToolTip(f"{name}  ({key})")
            else:
                act.setToolTip(name)
            act.triggered.connect(lambda _=False, t=tool: self.set_tool(t))
            self.tool_group.addAction(act)
            m_tools.addAction(act)
            self.tool_actions[tool] = act
        self.tool_actions[vp.T_WINDOW].setChecked(True)

        m_tools.addSeparator()
        m_sync = m_tools.addMenu("Synchronise")
        self.act_link_scroll = self._toggle(m_sync, "Linked scrolling", False,
                                            self._sync_changed)
        self.act_link_window = self._toggle(m_sync, "Linked window / level", False,
                                            self._sync_changed)
        self.act_link_zoom = self._toggle(m_sync, "Linked zoom and pan", False,
                                          self._sync_changed)
        m_tools.addSeparator()
        self._act(m_tools, "Window / level values…", self.action_window_dialog)
        self._act(m_tools, "DICOM tags…", self.action_tags, "Ctrl+T")
        self._act(m_tools, "Multiplanar reconstruction…", self.action_mpr, "Ctrl+M")

        # ---- Help -----------------------------------------------------
        m_help = mb.addMenu("&Help")
        self._act(m_help, "Keyboard and mouse reference", self.action_help, "F1")
        self._act(m_help, f"About {APP_NAME}", self.action_about)

        self._build_toolbar()

        # global shortcuts not tied to a menu
        for key, fn in (("Space", self.action_toggle_cine),
                        ("Left", lambda: self._step(-1)),
                        ("Right", lambda: self._step(1)),
                        ("Up", lambda: self._step(-1)),
                        ("Down", lambda: self._step(1)),
                        ("PgUp", lambda: self._step(-10)),
                        ("PgDown", lambda: self._step(10)),
                        ("Home", lambda: self._goto(0)),
                        ("End", lambda: self._goto(10 ** 9))):
            act = QAction(self)
            act.setShortcut(QKeySequence(key))
            act.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            act.triggered.connect(fn)
            self.addAction(act)

    def _build_toolbar(self):
        """Compact icon toolbar; every button also lives in a menu with text."""
        tb = QToolBar("Main")
        tb.setObjectName("mainToolbar")
        tb.setIconSize(QSize(22, 22))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        tb.setMovable(False)
        self.addToolBar(tb)
        self.toolbar = tb

        tb.addAction(icons.icon("open"), "Open DICOM folder  (Ctrl+O)",
                     self.action_open)
        tb.addAction(icons.icon("save"), "Save annotations  (Ctrl+S)",
                     self.action_save)
        tb.addAction(icons.icon("export"), "Export image  (Ctrl+E)",
                     self.action_export_image)
        tb.addSeparator()

        for tool in (vp.T_WINDOW, vp.T_SELECT, vp.T_PAN, vp.T_ZOOM,
                     vp.T_SCROLL, vp.T_CROSSHAIR, vp.T_MAGNIFY):
            tb.addAction(self.tool_actions[tool])
        tb.addSeparator()
        for tool in (vp.T_PROBE, vp.T_LENGTH, vp.T_POLYLINE, vp.T_ANGLE,
                     vp.T_COBB, vp.T_RECT, vp.T_ELLIPSE, vp.T_POLYGON,
                     vp.T_FREEHAND, vp.T_ARROW, vp.T_TEXT):
            tb.addAction(self.tool_actions[tool])
        tb.addSeparator()

        tb.addAction(icons.icon("fit"), "Fit to window  (Ctrl+0)",
                     lambda: self._apply(lambda v: v.fit_to_window()))
        tb.addAction(icons.icon("invert"), "Invert greyscale  (I)",
                     lambda: self._apply(lambda v: v.toggle_invert()))

        # rotate / flip / reset live under one button to keep the bar short
        self.adjust_button = QToolButton()
        self.adjust_button.setIcon(icons.icon("rotate_cw"))
        self.adjust_button.setToolTip("Rotate, flip and reset")
        self.adjust_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        adjust = QMenu(self.adjust_button)
        for icon_name, label, shortcut, slot in (
                ("rotate_ccw", "Rotate left", "Ctrl+L",
                 lambda: self._apply(lambda v: v.rotate(-90))),
                ("rotate_cw", "Rotate right", "Ctrl+Shift+L",
                 lambda: self._apply(lambda v: v.rotate(90))),
                ("flip_h", "Flip horizontal", "H",
                 lambda: self._apply(lambda v: v.flip(True))),
                ("flip_v", "Flip vertical", "V",
                 lambda: self._apply(lambda v: v.flip(False))),
                ("actual", "Actual size (100%)", "Ctrl+1",
                 lambda: self._apply(lambda v: v.zoom_actual())),
                ("reset", "Reset viewport", "Ctrl+R", self.action_reset)):
            act = adjust.addAction(icons.icon(icon_name), label)
            act.setShortcut(QKeySequence(shortcut))
            act.triggered.connect(lambda _=False, fn=slot: fn())
        self.adjust_button.setMenu(adjust)
        tb.addWidget(self.adjust_button)
        tb.addSeparator()

        # layout chooser as a single drop-down button
        self.layout_button = QToolButton()
        self.layout_button.setIcon(icons.layout_icon(1, 1))
        self.layout_button.setToolTip("Viewport layout")
        self.layout_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.layout_button)
        for name, r, c, key in LAYOUTS:
            act = menu.addAction(icons.layout_icon(r, c), name)
            if key:
                act.setShortcut(QKeySequence(key))
            act.triggered.connect(
                lambda _=False, rr=r, cc=c: self._set_layout(rr, cc))
        self.layout_button.setMenu(menu)
        tb.addWidget(self.layout_button)

        tb.addAction(icons.icon("reference"), "Cross-reference lines  (N)",
                     lambda: (self.act_reflines.toggle(),
                              self._update_overlay_flags()))
        tb.addAction(icons.icon("tags"), "DICOM tags  (Ctrl+T)", self.action_tags)
        tb.addAction(icons.icon("mpr"), "Multiplanar reconstruction  (Ctrl+M)",
                     self.action_mpr)
        tb.addSeparator()

        tb.addWidget(QLabel(" W/L "))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(130)
        self.preset_combo.setToolTip("Window / level preset")
        self.preset_combo.activated.connect(self._preset_chosen)
        tb.addWidget(self.preset_combo)
        self._refresh_presets()

        self.cmap_combo = QComboBox()
        self.cmap_combo.addItems(wl.COLORMAP_NAMES)
        self.cmap_combo.setToolTip("Colour map")
        self.cmap_combo.setMinimumWidth(105)
        self.cmap_combo.activated.connect(
            lambda i: self._apply(lambda v: v.set_colormap(
                self.cmap_combo.itemText(i))))
        tb.addWidget(self.cmap_combo)

    def _act(self, menu, text, slot, shortcut=None):
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
            act.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        act.triggered.connect(lambda _=False: slot())
        menu.addAction(act)
        return act

    def _toggle(self, menu, text, checked, slot, shortcut=None):
        act = QAction(text, self, checkable=True)
        act.setChecked(checked)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
            act.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        act.triggered.connect(lambda _=False: slot())
        menu.addAction(act)
        return act

    # ------------------------------------------------------------------
    # viewport grid
    # ------------------------------------------------------------------
    def _make_viewport(self) -> vp.Viewport:
        v = vp.Viewport(self.store, self.settings)
        v.activated.connect(self.set_active)
        v.sliceChanged.connect(self._slice_changed)
        v.windowChanged.connect(self._window_changed)
        v.annotationsChanged.connect(self._annotations_changed)
        v.crosshairMoved.connect(self._crosshair_moved)
        v.seriesDropped.connect(self._series_dropped)
        v.statusMessage.connect(self.status_pixel.setText)
        v.maximizeRequested.connect(self.toggle_maximize)
        v.seriesChanged.connect(self._viewport_series_changed)
        v.transformChanged.connect(self._transform_changed)
        v.reference_provider = lambda: list(self.viewports)
        return v

    def _set_layout(self, rows: int, cols: int, from_maximize: bool = False):
        if not from_maximize:
            self._maximized_state = None
        n = rows * cols
        while len(self._pool) < n:
            self._pool.append(self._make_viewport())
        for v in self._pool:
            v.setParent(None)
        for i in range(n):
            self.grid.addWidget(self._pool[i], i // cols, i % cols)
            self._pool[i].show()
        self.viewports = self._pool[:n]
        was = self._grid_shape
        self._grid_shape = (rows, cols)
        self._sync_layout_widgets(rows, cols)
        if self.active not in self.viewports:
            self.set_active(self.viewports[0] if self.viewports else None)
        self._refresh_series_marks()
        # 1 x 3 is the orthogonal hanging protocol - rehang on entering it.
        if (rows, cols) == (1, 3) and was != (1, 3) and self.study:
            self.action_autohang()
        self._update_overlay_flags()
        self._update_slider()

    def _sync_layout_widgets(self, rows, cols):
        for i, (_name, r, c, _key) in enumerate(LAYOUTS):
            if (r, c) == (rows, cols):
                if hasattr(self, "layout_button"):
                    self.layout_button.setIcon(icons.layout_icon(r, c))
                acts = self.layout_group.actions()
                if i < len(acts):
                    acts[i].setChecked(True)
                break

    def toggle_maximize(self, view: vp.Viewport):
        if self._maximized_state is not None:
            rows, cols = self._maximized_state
            self._maximized_state = None
            self._set_layout(rows, cols)
            return
        if view is None:
            return
        prev = self._grid_shape
        for v in self._pool:
            v.setParent(None)
        self.grid.addWidget(view, 0, 0)
        view.show()
        self.viewports = [view]
        self._maximized_state = prev
        self.set_active(view)
        self._refresh_series_marks()

    def set_active(self, view):
        if view is self.active:
            return
        for v in self._pool:
            v.active = (v is view)
            v.update()
        self.active = view
        self._update_slider()
        self._refresh_presets()
        self._refresh_series_marks()
        if view is not None and view.series is not None:
            self.status_series.setText(
                f"Series {view.series.number} · {view.series.description} · "
                f"{len(view.series)} images")
            self.cmap_combo.blockSignals(True)
            self.cmap_combo.setCurrentText(view.colormap)
            self.cmap_combo.blockSignals(False)

    def _apply(self, fn, all_viewports: bool = False):
        targets = self.viewports if all_viewports else (
            [self.active] if self.active else [])
        for v in targets:
            if v is not None:
                fn(v)

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------
    def action_open(self):
        start = self.folder or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Open DICOM folder", start)
        if folder:
            self.open_folder(folder)

    def action_open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open DICOM files", self.folder or os.path.expanduser("~"),
            "DICOM files (*.dcm *.dic *.ima *.img);;All files (*)")
        if paths:
            self.open_folder(os.path.dirname(paths[0]))

    def open_folder(self, folder: str):
        folder = os.path.abspath(folder)
        if not os.path.isdir(folder):
            QMessageBox.warning(self, APP_NAME, f"Not a folder:\n{folder}")
            return
        progress = QProgressDialog("Scanning DICOM files…", "Cancel", 0, 100, self)
        progress.setWindowTitle(APP_NAME)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(200)

        def report(done, total, _path):
            if total:
                progress.setMaximum(total)
                progress.setValue(done)
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            studies = dicom_io.scan_folder(folder, report)
        except Exception as exc:                       # pragma: no cover
            progress.close()
            QMessageBox.critical(self, APP_NAME, f"Could not read the folder:\n{exc}")
            return
        progress.close()

        if not studies:
            QMessageBox.information(self, APP_NAME,
                                    "No readable DICOM images were found here.")
            return

        self.folder = folder
        self.studies = studies
        self.settings.add_recent(folder)
        self._refresh_recent()
        self.store = AnnotationStore()
        self.annotation_panel.store = self.store
        for v in self._pool:
            v.store = self.store
            v.clear()
        self.load_study(studies[0])

        path = AnnotationStore.default_path(folder)
        self.store.path = path
        if os.path.exists(path):
            try:
                n = self.store.load(path)
                self.statusBar().showMessage(
                    f"Loaded {n} saved annotation(s)", 4000)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, APP_NAME,
                                    f"Annotations could not be loaded:\n{exc}")
        self._annotations_changed(None)

    def load_study(self, study):
        self.study = study
        for ser in study.series:
            ser.study = study                      # backlink used by the overlay
        auto_vet = study.looks_veterinary()
        pref = self.settings["veterinary_labels"]
        self.veterinary = auto_vet if pref is None else bool(pref)
        self.act_vet.setChecked(self.veterinary)

        self.series_panel.set_study(study, self.veterinary)
        self.info_panel.set_study(study, self.veterinary)
        self.annotation_panel.set_study(study)

        p = study.patient_info()
        s = study.study_info()
        self.setWindowTitle(
            f"{p['name'] or 'Unknown'} — {s['description'] or s['modality']} "
            f"— {s['date']} — {APP_NAME}")

        self.action_autohang()
        if self.viewports:
            self.set_active(self.viewports[0])
        self._update_overlay_flags()

    def action_autohang(self):
        """Fill the current layout with the series of the study.

        A 1 x 3 layout is treated as the orthogonal protocol: one pane per
        plane in coronal / sagittal / axial order, each showing the first
        series acquired in that plane.  Every other layout is filled with the
        series in list order.
        """
        if not self.study:
            return
        if self._grid_shape == (1, 3) and self._autohang_ortho():
            return
        for i, view in enumerate(self.viewports):
            if i < len(self.study.series):
                view.set_series(self.study.series[i])
                view.veterinary = self.veterinary
            else:
                view.clear()
        self._update_slider()

    def _autohang_ortho(self) -> bool:
        """Hang one plane per pane.  False when the study has no such series."""
        picks = [self._first_series_in_plane(p) for p in ORTHO_PLANES]
        if not any(picks):
            return False
        for view, plane, series in zip(self.viewports, ORTHO_PLANES, picks):
            if series is not None:
                view.set_series(series)
                view.veterinary = self.veterinary
            else:
                label = dicom_io.PLANE_LABELS[plane][1 if self.veterinary else 0]
                view.clear(f"No {label} series in this study")
        self._update_slider()
        return True

    def _first_series_in_plane(self, plane):
        for ser in self.study.series:
            if ser.plane == plane:
                return ser
        return None

    def _refresh_recent(self):
        self.recent_menu.clear()
        for folder in self.settings["recent_folders"] or []:
            act = QAction(folder, self)
            act.triggered.connect(lambda _=False, f=folder: self.open_folder(f))
            self.recent_menu.addAction(act)

    # ------------------------------------------------------------------
    # series assignment
    # ------------------------------------------------------------------
    def _series_activated(self, series):
        target = self.active or (self.viewports[0] if self.viewports else None)
        if target is None:
            return
        target.set_series(series)
        target.veterinary = self.veterinary
        self._update_slider()
        self.set_active(target)
        self._refresh_presets()

    def _refresh_series_marks(self):
        """Tell the series list which of its entries are on screen, and where.

        Viewports are numbered in reading order; a maximised viewport is on
        its own and so is always number 1.
        """
        panes: dict[str, list[int]] = {}
        for number, view in enumerate(self.viewports, 1):
            if view.series is not None:
                panes.setdefault(view.series.uid, []).append(number)
        active = (self.active.series.uid
                  if self.active is not None and self.active.series is not None
                  else None)
        self.series_panel.mark_displayed(panes, active)

    def _viewport_series_changed(self, view):
        self._refresh_series_marks()
        self._refresh_reference_lines()
        if view is self.active:
            self._update_slider()
            self._refresh_presets()
            if view.series is not None:
                self.status_series.setText(
                    f"Series {view.series.number} · {view.series.description} "
                    f"· {len(view.series)} images")

    def _series_dropped(self, view, uid):
        series = self.series_panel.series_by_uid(uid)
        if series is not None:
            view.set_series(series)
            view.veterinary = self.veterinary
            self.set_active(view)
            self._update_slider()

    # ------------------------------------------------------------------
    # tools
    # ------------------------------------------------------------------
    def set_tool(self, tool: str):
        for v in self._pool:
            v.set_tool(tool)
        act = self.tool_actions.get(tool)
        if act is not None:
            act.setChecked(True)

    def action_delete(self):
        if self.active:
            self.active.delete_selected()

    def action_escape(self):
        if self.active:
            self.active._pending = None
            self.active._pending_preview = False
            self.active.selected = None
            self.active.update()

    def action_clear_series(self):
        if self.active and self.active.series:
            self.store.clear_series(self.active.series.uid)
            self._annotations_changed(None)
            for v in self._pool:
                v.selected = None
                v.update()

    def action_clear_all(self):
        if self.store.count() == 0:
            return
        if QMessageBox.question(
                self, APP_NAME,
                f"Delete all {self.store.count()} annotations in this study?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self.store.clear_all()
        self._annotations_changed(None)
        for v in self._pool:
            v.selected = None
            v.update()

    def action_annotation_color(self):
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor
        color = QColorDialog.getColor(QColor(self.settings["annotation_color"]),
                                      self, "Annotation colour")
        if color.isValid():
            self.settings["annotation_color"] = color.name()
            self.settings.save()

    # ------------------------------------------------------------------
    # window / level
    # ------------------------------------------------------------------
    def _refresh_presets(self):
        if not hasattr(self, "preset_combo"):
            return
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("DICOM default", ("default", 0, 0))
        self.preset_combo.addItem("Auto (1-99 %)", ("auto", 0, 0))
        self.preset_combo.addItem("Full range", ("full", 0, 0))
        modality = ""
        if self.active is not None and self.active.series is not None:
            modality = self.active.series.modality
        for name, c, w in wl.preset_list(modality):
            self.preset_combo.addItem(name, ("fixed", c, w))
        for p in self.settings["user_presets"] or []:
            self.preset_combo.addItem(f"★ {p['name']}",
                                      ("fixed", p["center"], p["width"]))
        self.preset_combo.insertSeparator(self.preset_combo.count())
        self.preset_combo.addItem("Save current as preset…", ("save", 0, 0))
        self.preset_combo.blockSignals(False)

    def _preset_chosen(self, index):
        data = self.preset_combo.itemData(index)
        if not data:
            return
        kind, c, w = data
        if kind == "save":
            self._save_preset()
            return
        for v in ([self.active] if not self.link_window else self.viewports):
            if v is None or v.series is None:
                continue
            if kind == "default":
                v.default_window()
            elif kind == "auto":
                v.auto_window()
            elif kind == "full":
                v.full_window()
            else:
                v.set_window(c, w)

    def _save_preset(self):
        from PyQt6.QtWidgets import QInputDialog
        if self.active is None or self.active.series is None:
            return
        name, ok = QInputDialog.getText(self, "Save window preset", "Preset name:")
        if ok and name.strip():
            self.settings.add_preset(name.strip(), self.active.win_center,
                                     self.active.win_width)
            self._refresh_presets()

    def action_window_dialog(self):
        if self.active is None or self.active.image is None:
            return
        img = self.active.image
        dlg = WindowLevelDialog(self.active.win_center, self.active.win_width,
                                (float(img.min()), float(img.max())), self)
        if dlg.exec():
            c, w = dlg.values()
            self.active.set_window(c, w)

    # ------------------------------------------------------------------
    # synchronisation
    # ------------------------------------------------------------------
    def _sync_changed(self):
        self.link_scroll = self.act_link_scroll.isChecked()
        self.link_window = self.act_link_window.isChecked()
        was_linked = self.link_zoom
        self.link_zoom = self.act_link_zoom.isChecked()
        if self.link_zoom and not was_linked and self.active is not None:
            self._transform_changed(self.active)

    def _refresh_reference_lines(self):
        """Repaint every viewport after any plane moves.

        A viewport draws the localizer lines of its *peers*, so a slice change
        in one viewport leaves stale lines in all the others until they repaint
        too.  Qt coalesces these requests into a single paint per viewport.
        """
        for v in self.viewports:
            if v.series is not None and v.show_reference_lines:
                v.update()

    def _slice_changed(self, view, index):
        if view is self.active:
            self._update_slider()
        self._refresh_reference_lines()
        if self._syncing or not self.link_scroll:
            return
        self._syncing = True
        try:
            inst = view.instance
            point = None
            if inst is not None and inst.geometry.valid:
                point = inst.geometry.to_patient(inst.cols / 2, inst.rows / 2)
            for other in self.viewports:
                if other is view or other.series is None:
                    continue
                if point is not None and other.series.plane == view.series.plane \
                        and other.instance is not None \
                        and other.instance.geometry.valid:
                    other.set_index(geo.nearest_slice(other.series, point),
                                    notify=False)
                else:
                    ratio = index / max(1, len(view.series) - 1)
                    other.set_index(round(ratio * (len(other.series) - 1)),
                                    notify=False)
        finally:
            self._syncing = False

    def _window_changed(self, view, center, width):
        if self._syncing or not self.link_window:
            return
        self._syncing = True
        try:
            for other in self.viewports:
                if other is not view and other.series is not None:
                    other.set_window(center, width, notify=False)
        finally:
            self._syncing = False

    def _transform_changed(self, view):
        """Mirror zoom and pan onto the other viewports when linking is on."""
        if self._syncing or not self.link_zoom:
            return
        self._syncing = True
        try:
            for other in self.viewports:
                if other is not view and other.series is not None:
                    other.apply_transform_from(view)
        finally:
            self._syncing = False

    def _crosshair_moved(self, view, point):
        """Point every other viewport at the same anatomy, where it has it.

        A series that never imaged this location keeps its current slice and
        shows no cursor, rather than jumping to an edge slice and implying the
        point is visible there.
        """
        missed = []
        for other in self.viewports:
            if other is view or other.series is None:
                continue
            idx, distance, covered = geo.locate_point(other.series, point)
            if covered:
                other.set_index(idx, notify=False)
                other.set_crosshair(point)
            else:
                other.set_crosshair(None)
                missed.append((other.series.number, distance))
        self._refresh_reference_lines()
        self._update_slider()
        if missed:
            detail = ", ".join(f"series {n} ({d:.0f} mm away)" for n, d in missed)
            self.statusBar().showMessage(
                f"Point is outside the imaged volume of {detail}", 4000)

    # ------------------------------------------------------------------
    # cine
    # ------------------------------------------------------------------
    def action_toggle_cine(self):
        self.btn_play.setChecked(not self.btn_play.isChecked())

    def toggle_cine(self, playing: bool):
        self.btn_play.setText("❚❚" if playing else "▶")
        if playing:
            self.cine_timer.start(int(1000 / self.fps_spin.value()))
        else:
            self.cine_timer.stop()

    def _fps_changed(self, value):
        if self.cine_timer.isActive():
            self.cine_timer.start(int(1000 / max(1, value)))

    def _cine_tick(self):
        view = self.active
        if view is None or view.series is None:
            return
        nxt = view.index + 1
        if nxt >= len(view.series):
            nxt = 0
        view.set_index(nxt)

    # ------------------------------------------------------------------
    # slider / navigation
    # ------------------------------------------------------------------
    def _update_slider(self):
        view = self.active
        if view is None or view.series is None:
            self.slice_slider.setRange(0, 0)
            self.slice_label.setText("—")
            return
        self.slice_slider.blockSignals(True)
        self.slice_slider.setRange(0, max(0, len(view.series) - 1))
        self.slice_slider.setValue(view.index)
        self.slice_slider.blockSignals(False)
        self.slice_label.setText(f"{view.index + 1} / {len(view.series)}")

    def _slider_changed(self, value):
        if self.active is not None:
            self.active.set_index(value)

    def _step(self, delta):
        if self.active is not None:
            self.active.step(delta)

    def _goto(self, index):
        if self.active is not None:
            self.active.set_index(index)

    # ------------------------------------------------------------------
    # annotations
    # ------------------------------------------------------------------
    def _annotations_changed(self, _view):
        self.annotation_panel.refresh()
        self._refresh_annotation_badges()

    def _refresh_annotation_badges(self):
        if self.study:
            counts = {s.uid: self.store.count_for_series(s.uid)
                      for s in self.study.series}
            self.series_panel.mark_annotated(counts)

    def _goto_annotation(self, series, ann, sop_uid):
        view = self.active or (self.viewports[0] if self.viewports else None)
        if view is None:
            return
        if view.series is not series:
            view.set_series(series)
        for i, inst in enumerate(series.instances):
            if inst.sop_uid == sop_uid:
                view.set_index(i)
                break
        view.selected = ann
        view.update()
        self._update_slider()

    def _delete_annotation(self, ann):
        self.store.remove(ann)
        for v in self._pool:
            if v.selected is ann:
                v.selected = None
            v.update()
        self._annotations_changed(None)

    def _autosave_tick(self):
        if self.store.dirty and self.store.path:
            try:
                self.store.save()
            except OSError:
                pass

    def action_save(self):
        if not self.store.path:
            if not self.folder:
                return
            self.store.path = AnnotationStore.default_path(self.folder)
        try:
            path = self.store.save()
            self.statusBar().showMessage(
                f"Saved {self.store.count()} annotation(s) to {path}", 5000)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not save:\n{exc}")

    def action_save_as(self):
        start = self.store.path or os.path.join(self.folder or "", "annotations.json")
        path, _ = QFileDialog.getSaveFileName(self, "Save annotations", start,
                                              "JSON files (*.json)")
        if path:
            try:
                self.store.save(path)
                self.statusBar().showMessage(f"Saved to {path}", 5000)
            except OSError as exc:
                QMessageBox.warning(self, APP_NAME, f"Could not save:\n{exc}")

    def action_load_annotations(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load annotations",
                                              self.folder or "",
                                              "JSON files (*.json)")
        if not path:
            return
        try:
            n = self.store.load(path, merge=True)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not load:\n{exc}")
            return
        self._annotations_changed(None)
        for v in self._pool:
            v.update()
        self.statusBar().showMessage(f"Loaded {n} annotation(s)", 5000)

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------
    def action_export_image(self):
        view = self.active
        if view is None or view.series is None:
            return
        default = self._export_name(view) + ".png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export image", os.path.join(self.folder or "", default),
            "PNG image (*.png);;JPEG image (*.jpg)")
        if not path:
            return
        img = view.render_image(with_overlay=view.show_overlay, scale=2.0)
        if img is None or not img.save(path):
            QMessageBox.warning(self, APP_NAME, "The image could not be written.")
        else:
            self.statusBar().showMessage(f"Exported {path}", 5000)

    def action_export_series(self):
        view = self.active
        if view is None or view.series is None:
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Export series to folder", self.folder or "")
        if not folder:
            return
        series = view.series
        saved = view.index
        progress = QProgressDialog("Exporting images…", "Cancel", 0,
                                   len(series), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        base = self._export_name(view)
        written = 0
        for i in range(len(series)):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            view.set_index(i, notify=False)
            view.repaint()
            img = view.render_image(with_overlay=view.show_overlay, scale=2.0)
            if img is not None and img.save(
                    os.path.join(folder, f"{base}_{i + 1:04d}.png")):
                written += 1
        progress.setValue(len(series))
        view.set_index(saved, notify=False)
        self.statusBar().showMessage(f"Exported {written} image(s) to {folder}", 6000)

    def action_copy_clipboard(self):
        view = self.active
        if view is None or view.series is None:
            return
        img = view.render_image(with_overlay=view.show_overlay, scale=2.0)
        if img is not None:
            QGuiApplication.clipboard().setImage(img)
            self.statusBar().showMessage("Image copied to the clipboard", 4000)

    def _export_name(self, view) -> str:
        p = self.study.patient_info() if self.study else {"id": "study"}
        ser = view.series
        raw = f"{p.get('id', 'study')}_Se{ser.number}_{ser.description}"
        return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in raw)

    def action_export_report(self):
        if self.store.count() == 0:
            QMessageBox.information(self, APP_NAME, "There are no measurements yet.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export measurement report",
            os.path.join(self.folder or "", "measurements.csv"),
            "CSV file (*.csv)")
        if not path:
            return
        rows = self._collect_report()
        fields = ["series", "series_description", "image", "instance", "type",
                  "value", "unit", "mean", "sd", "min", "max", "pixels", "note"]
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not write the report:\n{exc}")
            return
        self.statusBar().showMessage(f"Wrote {len(rows)} measurement(s) to {path}",
                                     6000)

    def _collect_report(self) -> list[dict]:
        from .measure import Scale
        rows = []
        by_uid = {s.uid: s for s in (self.study.series if self.study else [])}
        for ser_uid, sop_uid, ann in self.store.all_items():
            series = by_uid.get(ser_uid)
            if series is None:
                continue
            idx, inst = -1, None
            for i, cand in enumerate(series.instances):
                if cand.sop_uid == sop_uid:
                    idx, inst = i, cand
                    break
            scale = Scale.from_instance(inst) if inst else Scale(1, 1, False)
            image = inst.pixels if (inst is not None and ann.is_roi) else None
            data = ann.report_row(scale, image)
            value = data.get("length", data.get("angle", data.get("area",
                             data.get("value", ""))))
            rows.append({
                "series": series.number,
                "series_description": series.description,
                "image": idx + 1 if idx >= 0 else "",
                "instance": inst.number if inst else "",
                "type": ann.name,
                "value": value,
                "unit": data.get("unit", scale.area_unit if ann.is_roi else ""),
                "mean": data.get("mean", ""),
                "sd": data.get("sd", ""),
                "min": data.get("min", ""),
                "max": data.get("max", ""),
                "pixels": data.get("pixels", ""),
                "note": ann.text,
            })
        rows.sort(key=lambda r: (r["series"], r["image"] or 0))
        return rows

    # ------------------------------------------------------------------
    # misc actions
    # ------------------------------------------------------------------
    def _update_overlay_flags(self):
        for v in self._pool:
            v.show_overlay = self.act_overlay.isChecked()
            v.show_annotations = self.act_annotations.isChecked()
            v.show_reference_lines = self.act_reflines.isChecked()
            v.show_orientation = self.act_orientation.isChecked()
            v.show_scale_bar = self.act_scalebar.isChecked()
            v.smooth = self.act_smooth.isChecked()
            v.veterinary = self.veterinary
            v.update()

    def _vet_changed(self):
        self.veterinary = self.act_vet.isChecked()
        self.settings["veterinary_labels"] = self.veterinary
        self.settings.save()
        if self.study:
            self.series_panel.set_study(self.study, self.veterinary)
            self.info_panel.set_study(self.study, self.veterinary)
            self._refresh_annotation_badges()
            self._refresh_series_marks()
        self._update_overlay_flags()

    def action_reset(self):
        view = self.active
        if view is None or view.series is None:
            return
        view.reset_display()
        view.default_window()
        view.update()

    def action_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def action_tags(self):
        if self.active is None or self.active.instance is None:
            return
        if self._tag_browser is None:
            self._tag_browser = TagBrowser(self)
        self._tag_browser.show_instance(self.active.instance)
        self._tag_browser.show()
        self._tag_browser.raise_()

    def _mpr_for_series(self, series):
        MprWindow(series, self).show()

    def _tags_for_series(self, series):
        if self._tag_browser is None:
            self._tag_browser = TagBrowser(self)
        self._tag_browser.show_instance(series.first)
        self._tag_browser.show()
        self._tag_browser.raise_()

    def action_mpr(self):
        if self.active is None or self.active.series is None:
            return
        series = self.active.series
        if not series.is_volume:
            QMessageBox.information(
                self, APP_NAME,
                f"Series {series.number} is not a uniformly spaced parallel "
                "stack, so it cannot be reconstructed.")
            return
        win = MprWindow(series, self)
        win.show()

    def action_help(self):
        if self._help is None:
            self._help = HelpDialog(self)
        self._help.show()
        self._help.raise_()

    def action_about(self):
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h3>{APP_NAME}</h3>"
            "<p>A DICOM viewer and annotation workstation for radiological "
            "reading.</p>"
            "<p>Built on pydicom, NumPy and PyQt6.</p>"
            "<p style='color:#c8a24a'>Not a certified medical device. "
            "Not for primary diagnostic use.</p>")

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        if self.store.dirty and self.store.path:
            answer = QMessageBox.question(
                self, APP_NAME, "Save annotations before closing?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    self.store.save()
                except OSError:
                    pass
        self.settings.save()
        super().closeEvent(event)


def run(folder: str | None = None) -> int:
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    window = MainWindow(folder)
    window.show()
    return app.exec()
