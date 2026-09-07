# DicomView
<img width="2291" height="1358" alt="image" src="https://github.com/user-attachments/assets/e8c92632-9534-440b-9974-ffebc48175c1" />

A DICOM viewer and annotation workstation for radiological reading, in the
style of INFINITT PACS Viewer and RadiAnt. It reads a folder of DICOM files,
groups them into studies and series, and provides multi-viewport hanging,
window/level, measurement and annotation tools, cross-referencing between
planes, and export.

Built on pydicom + NumPy + PyQt6. Works entirely offline; nothing leaves the
machine.

> Not a certified medical device. Not for primary diagnostic use.

---

## Running it

Double-click **`DicomView.bat`**, or from a terminal:

```
python viewer.py                 # opens the folder this project sits in
python viewer.py "D:\studies\patient01"
```

First-time setup, if the libraries are missing:

```
pip install -r requirements.txt
```

Compressed DICOM (JPEG, JPEG 2000, JPEG-LS, RLE) needs a decoder. Uncompressed
studies work without it:

```
pip install pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg
  or
pip install python-gdcm
```

Without a decoder, compressed images show an explanatory message in the
viewport instead of failing silently.

Text is decoded defensively. Some PACS exports declare
`SpecificCharacterSet = ISO_IR 6` (ASCII) while actually carrying CP949 or
Shift-JIS bytes, which would otherwise render patient and institution names as
mojibake; such text is re-decoded through a CP949/EUC-KR/Shift-JIS fallback
chain.

---

## Interface

```
┌──────────────────────────────────────────────────────────────────────┐
│ menu bar                                                              │
│ toolbar:  file · navigation tools · measurement tools · display · W/L │
├────────────┬────────────────────────────────────────┬────────────────┤
│ patient &  │                                        │ Measurements   │
│ study info │           viewport grid                │ list: type,     │
│            │        (1×1 up to 4×4)                 │ value, series,  │
│ series     │                                        │ image           │
│ thumbnails │                                        │                │
├────────────┴────────────────────────────────────────┴────────────────┤
│ cine controls · slice slider · position readout                       │
└──────────────────────────────────────────────────────────────────────┘
```

Load a series by double-clicking it in the left panel, or drag it onto any
viewport. **Layout → Fill layout with series** hangs the first N series at once.

The list marks the series that are on screen: a coloured bar down the left of
the entry and a badge on its thumbnail carrying the number of the viewport
holding it — viewports counted left to right, top to bottom, so a 2 × 2 grid
runs 1 2 / 3 4. The series in the active viewport is marked in the same bright
blue as that viewport's own frame, the rest in a dimmer blue; a series hung in
two places at once shows both numbers. Hovering an entry says the same thing in
words.

Each viewport shows the standard four-corner overlay: patient identity and
institution (top left), study/series description and date (top right), image
number, window values and zoom (bottom left), and acquisition parameters —
slice thickness and spacing, table position, TR/TE, field strength, matrix and
pixel size (bottom right). Press `O` to hide it.

---

## Tools

**Navigation** — window/level, select & edit, pan, zoom, stack browse,
cross-reference cursor, magnifying glass.

**Measurement** — probe (pixel value), length, polyline, angle, Cobb angle,
rectangle ROI, ellipse ROI, polygon ROI, freehand ROI, arrow, text note.

Every ROI reports **area, mean, standard deviation, min and max** of the
underlying signal, computed from an exact rasterised mask of the drawn shape
(not a bounding-box approximation). Lengths and areas use `PixelSpacing`, so
they are in true millimetres; if a series carries no spacing the units fall
back to pixels and say so.

Annotations belong to the image they were drawn on, keep their position through
zoom/pan/rotate/flip, and can be selected, dragged, reshaped by their handles,
re-labelled, locked, and deleted. Their text labels can be dragged clear of the
anatomy.

### Mouse

| Action | Result |
|---|---|
| Left drag | Active tool (window/level by default) |
| Middle drag | Pan |
| Right drag | Zoom |
| Right click | Context menu, or finish a multi-point measurement |
| Wheel | Scroll slices |
| Shift + wheel | Scroll 10 at a time |
| Ctrl + wheel | Zoom about the cursor |
| Double click | Maximise / restore the viewport |

Multi-point tools (angle, Cobb, polyline, polygon) are built by clicking each
vertex; angle and Cobb complete themselves, polyline and polygon finish on
right-click or double-click. `Esc` cancels one in progress.

### Keyboard

Tools `W S P Z B X G` · `D L A C R E Y F K T` for probe, length, angle, Cobb,
rectangle, ellipse, polygon, freehand, arrow, text.
Display `I` invert · `H`/`V` flip · `Ctrl+L` rotate · `Ctrl+0` fit ·
`Ctrl+1` 100% · `O`/`M`/`N` toggle overlay/annotations/reference lines ·
`Space` cine · `F11` full screen. Layouts `Alt+1`…`Alt+6`.
Press **F1** for the full reference.

---

## Cross-referencing between planes

With more than one viewport showing, each viewport draws the intersection of
the other viewports' current slices as reference lines — the active one solid
yellow and labelled with its series number, the rest dashed grey. Scrolling the
sagittal stack sweeps its line across the transverse and dorsal images, exactly
as in a PACS localizer.

