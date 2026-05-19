# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path


ROOT = Path.cwd()
HOOKS = ROOT / "pyinstaller_hooks"
PYTHON_ROOT = Path(sys.base_prefix)
PYTHON_DLLS = PYTHON_ROOT / "DLLs"
PYTHON_TCL = PYTHON_ROOT / "tcl"
PYTHON_TKINTER = PYTHON_ROOT / "Lib" / "tkinter"

os.environ["TCL_LIBRARY"] = str(PYTHON_TCL / "tcl8.6")
os.environ["TK_LIBRARY"] = str(PYTHON_TCL / "tk8.6")


a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[
        (str(PYTHON_DLLS / "_tkinter.pyd"), "."),
        (str(PYTHON_DLLS / "tcl86t.dll"), "."),
        (str(PYTHON_DLLS / "tk86t.dll"), "."),
    ],
    datas=[
        ("settings.json", "."),
        ("version.json", "."),
        ("app/parser/templates", "app/parser/templates"),
        ("config", "config"),
        ("templates", "templates"),
        (str(PYTHON_TCL / "tcl8.6"), "_tcl_data"),
        (str(PYTHON_TCL / "tk8.6"), "_tk_data"),
        (str(PYTHON_TCL / "tcl8"), "_tcl_data/tcl8"),
    ],
    hiddenimports=[
        "_tkinter",
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.scrolledtext",
    ],
    hookspath=[str(HOOKS)],
    hooksconfig={},
    runtime_hooks=["pyi_rth_runtime_layout.py", "pyi_rth_tkinter_manual.py"],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="通洋報關平台",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
