# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


ROOT = Path.cwd()
SOURCE = ROOT / "source"
VERSION_FILE = ROOT / "version_info.txt"
payload = ROOT / "installer_payload"
datas = []
for name in ("TongYangCustomsPlatform.exe", "version.json", "SHA256.txt"):
    path = payload / name
    if path.exists():
        datas.append((str(path), "payload"))


a = Analysis(
    ["source/scripts/installer_stub.py"],
    pathex=[str(SOURCE), str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
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
    name="TongYangCustomsPlatform_Setup",
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
    version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
    uac_admin=True,
)