The **cross-reference cursor** (`X`) goes further: click any anatomical point
and every other viewport jumps to the slice containing that point and marks it.

A series that never imaged that location is deliberately left alone and shows no
cursor, with a note in the status bar — a gapped stack covering a short span
will not contain a point picked well outside it on a sagittal image. Moving that
viewport to an edge slice would imply the point is visible there when it is not.

**Tools → Synchronise** additionally offers linked scrolling (matched by patient
position, not slice index, so stacks with different spacing stay aligned),
linked window/level, and linked zoom/pan.

---

## Window / level

The W/L box offers the DICOM default from the header, **Auto** (1–99th
percentile, robust against the air background), and **Full range**. CT presets
(soft tissue, lung, bone, brain, abdomen, angio, spine…) appear automatically
for CT and PET studies, where Hounsfield units make them meaningful; they are
hidden for MR, whose signal intensities are arbitrary and vary per sequence.
Save your own with **Save current as preset…** — user presets persist across
sessions and appear marked with a star.

Seven colour maps are available (hot iron, PET, rainbow, bone, hot metal,
cold/hot), plus greyscale inversion.

---

## Orientation markers

Edge letters are derived from `ImageOrientationPatient` and follow the
viewport's rotation and flips.

A study is recognised as veterinary from its institution name and species/breed
tags, in which case edge markers read **Cr/Cd** (cranial/caudal) and **D/V**
(dorsal/ventral) rather than H/F and P/A. Toggle it in **View → Veterinary
orientation labels**.

DICOM patient coordinates are LPS (+X left, +Y posterior, +Z head), and
scanners write LPS for animals too. The veterinary labels map
+Y → dorsal and +Z → cranial, **which assumes sternal (prone) recumbency** —
the usual position for spinal imaging. For an animal scanned in dorsal
recumbency the dorsal/ventral pair is reversed. This is why the setting is an
explicit toggle rather than something applied silently: switch to human labels
(H/F, A/P) in **View** to see the unambiguous DICOM directions.

A scale bar with 1 mm/10 mm ticks is drawn against the right edge whenever the
series is spatially calibrated.

---

## Multiplanar reconstruction

**Tools → Multiplanar reconstruction** (`Ctrl+M`) reconstructs orthogonal
planes from the active series, with a linked crosshair across the three panes.

It is offered only for series that are genuinely a uniform parallel stack; a
gapped or unevenly spaced series is refused rather than reconstructed into
something misleading. Note that reconstruction quality is bounded by slice
spacing — millimetre-scale slices give coarse reconstructions, and the window
states the voxel size so the limitation is visible rather than implied.

---

## Saving and exporting

Annotations save to `.dicomview/annotations.json` beside the images, written
automatically a few seconds after any change and on exit. They are keyed by
SeriesInstanceUID + SOPInstanceUID, so they reattach to the right image even if
the folder moves. **File → Load annotations…** merges a file from elsewhere,
which is how you hand measurements to a colleague.

- **Export image** (`Ctrl+E`) — PNG/JPEG of the active viewport at 2× resolution
- **Export series as images…** — the whole stack as a numbered PNG sequence
- **Copy image to clipboard** (`Ctrl+C`)
- **Export measurement report…** — CSV of every measurement with series, image,
  type, value, units and ROI statistics, in UTF-8 BOM so Excel opens Korean text
  correctly

**Tools → DICOM tags** (`Ctrl+T`) opens the full header including sequences,
with a filter that matches either the spaced element name or the keyword
("Echo Time" and "EchoTime" both find it), and can dump the header to text.

---

## Verifying it works

```
python selftest.py                       # uses the study in the parent folder
python selftest.py "D:\studies\other"
```

Checks DICOM parsing, slice ordering, windowing, measurement mathematics against
closed-form values, ROI mask accuracy against NumPy, patient-coordinate
round-trips, cross-reference geometry, annotation persistence, and the
report/export paths.

---

## Layout of the code

| File | Purpose |
|---|---|
| `viewer.py` | Launcher |
| `selftest.py` | Self-check suite |
| `dicomview/dicom_io.py` | Loading, character-set repair, study/series model, lazy pixels |
| `dicomview/geometry.py` | Patient-space maths: orientation, reference lines, point location, volumes |
| `dicomview/windowing.py` | VOI LUT transform, presets, colour maps |
| `dicomview/measure.py` | Annotation primitives, ROI statistics, painting |
| `dicomview/viewport.py` | The image viewport: rendering, mouse tools, overlays |
| `dicomview/panels.py` | Series thumbnails, measurement list, study info |
| `dicomview/dialogs.py` | Tag browser, MPR, window/level editor, help |
| `dicomview/mainwindow.py` | Layout, toolbars, synchronisation, export |
| `dicomview/icons.py` | Toolbar icons, drawn at runtime |
| `dicomview/session.py` | Annotation store and settings persistence |
| `dicomview/theme.py` | Dark reading-room theme |

Pixel data is read lazily per image and cached; windowing runs through a
65536-entry lookup table rather than per-pixel arithmetic, so scrolling and
window dragging stay responsive on full-resolution 16-bit images.
