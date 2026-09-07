"""DICOM loading, study/series modelling and pixel access.

Handles the common Korean-PACS quirk where text is encoded CP949 but the
SpecificCharacterSet tag claims plain ASCII (ISO_IR 6).
"""
from __future__ import annotations

import os

import numpy as np

import pydicom
from pydicom.errors import InvalidDicomError

# --------------------------------------------------------------------------
# text handling
# --------------------------------------------------------------------------

_FALLBACK_ENCODINGS = ("cp949", "euc-kr", "shift_jis", "gb18030", "utf-8")


def fix_text(value) -> str:
    """Repair mojibake produced when non-ASCII bytes are decoded as latin-1.

    pydicom decodes with the declared SpecificCharacterSet.  Many Korean and
    Japanese PACS write CP949/Shift-JIS bytes while declaring ISO_IR 6, which
    surfaces as latin-1 mojibake.  Round-trip through latin-1 and retry.
    """
    if value is None:
        return ""
    s = str(value)
    if not s or s.isascii():
        return s
    try:
        raw = s.encode("latin-1")
    except UnicodeEncodeError:
        return s
    for enc in _FALLBACK_ENCODINGS:
        try:
            out = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        # Reject decodings that still look like control noise.
        if any(ord(c) < 32 and c not in "\r\n\t" for c in out):
            continue
        return out
    return s


def person_name(value) -> str:
    """Format a DICOM PersonName for display ("Family^Given" -> "Family Given")."""
    s = fix_text(value)
    parts = [p for p in s.split("^") if p]
    return " ".join(parts) if parts else s


def format_date(value) -> str:
    s = str(value or "")
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s


def format_time(value) -> str:
    s = str(value or "").split(".")[0]
    if len(s) >= 6 and s[:6].isdigit():
        return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"
    if len(s) >= 4 and s[:4].isdigit():
        return f"{s[0:2]}:{s[2:4]}"
    return s


def format_age(value) -> str:
    s = str(value or "").strip()
    if len(s) == 4 and s[:3].isdigit():
        n = int(s[:3])
        unit = {"Y": "y", "M": "mo", "W": "wk", "D": "d"}.get(s[3].upper(), s[3])
        return f"{n}{unit}"
    return s


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------

def _f(seq, default=None):
    if seq is None:
        return default
    try:
        return [float(x) for x in seq]
    except (TypeError, ValueError):
        return default


PLANE_AXIAL = "AXIAL"
PLANE_SAGITTAL = "SAGITTAL"
PLANE_CORONAL = "CORONAL"
PLANE_OBLIQUE = "OBLIQUE"

# Short tags shown on the series list.  Second entry is the veterinary term.
PLANE_LABELS = {
    PLANE_AXIAL: ("AX", "TRV"),
    PLANE_SAGITTAL: ("SAG", "SAG"),
    PLANE_CORONAL: ("COR", "DOR"),
    PLANE_OBLIQUE: ("OBL", "OBL"),
}


def classify_plane(iop) -> str:
    """Classify an image plane from ImageOrientationPatient direction cosines."""
    v = _f(iop)
    if not v or len(v) < 6:
        return PLANE_OBLIQUE
    row = np.array(v[0:3], dtype=float)
    col = np.array(v[3:6], dtype=float)
    normal = np.cross(row, col)
    n = np.linalg.norm(normal)
    if n == 0:
        return PLANE_OBLIQUE
    normal = normal / n
    a = np.abs(normal)
    dominant = int(np.argmax(a))
    # Within ~26 deg of a cardinal axis counts as that plane.
    if a[dominant] < 0.90:
        return PLANE_OBLIQUE
    return (PLANE_SAGITTAL, PLANE_CORONAL, PLANE_AXIAL)[dominant]


