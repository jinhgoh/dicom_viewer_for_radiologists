import sys

from .mainwindow import run


def main() -> int:
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    return run(folder)


if __name__ == "__main__":
    raise SystemExit(main())
