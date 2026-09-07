#!/usr/bin/env python3
"""Self-check for DicomView.

    python selftest.py [dicom-folder]

Verifies DICOM parsing, geometry, windowing, measurement mathematics, ROI
statistics, annotation persistence and the export paths against a real study.
Runs headless; no windows appear and nothing in the study folder is modified.
"""
from __future__ import annotations

import math
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

FAILURES: list[str] = []
CHECKS = 0


def check(name: str, ok: bool, detail=""):
    global CHECKS
    CHECKS += 1
    mark = "PASS" if ok else "FAIL"
    line = f"  {mark}  {name}"
    if detail != "":
        line += f"   [{detail}]"
    print(line)
    if not ok:
        FAILURES.append(name)


def section(title: str):
    print(f"\n{title}")


def main(folder: str) -> int:
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication

    from dicomview import dicom_io, geometry as geo, measure as ms, windowing as wl
    from dicomview.session import AnnotationStore

    # the QApplication must stay referenced for the widget tests below
    app = QApplication.instance() or QApplication([])
    assert app is not None

    # -- loading -------------------------------------------------------
    section("DICOM loading")
    studies = dicom_io.scan_folder(folder)
    check("a study was found", len(studies) >= 1, f"{len(studies)} studies")
    if not studies:
        return 1
    study = studies[0]
    check("series were grouped", len(study.series) >= 1, f"{len(study.series)} series")
    check("images were counted", study.image_count >= 1, study.image_count)
    info = study.patient_info()
    check("patient name decoded without mojibake",
          "Ã" not in info["name"] and "¹" not in info["name"], info["name"] or "(empty)")

    series = max(study.series, key=len)
    check("slices sort monotonically",
          all(a.sort_key <= b.sort_key
              for a, b in zip(series.instances, series.instances[1:])))

    inst = series.first
    image = inst.pixels
    check("pixel data decodes", image is not None,
          None if image is None else f"{image.shape} {image.dtype}")
    if image is None:
        return 1

    # -- windowing -----------------------------------------------------
    section("Windowing")
    c, w = wl.auto_window(image)
    check("auto window has positive width", w > 0, f"C={c:.0f} W={w:.0f}")
    g = wl.apply_window(image, c, w)
    check("windowed output is 8-bit", g.dtype == np.uint8 and g.shape == image.shape)
    check("windowed output spans the range", g.min() <= 5 and g.max() >= 250,
          f"{g.min()}..{g.max()}")
    flat = wl.apply_window(image, c, w, invert=True)
    check("inversion mirrors the ramp", int(g[0, 0]) + int(flat[0, 0]) == 255)
    rgb = wl.colorize(g, "Hot iron")
    check("colour map returns RGB", rgb is not None and rgb.shape == g.shape + (3,))

    # -- geometry ------------------------------------------------------
    section("Patient geometry")
    gm = inst.geometry
    if gm.valid:
        px = (gm.cols * 0.3, gm.rows * 0.7)
        point = gm.to_patient(*px)
        back = gm.to_pixel(point)
        check("pixel -> patient -> pixel round-trips",
              abs(back[0] - px[0]) < 1e-3 and abs(back[1] - px[1]) < 1e-3,
              f"{px} -> {tuple(round(v, 3) for v in back)}")
        check("a slice's own plane distance is zero",
              abs(gm.distance_to_plane(point)) < 1e-6)
        idx, dist, covered = geo.locate_point(series, point)
        check("point locates to its own slice", idx == 0 and covered,
              f"index={idx} covered={covered} d={dist:.3f}")
        labels = geo.edge_labels(gm)
        check("orientation labels produced", len(labels) == 4, labels)
        rot = geo.transform_edge_labels(labels, 90, False, False)
        check("rotating 90 deg moves top to right", rot["right"] == labels["top"],
              f"{labels} -> {rot}")
        flip = geo.transform_edge_labels(labels, 0, True, False)
        check("horizontal flip swaps left and right",
              flip["left"] == labels["right"] and flip["right"] == labels["left"])

        others = [s for s in study.series if s.plane != series.plane and len(s)]
        if others:
            line = geo.plane_intersection_line(inst.geometry, others[0].first.geometry)
            check("cross-reference line computed for a crossing plane",
                  line is not None, line)
        check("a plane does not cross itself",
              geo.plane_intersection_line(gm, gm) is None)
    else:
        check("geometry present", False, "no ImageOrientationPatient")

    # -- measurements --------------------------------------------------
    section("Measurement mathematics")
    scale = ms.Scale.from_instance(inst)
    d = scale.d_col
    length = ms.Length(points=[[100, 100], [200, 100]])
    check("100 px horizontal length", abs(length.value(scale) - 100 * d) < 1e-6,
          length.describe(scale))
    diag = ms.Length(points=[[0, 0], [300, 400]])
    check("3-4-5 diagonal length",
          abs(diag.value(scale) - 500 * d) < 1e-6 if scale.isotropic else True,
          diag.describe(scale))
    check("right angle measures 90 deg",
          abs(ms.Angle(points=[[100, 0], [100, 100], [200, 100]]).value(scale) - 90)
          < 1e-6)
    check("Cobb angle of two 45 deg lines",
          abs(ms.CobbAngle(points=[[0, 0], [100, 0], [0, 0], [100, 100]]).value(scale)
              - 45) < 1e-6)

    section("ROI statistics")
    rect = ms.Rectangle(points=[[100, 100], [200, 150]])
    st = rect.statistics(image, scale)
    truth = image[100:150, 100:200].astype(float)
    check("rectangle mask covers the right pixels", abs(st["count"] - 5000) <= 200,
          st["count"])
    check("rectangle mean matches NumPy", abs(st["mean"] - truth.mean()) < 3.0,
          f"{st['mean']:.2f} vs {truth.mean():.2f}")
    check("rectangle area uses pixel spacing",
          abs(st["area"] - st["count"] * scale.pixel_area) < 1e-6)
    ell = ms.Ellipse(points=[[100, 100], [200, 200]])
    est = ell.statistics(image, scale)
    ideal = math.pi * 50 * 50
    check("ellipse mask area within 5% of pi r^2",
          abs(est["count"] - ideal) / ideal < 0.05, f"{est['count']} vs {ideal:.0f}")
    poly = ms.Polygon(points=[[0, 0], [100, 0], [100, 100], [0, 100]])
    check("polygon mask matches a 100x100 square",
          abs(poly.statistics(image, scale)["count"] - 10000) <= 250)

    # -- persistence ---------------------------------------------------
    section("Annotation persistence")
    store = AnnotationStore()
    sop = inst.sop_uid
    note = ms.TextNote(points=[[10, 20]])
    note.text = "환자 메모 / note"
    for ann in (length, ell, poly, note, ms.Arrow(points=[[1, 2], [3, 4]])):
        store.add(series.uid, sop, ann)
    n = store.count()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "annotations.json")
        store.save(path)
        again = AnnotationStore()
        loaded = again.load(path)
        check("every annotation survives a save/load", loaded == n, f"{loaded} of {n}")
        check("kinds survive",
              sorted(a.kind for _, _, a in again.all_items())
              == sorted(a.kind for _, _, a in store.all_items()))
        check("coordinates survive exactly",
              [a.points for _, _, a in again.all_items()]
              == [a.points for _, _, a in store.all_items()])
        check("non-ASCII note survives",
              [a.text for _, _, a in again.all_items() if a.kind == "text"]
              == ["환자 메모 / note"])

    # -- viewport / export ---------------------------------------------
    section("Viewport and export")
    from dicomview.session import Settings
    from dicomview.viewport import Viewport

    view = Viewport(store, Settings())
    view.resize(800, 600)
    view.set_series(series)
    check("viewport bound the series", view.series is series and view.slice_count == len(series))
    view.set_index(len(series) - 1)
    check("stepping to the last slice", view.index == len(series) - 1)
    view.set_index(10 ** 6)
    check("index is clamped in range", view.index == len(series) - 1)
    view.fit_to_window()
    check("fit produced a positive zoom", view.zoom > 0, f"{view.zoom:.3f}")
    view.zoom_actual()
    check("actual size is 1 screen px per image px",
          abs(view.displayed_scale() - 1.0) < 1e-6)
    p = view.image_to_widget(QPointF(123, 456))
    back = view.widget_to_image(p)
    check("widget <-> image transform round-trips",
          abs(back[0] - 123) < 1e-6 and abs(back[1] - 456) < 1e-6,
          tuple(round(v, 4) for v in back))
    view.rotate(90)
    back = view.widget_to_image(view.image_to_widget(QPointF(50, 60)))
    check("round-trip holds after rotation",
          abs(back[0] - 50) < 1e-6 and abs(back[1] - 60) < 1e-6)
    view.rotate(270)

    rendered = view.render_image(with_overlay=True, scale=1.0)
    check("viewport renders to an image",
          rendered is not None and rendered.width() == 800,
          None if rendered is None else f"{rendered.width()}x{rendered.height()}")
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "frame.png")
        check("rendered image writes as PNG",
              rendered.save(out) and os.path.getsize(out) > 1000,
              os.path.getsize(out) if os.path.exists(out) else 0)

    if series.is_volume:
        built = geo.build_volume(series)
        check("volume assembles for a parallel stack",
              built is not None and built[0].shape[0] == len(series),
              None if built is None else built[0].shape)

    # -- cross-reference line updates ----------------------------------
    section("Cross-reference lines")
    from dicomview.mainwindow import MainWindow

    win = MainWindow()
    win._set_layout(1, 2)
    left, right = win.viewports
    left.set_series(series)
    right.set_series(series)
    win._update_overlay_flags()
    check("reference lines are on by default", left.show_reference_lines)

    # a viewport draws its peers' planes, so moving one must repaint the rest
    repaints = []
    right.update = lambda *a: repaints.append(1)
    left.set_index(0)
    repaints.clear()
    left.set_index(min(7, len(series) - 1))
    check("scrolling one viewport repaints the other", len(repaints) > 0,
          f"{len(repaints)} repaints")

    inst0 = series.first
    if inst0.geometry.valid:
        point = inst0.geometry.to_patient(inst0.cols / 2, inst0.rows / 2)
        # the cursor moves the *peers*' slices, so the viewport the user
        # clicked in has to repaint too - its own lines are now stale
        origin = []
        left.update = lambda *a: origin.append(1)
        win._crosshair_moved(left, point)
        check("the cross-reference cursor repaints the clicked viewport",
              len(origin) > 0, f"{len(origin)} repaints")
        del left.update

    repaints.clear()
    left.set_series(series)
    check("assigning a series repaints the other viewport", len(repaints) > 0,
          f"{len(repaints)} repaints")
    del right.update

    # -- "which series is on screen" marks -----------------------------
    section("Series list hanging marks")
    from dicomview.panels import ROLE_HUNG, ROLE_TIP, ROLE_UID

    win.load_study(study)
    win._set_layout(1, 2)
    panel = win.series_panel
    check("the list holds every series", panel.count() == len(study.series),
          f"{panel.count()} rows")

    def mark(ser):
        for i in range(panel.count()):
            item = panel.item(i)
            if item.data(ROLE_UID) == ser.uid:
                return item.data(ROLE_HUNG)
        return "no such row"

    def tip(ser):
        for i in range(panel.count()):
            item = panel.item(i)
            if item.data(ROLE_UID) == ser.uid:
                return item.toolTip()
        return ""

    a = study.series[0]
    b = study.series[1] if len(study.series) > 1 else a
    win.viewports[0].set_series(a)
    win.viewports[1].set_series(b)
    win.set_active(win.viewports[0])
    check("the series in viewport 1 is marked as active", mark(a) == ([1], True),
          mark(a))
    check("the series in viewport 2 is marked, but not active",
          mark(b) == ([2], False), mark(b))
    check("the tooltip names the viewport",
          "Displayed in viewport 2" in tip(b))

    win.set_active(win.viewports[1])
    check("moving focus moves the active mark",
          mark(a) == ([1], False) and mark(b) == ([2], True))

    unhung = [s for s in study.series if s.uid not in (a.uid, b.uid)]
    if unhung:
        check("a series not on screen carries no mark", mark(unhung[0]) is None,
              mark(unhung[0]))

    win.viewports[1].set_series(a)
    check("one series in two viewports lists both", mark(a) == ([1, 2], True),
          mark(a))
    check("the tooltip names both viewports",
          "Displayed in viewports 1, 2" in tip(a), tip(a).splitlines()[-1:])
    check("the series it replaced is unmarked", mark(b) is None, mark(b))

    win.viewports[1].clear()
    check("clearing a viewport clears its mark", mark(a) == ([1], False), mark(a))

    win.toggle_maximize(win.viewports[0])
    check("maximising leaves only the visible series marked",
          mark(a) == ([1], True) and all(
              panel.item(i).data(ROLE_HUNG) is None
              for i in range(panel.count())
              if panel.item(i).data(ROLE_UID) != a.uid))
    win.toggle_maximize(win.viewports[0])

    win.viewports[0].set_series(b)
    win.act_vet.setChecked(not win.veterinary)
    win._vet_changed()
    check("marks survive the list being rebuilt", mark(b) is not None, mark(b))
    check("the plain tooltip is kept apart from the hanging line",
          "Displayed in" not in (panel.item(0).data(ROLE_TIP) or ""))

    win.close()

    print(f"\n{CHECKS - len(FAILURES)} of {CHECKS} checks passed.")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    print(f"DicomView self-test\nStudy folder: {target}")
    if not os.path.isdir(target):
        print("That folder does not exist.")
        raise SystemExit(2)
    raise SystemExit(main(target))