class ImageGeometry:
    """Patient-coordinate geometry for one image (DICOM LPS space)."""

    __slots__ = ("origin", "row_dir", "col_dir", "normal", "d_col", "d_row",
                 "rows", "cols", "valid")

    def __init__(self, ds):
        iop = _f(ds.get("ImageOrientationPatient"))
        ipp = _f(ds.get("ImagePositionPatient"))
        ps = _f(ds.get("PixelSpacing"))
        self.rows = int(ds.get("Rows", 0) or 0)
        self.cols = int(ds.get("Columns", 0) or 0)
        self.valid = bool(iop and ipp and len(iop) >= 6 and len(ipp) >= 3)
        if self.valid:
            # IOP first triplet = direction of increasing column index.
            self.row_dir = np.array(iop[0:3], dtype=float)   # along a row (+x pixel)
            self.col_dir = np.array(iop[3:6], dtype=float)   # down a column (+y pixel)
            self.origin = np.array(ipp[0:3], dtype=float)
        else:
            self.row_dir = np.array([1.0, 0.0, 0.0])
            self.col_dir = np.array([0.0, 1.0, 0.0])
            self.origin = np.zeros(3)
        self.normal = np.cross(self.row_dir, self.col_dir)
        n = np.linalg.norm(self.normal)
        if n:
            self.normal = self.normal / n
        # PixelSpacing = [between rows (y step), between columns (x step)]
        if ps and len(ps) >= 2:
            self.d_row, self.d_col = float(ps[0]), float(ps[1])
        else:
            self.d_row = self.d_col = 1.0

    def to_patient(self, x: float, y: float) -> np.ndarray:
        """Pixel (column x, row y) -> patient LPS millimetres."""
        return (self.origin
                + self.row_dir * (x * self.d_col)
                + self.col_dir * (y * self.d_row))

    def to_pixel(self, point) -> tuple[float, float]:
        """Patient LPS millimetres -> pixel (column x, row y). Projects onto plane."""
        v = np.asarray(point, dtype=float) - self.origin
        x = float(np.dot(v, self.row_dir)) / (self.d_col or 1.0)
        y = float(np.dot(v, self.col_dir)) / (self.d_row or 1.0)
        return x, y

    def distance_to_plane(self, point) -> float:
        return float(np.dot(np.asarray(point, dtype=float) - self.origin, self.normal))


# --------------------------------------------------------------------------
# instance / series / study
# --------------------------------------------------------------------------

class Instance:
    """One DICOM image.  Header is read eagerly, pixel data lazily."""

    def __init__(self, path: str, ds):
        self.path = path
        self.ds = ds                     # header only (stop_before_pixels)
        self._pixels = None
        self.sop_uid = str(ds.get("SOPInstanceUID", path))
        try:
            self.number = int(ds.get("InstanceNumber", 0) or 0)
        except (TypeError, ValueError):
            self.number = 0
        self.geometry = ImageGeometry(ds)
        self.rows = self.geometry.rows
        self.cols = self.geometry.cols
        self.sort_key = 0.0
        self.decode_error: str | None = None

    # -- pixel access ------------------------------------------------------
    @property
    def pixels(self) -> np.ndarray | None:
        """Modality-corrected pixels, or None when the image cannot be decoded.

        Compressed transfer syntaxes (JPEG, JPEG 2000, JPEG-LS, RLE) need an
        extra decoder such as pylibjpeg or python-gdcm.  Rather than letting
        that failure escape into a paint event, it is recorded in
        ``decode_error`` and surfaced in the viewport.
        """
        if self._pixels is None and self.decode_error is None:
            try:
                self._decode()
            except Exception as exc:                    # noqa: BLE001
                self.decode_error = self._explain(exc)
                return None
        return self._pixels

    def _explain(self, exc: Exception) -> str:
        syntax = ""
        try:
            ts = self.ds.file_meta.TransferSyntaxUID
            syntax = f"{ts.name} ({ts})" if ts else ""
        except (AttributeError, KeyError):
            pass
        lines = [f"Cannot decode pixel data: {exc}"]
        if syntax:
            lines.append(f"Transfer syntax: {syntax}")
        text = str(exc).lower()
        if any(k in text for k in ("handler", "decompress", "plugin", "codec")):
            lines += [
                "",
                "This image is compressed. Install a decoder, then reopen:",
                "    pip install pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg",
                "  or",
                "    pip install python-gdcm",
            ]
        return "\n".join(lines)

    def _decode(self):
        full = pydicom.dcmread(self.path, force=True)
        arr = full.pixel_array
        if arr.ndim == 3:                         # colour -> luminance
            arr = arr[..., :3].astype(np.float32)
            arr = (0.299 * arr[..., 0] + 0.587 * arr[..., 1]
                   + 0.114 * arr[..., 2])
        slope = full.get("RescaleSlope")
        intercept = full.get("RescaleIntercept")
        if slope is not None or intercept is not None:
            s = float(slope) if slope is not None else 1.0
            b = float(intercept) if intercept is not None else 0.0
            if s != 1.0 or b != 0.0:
                arr = arr.astype(np.float32) * s + b
        if str(full.get("PhotometricInterpretation", "")) == "MONOCHROME1":
            arr = arr.max() - arr
        self._pixels = np.ascontiguousarray(arr)
        self.rows, self.cols = self._pixels.shape[:2]

    def release(self):
        self._pixels = None

    @property
    def loaded(self) -> bool:
        return self._pixels is not None

    def full_dataset(self):
        """Read the complete dataset including pixel data (for the tag browser)."""
        return pydicom.dcmread(self.path, force=True)

    # -- convenience -------------------------------------------------------
    def get(self, key, default=None):
        return self.ds.get(key, default)

    def text(self, key, default="") -> str:
        return fix_text(self.ds.get(key, default))

    def num(self, key, default=None):
        try:
            v = self.ds.get(key)
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    @property
    def slice_location(self):
        v = self.num("SliceLocation")
        if v is not None:
            return v
        if self.geometry.valid:
            return float(np.dot(self.geometry.origin, self.geometry.normal))
        return None


