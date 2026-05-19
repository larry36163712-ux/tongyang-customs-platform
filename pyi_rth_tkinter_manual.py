from __future__ import annotations

import os
import sys
from pathlib import Path


if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    os.environ.setdefault("TCL_LIBRARY", str(base / "_tcl_data"))
    os.environ.setdefault("TK_LIBRARY", str(base / "_tk_data"))
