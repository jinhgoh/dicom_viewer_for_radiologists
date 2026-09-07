# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

DicomView — an offline DICOM viewer and annotation workstation (PACS-style), built on
pydicom + NumPy + PyQt6. `README.md` documents the user-facing behaviour in depth and is
accurate; read it before changing UI semantics. This file covers what the README does not:
how the code fits together.

Not a git repository. Not a certified medical device — keep the disclaimers in
`action_about` and the README intact.

## Commands

```bash
python selftest.py                  # full suite against the study in the PARENT folder
python selftest.py "D:\studies\x"   # against another study
python viewer.py                    # run the app on the parent folder
python viewer.py "D:\studies\x"
python -m dicomview <folder>        # same app; unlike viewer.py, no argument
                                    # means no default folder (empty window)
pip install -r requirements.txt     # pydicom>=3.0, numpy>=1.24, PyQt6>=6.5
```

`DicomView.bat` is the double-click launcher: it checks for Python, auto-installs
requirements if imports fail, then runs `pythonw viewer.py`.

Verified working: Python 3.12.9, pydicom 3.0.2, numpy 2.5.0 — 59/59 checks pass.

### Testing

`selftest.py` is the entire test suite — no pytest, no test discovery. It is one `main()`
function running sequential `check(name, ok, detail)` assertions grouped by `section()`,
printing `PASS`/`FAIL` per line and exiting 1 if any failed. It sets
`QT_QPA_PLATFORM=offscreen` at import time and constructs **real** `Viewport` and
`MainWindow` widgets, so GUI wiring (hanging marks, reference-line repaints, transform
round-trips) is genuinely covered.

There is no way to run a single check — add new checks into the relevant `section()` block
in `main()`. The suite needs a real study folder; it validates measurement maths against
closed-form values and ROI masks against NumPy slicing, so it will fail on a study whose
first series is too small for the hard-coded 100×100 test ROIs.

The suite never writes to the study folder (it saves annotations into a `TemporaryDirectory`).

## Architecture

Layering is strict and worth preserving: `dicom_io` and `geometry` and `windowing` are
Qt-free domain logic (except `measure.py`, which needs QPainterPath for rasterising ROIs);
`viewport`/`panels`/`dialogs`/`mainwindow` are the Qt layer. `mainwindow` orchestrates and
owns all cross-viewport policy — viewports never talk to each other directly.

### Three coordinate spaces

This is the central concept; nearly every bug lives at a boundary between them.

| Space | Units | Where |
|---|---|---|
| **Image pixel** | pixels, origin top-left of the image | annotations store their points here |
| **Widget/screen** | device pixels in the `Viewport` | painting, mouse events |
| **Patient (LPS)** | millimetres, +X left / +Y posterior / +Z head | cross-referencing, MPR, slice sorting |

- Image ↔ widget: `Viewport.image_transform()` builds one `QTransform` (translate → rotate →
  zoom/flip → aspect correction for non-square `PixelSpacing` → centre). Use
  `image_to_widget()` / `widget_to_image()`; never hand-roll the maths.
- Image ↔ patient: `ImageGeometry.to_patient(x, y)` / `.to_pixel(point)` in `dicom_io.py`.
- **Annotations are stored in image pixel coordinates** (`measure.py` docstring) — that is
  what makes them survive zoom, pan, rotate and flip, and what makes the JSON portable.
  Physical mm values are derived at *display* time via `Scale.from_instance()`. Do not
  "helpfully" convert stored points to mm.

`Scale` falls back to 1.0 mm/px with `calibrated=False` when a series has no `PixelSpacing`,
and the unit strings switch from `mm`/`mm²` to `px`/`px²` accordingly — measurement code
must go through `scale.unit` / `scale.area_unit` rather than hard-coding "mm".

### Data model

`scan_folder(folder, progress)` → `list[Study]` → `Study.series` → `Series.instances` →
`Instance`. Grouped by `SeriesInstanceUID` then `StudyInstanceUID`; both get a `finalise()`
call after collection.

- **Headers eager, pixels lazy.** `scan_folder` reads with `stop_before_pixels=True`.
  `Instance.pixels` is a property that decodes on first access, applies
  RescaleSlope/Intercept, converts colour → luminance and inverts MONOCHROME1, then caches.
- **Decode failures never raise into a paint event.** `Instance.pixels` catches everything,
  stores a human-readable string in `Instance.decode_error` (including the pip install hint
  for compressed transfer syntaxes) and returns `None`; `Viewport.paintEvent` renders that
  text. Preserve this contract — a raised exception inside `paintEvent` is fatal in Qt.
- `Series._sort()` sorts by projection onto the slice normal, **not** InstanceNumber, and
  falls back to InstanceNumber when every slice projects to the same location (multi-echo /
  time series). `Series.is_volume` additionally requires uniform spacing and matching
  dimensions; it gates MPR (`action_mpr` refuses non-volumes with a message rather than
  reconstructing garbage).
- `scan_folder` skips dot-directories and any directory named `dicomviewer` — that is why
  pointing the app at the parent folder does not recurse into the source tree.
  `_is_candidate` accepts extensionless files, so DICOM without `.dcm` still loads.

### Text encoding

`dicom_io.fix_text()` repairs the Korean-PACS mojibake case (CP949 bytes declared as
`ISO_IR 6`) by round-tripping through latin-1 and retrying a fallback encoding chain.
**Every DICOM string that reaches the UI must go through `fix_text` or `Instance.text()`** —
raw `ds.get("PatientName")` renders as mojibake on any such export, including the test study
this repo is developed against. CSV export uses UTF-8 BOM so Excel opens the result correctly.

