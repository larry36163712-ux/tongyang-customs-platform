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


def safe_collect_submodules(package):
    try:
        return collect_submodules(
            package,
            filter=lambda name: (
                ".tests" not in name
                and ".testing" not in name
                and not name.endswith(".tests")
                and not name.endswith(".conftest")
                and ".conftest" not in name
            ),
        )
    except Exception:
        return []


runtime_packages = [
    "PIL",
    "pytesseract",
    "fitz",
    "pdf2image",
    "cv2",
    "numpy",
    "openpyxl",
    "pandas",
]

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
        "pdf2image",
        "cv2",
        "numpy",
        "openpyxl",
        "pandas",
    ]
    + safe_collect_submodules("engine")
    + safe_collect_submodules("v2")
    + [module for package in runtime_packages for module in safe_collect_submodules(package)],
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
