# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules


ROOT = Path.cwd()
datas = []
for source, target in (
    ("config", "config"),
    ("templates", "templates"),
    ("engine", "engine"),
    ("v2", "v2"),
):
    path = ROOT / source
    if path.exists():
        datas.append((str(path), target))

a = Analysis(
    ["v2/main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PIL",
        "pytesseract",
        "fitz",
    ]
    + collect_submodules("engine")
    + collect_submodules("v2")
    + collect_submodules("PIL")
    + collect_submodules("pytesseract")
    + collect_submodules("fitz"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
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
    name="TongYangCustomsPlatform",
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
