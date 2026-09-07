"""Persistence: annotation store, user presets and window state."""
from __future__ import annotations

import json
import os
import time

from .measure import Annotation

STORE_DIRNAME = ".dicomview"
ANNOTATION_FILE = "annotations.json"
FORMAT_VERSION = 1


class AnnotationStore:
    """Annotations keyed by (SeriesInstanceUID, SOPInstanceUID)."""

    def __init__(self):
        self._by_image: dict[tuple[str, str], list[Annotation]] = {}
        self.dirty = False
        self.path: str | None = None

    # -- access ------------------------------------------------------------
    def get(self, series_uid: str, sop_uid: str) -> list[Annotation]:
        return self._by_image.get((series_uid, sop_uid), [])

    def add(self, series_uid: str, sop_uid: str, ann: Annotation):
        ann.series_uid = series_uid
        ann.sop_uid = sop_uid
        self._by_image.setdefault((series_uid, sop_uid), []).append(ann)
        self.dirty = True

    def remove(self, ann: Annotation):
        key = (ann.series_uid, ann.sop_uid)
        lst = self._by_image.get(key)
        if lst and ann in lst:
            lst.remove(ann)
            self.dirty = True
            return True
        return False

    def clear_image(self, series_uid: str, sop_uid: str):
        if self._by_image.pop((series_uid, sop_uid), None) is not None:
            self.dirty = True

    def clear_series(self, series_uid: str):
        keys = [k for k in self._by_image if k[0] == series_uid]
        for k in keys:
            del self._by_image[k]
        if keys:
            self.dirty = True

    def clear_all(self):
        if self._by_image:
            self._by_image.clear()
            self.dirty = True

    def all_items(self):
        """Yield (series_uid, sop_uid, annotation) for every annotation."""
        for (ser, sop), lst in self._by_image.items():
            for ann in lst:
                yield ser, sop, ann

    def count(self) -> int:
        return sum(len(v) for v in self._by_image.values())

    def count_for_series(self, series_uid: str) -> int:
        return sum(len(v) for k, v in self._by_image.items() if k[0] == series_uid)

    # -- persistence -------------------------------------------------------
    @staticmethod
    def default_path(folder: str) -> str:
        return os.path.join(folder, STORE_DIRNAME, ANNOTATION_FILE)

    def to_json(self) -> dict:
        return {
            "format": "dicomview-annotations",
            "version": FORMAT_VERSION,
            "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
            "annotations": [a.to_dict() for _, _, a in self.all_items()],
        }

    def save(self, path: str | None = None) -> str:
        path = path or self.path
        if not path:
            raise ValueError("no annotation path set")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.to_json(), fh, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
        self.path = path
        self.dirty = False
        return path

    def load(self, path: str, merge: bool = False) -> int:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not merge:
            self._by_image.clear()
        n = 0
        for d in data.get("annotations", []):
            ann = Annotation.from_dict(d)
            if ann is None:
                continue
            self._by_image.setdefault((ann.series_uid, ann.sop_uid), []).append(ann)
            n += 1
        self.path = path
        self.dirty = merge and n > 0
        return n


# --------------------------------------------------------------------------
# application settings (window presets, preferences)
# --------------------------------------------------------------------------

def config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "DicomView")
    os.makedirs(d, exist_ok=True)
    return d


class Settings:
    def __init__(self):
        self.path = os.path.join(config_dir(), "settings.json")
        self.data = {
            "user_presets": [],          # [{name, center, width}]
            "recent_folders": [],
            "veterinary_labels": None,   # None = auto-detect per study
            "show_overlay": True,
            "show_reference_lines": True,
            "smooth": True,
            "annotation_color": "#00e5ff",
        }
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                self.data.update(json.load(fh))
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=1, ensure_ascii=False)
        except OSError:
            pass

    def __getitem__(self, key):
        return self.data.get(key)

    def __setitem__(self, key, value):
        self.data[key] = value

    def add_recent(self, folder: str):
        recent = [f for f in self.data.get("recent_folders", [])
                  if os.path.normcase(f) != os.path.normcase(folder)]
        recent.insert(0, folder)
        self.data["recent_folders"] = recent[:10]
        self.save()

    def add_preset(self, name: str, center: float, width: float):
        presets = [p for p in self.data.get("user_presets", [])
                   if p.get("name") != name]
        presets.append({"name": name, "center": center, "width": width})
        self.data["user_presets"] = presets
        self.save()

    def remove_preset(self, name: str):
        self.data["user_presets"] = [p for p in self.data.get("user_presets", [])
                                     if p.get("name") != name]
        self.save()
