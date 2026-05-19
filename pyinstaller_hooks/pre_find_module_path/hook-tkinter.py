from __future__ import annotations

import sys
from pathlib import Path


def pre_find_module_path(hook_api):
    tkinter_dir = Path(sys.base_prefix) / "Lib" / "tkinter"
    if tkinter_dir.exists():
        hook_api.search_dirs = [str(tkinter_dir.parent)]