class Series:
    def __init__(self, uid: str):
        self.uid = uid
        self.instances: list[Instance] = []
        self.number = 0
        self.description = ""
        self.modality = ""
        self.plane = PLANE_OBLIQUE
        self.study_uid = ""

    # -- construction ------------------------------------------------------
    def finalise(self):
        first = self.instances[0]
        try:
            self.number = int(first.get("SeriesNumber", 0) or 0)
        except (TypeError, ValueError):
            self.number = 0
        self.description = first.text("SeriesDescription") or first.text("ProtocolName")
        self.modality = str(first.get("Modality", "") or "")
        self.study_uid = str(first.get("StudyInstanceUID", ""))
        self.plane = classify_plane(first.get("ImageOrientationPatient"))
        self._sort()

    def _sort(self):
        geo = self.instances[0].geometry
        if geo.valid and len(self.instances) > 1:
            normal = geo.normal
            for inst in self.instances:
                if inst.geometry.valid:
                    inst.sort_key = float(np.dot(inst.geometry.origin, normal))
                else:
                    inst.sort_key = float(inst.number)
            keys = [i.sort_key for i in self.instances]
            # If every slice projects to the same spot the stack is not spatial
            # (e.g. a multi-echo or time series) - fall back to instance number.
            if max(keys) - min(keys) < 1e-4:
                for inst in self.instances:
                    inst.sort_key = float(inst.number)
        else:
            for inst in self.instances:
                inst.sort_key = float(inst.number)
        self.instances.sort(key=lambda i: (i.sort_key, i.number))

    # -- properties --------------------------------------------------------
    def __len__(self):
        return len(self.instances)

    def __getitem__(self, i) -> Instance:
        return self.instances[i]

    @property
    def first(self) -> Instance:
        return self.instances[0]

    def plane_label(self, veterinary: bool = False) -> str:
        return PLANE_LABELS[self.plane][1 if veterinary else 0]

    @property
    def slice_spacing(self) -> float | None:
        """Median centre-to-centre spacing in mm, if the stack is spatial."""
        if len(self.instances) < 2:
            return None
        keys = [i.sort_key for i in self.instances]
        diffs = [abs(b - a) for a, b in zip(keys, keys[1:]) if abs(b - a) > 1e-6]
        if not diffs:
            return None
        return float(np.median(diffs))

    @property
    def is_volume(self) -> bool:
        """True when slices are parallel, evenly spaced and identically sized."""
        if len(self.instances) < 3:
            return False
        g0 = self.instances[0].geometry
        if not g0.valid:
            return False
        for inst in self.instances:
            g = inst.geometry
            if g.rows != g0.rows or g.cols != g0.cols:
                return False
            if abs(float(np.dot(g.normal, g0.normal))) < 0.999:
                return False
        sp = self.slice_spacing
        if not sp:
            return False
        keys = [i.sort_key for i in self.instances]
        diffs = np.abs(np.diff(keys))
        return bool(np.all(np.abs(diffs - sp) < max(0.15 * sp, 0.05)))

    def label(self, veterinary: bool = False) -> str:
        desc = self.description or "(no description)"
        return f"{self.number}: {desc}"

    def default_window(self) -> tuple[float, float] | None:
        """Window centre/width from the DICOM header of the middle slice."""
        inst = self.instances[len(self.instances) // 2]
        c = inst.get("WindowCenter")
        w = inst.get("WindowWidth")
        if c is None or w is None:
            return None
        try:
            if isinstance(c, pydicom.multival.MultiValue):
                c = c[0]
            if isinstance(w, pydicom.multival.MultiValue):
                w = w[0]
            c, w = float(c), float(w)
        except (TypeError, ValueError, IndexError):
            return None
        if w <= 0:
            return None
        return c, w


class Study:
    def __init__(self, uid: str):
        self.uid = uid
        self.series: list[Series] = []

    def finalise(self):
        self.series.sort(key=lambda s: (s.number, s.description))

    @property
    def first_instance(self) -> Instance:
        return self.series[0].first

    def patient_info(self) -> dict:
        i = self.first_instance
        return {
            "name": person_name(i.get("PatientName")),
            "id": fix_text(i.get("PatientID")),
            "sex": str(i.get("PatientSex", "") or ""),
            "birth": format_date(i.get("PatientBirthDate")),
            "age": format_age(i.get("PatientAge")),
            "weight": i.num("PatientWeight"),
            "species": fix_text(i.get("PatientSpeciesDescription")),
            "breed": fix_text(i.get("PatientBreedDescription")),
        }

    def study_info(self) -> dict:
        i = self.first_instance
        return {
            "description": i.text("StudyDescription"),
            "date": format_date(i.get("StudyDate")),
            "time": format_time(i.get("StudyTime")),
            "id": fix_text(i.get("StudyID")),
            "accession": fix_text(i.get("AccessionNumber")),
            "modality": str(i.get("Modality", "") or ""),
            "institution": i.text("InstitutionName"),
            "manufacturer": i.text("Manufacturer"),
            "model": i.text("ManufacturerModelName"),
            "physician": person_name(i.get("ReferringPhysicianName")),
            "body_part": str(i.get("BodyPartExamined", "") or ""),
        }

    @property
    def image_count(self) -> int:
        return sum(len(s) for s in self.series)

    def looks_veterinary(self) -> bool:
        info = self.study_info()
        pat = self.patient_info()
        haystack = " ".join([
            info["institution"], info["manufacturer"], pat["species"],
            pat["breed"], pat["name"],
        ]).upper()
        for kw in ("ANIMAL", "VET", "VETERINAR", "PET ", "CANINE", "FELINE",
                   "동물", "수의"):
            if kw in haystack:
                return True
        i = self.first_instance
        return bool(i.get("PatientSpeciesDescription")
                    or i.get("PatientBreedDescription"))


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------

_SKIP_NAMES = {"dicomdir", "thumbs.db", ".ds_store"}


def _is_candidate(path: str) -> bool:
    name = os.path.basename(path).lower()
    if name in _SKIP_NAMES or name.startswith("."):
        return False
    ext = os.path.splitext(name)[1]
    return ext in ("", ".dcm", ".dic", ".dicom", ".ima", ".img")


def scan_folder(folder: str, progress=None) -> list[Study]:
    """Recursively read a folder and group images into studies and series.

    ``progress`` is called as ``progress(done, total, path)``; returning False
    aborts the scan.
    """
    paths: list[str] = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")
                   and d.lower() != "dicomviewer"]
        for fn in files:
            p = os.path.join(root, fn)
            if _is_candidate(p):
                paths.append(p)
    paths.sort(key=_natural_key)

    studies: dict[str, Study] = {}
    series_map: dict[str, Series] = {}
    total = len(paths)
    for n, path in enumerate(paths):
        if progress is not None and progress(n, total, path) is False:
            break
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        except (InvalidDicomError, OSError, AttributeError, ValueError):
            continue
        if "SOPClassUID" not in ds and "Modality" not in ds:
            continue
        if not ds.get("Rows") or not ds.get("Columns"):
            continue
        inst = Instance(path, ds)
        ser_uid = str(ds.get("SeriesInstanceUID", "") or f"__nouid__{path}")
        ser = series_map.get(ser_uid)
        if ser is None:
            ser = series_map[ser_uid] = Series(ser_uid)
        ser.instances.append(inst)

    for ser in series_map.values():
        if not ser.instances:
            continue
        ser.finalise()
        st_uid = ser.study_uid or "__nostudy__"
        study = studies.get(st_uid)
        if study is None:
            study = studies[st_uid] = Study(st_uid)
        study.series.append(ser)

    out = list(studies.values())
    for s in out:
        s.finalise()
    out.sort(key=lambda s: str(s.first_instance.get("StudyDate", "")), reverse=True)
    if progress is not None:
        progress(total, total, "")
    return out


def _natural_key(path: str):
    """Sort 'img2' before 'img10'."""
    import re
    name = os.path.basename(path)
    parts = re.split(r"(\d+)", name)
    return (os.path.dirname(path),
            [int(p) if p.isdigit() else p.lower() for p in parts])