### Viewport pool and layout

`MainWindow._pool` is a monotonically growing list of `Viewport` widgets; `self.viewports`
is `_pool[:rows*cols]`. `_set_layout` reparents everything into the `QGridLayout` — viewports
are reused, never destroyed, so **display state persists when the user shrinks and regrows
the layout**. `toggle_maximize` stashes the previous grid shape in `_maximized_state`.

Consequences to remember: state pushed to "all viewports" must decide between `self.viewports`
(visible) and `self._pool` (all, including hidden). `open_folder` deliberately pushes the new
`AnnotationStore` into every member of `_pool`.

### Cross-viewport synchronisation

Every viewport emits signals; `_make_viewport` wires all of them to `MainWindow` handlers.
Two patterns are load-bearing:

1. **The `_syncing` re-entrancy guard.** `_slice_changed`, `_window_changed` and
   `_transform_changed` set `self._syncing = True` in a `try/finally` and propagate with
   `notify=False`, so mirroring one viewport onto its peers cannot feed back. Any new linked
   property must follow this exact shape or it will recurse.
2. **`Viewport.reference_provider`** — a callback injected by `MainWindow` as
   `lambda: list(self.viewports)`. A viewport draws the localizer lines of its *peers*, so a
   slice change leaves stale lines everywhere else; `_refresh_reference_lines()` must be
   called after any plane moves. It is deliberately a callback, not a back-pointer to
   MainWindow, to keep `Viewport` independently constructible (the selftest relies on this).

Linked scroll matches by **patient position** (`geo.nearest_slice`) for same-plane series and
only falls back to index ratio otherwise, so stacks with different spacing stay aligned.

`geometry.locate_point()` returns `(index, distance_mm, covered)`. The `covered` flag is a
deliberate clinical-safety design: a series that never imaged the clicked location keeps its
current slice and shows **no** cursor, with a status-bar note, rather than jumping to an edge
slice and implying the anatomy is visible there. Do not "fix" this by clamping.

### Annotations

`AnnotationStore` (`session.py`) is a single shared instance keyed by
`(SeriesInstanceUID, SOPInstanceUID)` — that is what reattaches annotations after the folder
moves. Viewports mutate it directly and set `store.dirty`; a 4-second `QTimer` autosaves, and
`closeEvent` prompts. Saving is atomic (`.tmp` + `os.replace`).

Adding a new annotation type touches five places:

1. Subclass `Annotation` (or `RoiMixin, Annotation`) in `measure.py` with a unique `kind`,
   `name`, `min_points`/`max_points`.
2. Register it in the `ANNOTATION_TYPES` tuple — `Annotation.from_dict` dispatches on `kind`,
   so an unregistered type silently drops on load.
3. Add a `T_*` constant and an `ANNOTATION_TOOLS` entry in `viewport.py` (plus `CLICK_TOOLS`
   if it is built by clicking vertices rather than one drag).
4. Add a row to `TOOLS` in `mainwindow.py` (label, tool constant, shortcut, icon name).
5. Add a builder to `_BUILDERS` in `icons.py` — icons are vector-drawn at runtime, the app
   ships no image assets.

Override `describe()` for on-image labels and `report_row()` for the CSV export.
`RoiMixin.mask()` rasterises the exact `QPainterPath` into a boolean mask via an offscreen
`QImage`, so ROI statistics are true to the drawn shape, not its bounding box — the selftest
checks this against NumPy and against πr².

### Rendering and caching

Two caches, both easy to break:

- `windowing._LUT_CACHE` — for 8/16-bit integer images `apply_window` builds a full
  65536-entry lookup table keyed by `(dtype, center, width, invert)` instead of doing
  per-pixel arithmetic. This is why window dragging stays responsive; keep the fast path.
- `Viewport._cache_key` = `(id(img), center, width, invert, colormap)`. Note it uses
  **`id(img)`** — mutating pixel data in place will not invalidate the cache. Set
  `self._cache_key = None` after anything that should force a re-render.

`Viewport._qimage_buf` must keep referencing the NumPy array: `QImage` wraps that buffer
without copying, so dropping the reference produces garbage or a crash.

### Backlink gotcha

`MainWindow.load_study` sets `ser.study = study` on each `Series` — an attribute assigned
outside `Series.__init__`. `viewport._study_of()` reads it via `getattr(..., None)` and the
four-corner overlay degrades gracefully without it. A `Series` obtained straight from
`scan_folder` has no `.study`.

### Veterinary orientation

`geometry.py` holds two label tables: `HUMAN_LABELS` (L/R, P/A, H/F) and `VET_LABELS`
(L/R, D/V, Cr/Cd). The veterinary mapping (+Y → dorsal, +Z → cranial) **assumes sternal
recumbency** and is wrong for an animal scanned in dorsal recumbency — which is precisely why
it is an explicit `View` toggle auto-defaulted from `Study.looks_veterinary()` rather than
applied silently. `Settings["veterinary_labels"]` is tri-state: `None` means auto-detect per
study. Keep it a user-visible choice.

### Window presets

`windowing.preset_list(modality)` returns CT presets only for CT/PT/PET. MR intensities are
arbitrary and vary per sequence, so Hounsfield presets are meaningless there and the list is
intentionally empty — do not add MR presets.

## Conventions

- British spelling in user-facing strings and comments (`finalise`, `synchronise`,
  `colour map`), matching the README.
- Type hints use `from __future__ import annotations` with `X | None` syntax.
- Comments explain *why*, particularly for clinical-safety decisions; several of those
  decisions look like bugs until you read the comment. Preserve them when refactoring.
- Section banners (`# ---- name ----`) separate concerns within the larger modules.
