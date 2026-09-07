#!/usr/bin/env python3
"""Launch DicomView.

    python viewer.py [folder]

With no argument the folder containing this script (one level up, where the
DICOM files live) is opened.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dicomview.mainwindow import run


def main() -> int:
    if len(sys.argv) > 1:
        folder = sys.argv[1]
    else:
        folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return run(folder)


if __name__ == "__main__":
    raise SystemExit(main())
