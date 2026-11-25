"""Standalone capture coordinator, dormant until the exact reviewed installation."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    from t02_capture_native_composition import INSTALLED_CAPTURE, start_coordinator

    return 2 if INSTALLED_CAPTURE is None else start_coordinator(INSTALLED_CAPTURE)


if __name__ == "__main__":
    if not sys.flags.isolated or len(sys.argv) != 1:
        raise SystemExit(2)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
