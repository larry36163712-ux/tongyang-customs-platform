from __future__ import annotations

import ctypes
import os
from pathlib import Path


APP_EXE_NAME = "TongYangCustomsPlatform.exe"


class GUID(ctypes.Structure):
    _fields_ = (
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    )


def _guid(value: str) -> GUID:
    guid = GUID()
    ctypes.oledll.ole32.CLSIDFromString(str(value), ctypes.byref(guid))
    return guid


CLSID_SHELL_LINK = _guid("{00021401-0000-0000-C000-000000000046}")
IID_ISHELL_LINK_W = _guid("{000214F9-0000-0000-C000-000000000046}")
IID_IPERSIST_FILE = _guid("{0000010B-0000-0000-C000-000000000046}")

CLSCTX_INPROC_SERVER = 1
STGM_READ = 0
MAX_PATH = 260


def shortcut_supported() -> bool:
    return os.name == "nt"


def read_shortcut_target(shortcut_path: Path) -> str:
    if os.name != "nt" or not shortcut_path.exists():
        return ""
    shell_link = ctypes.c_void_p()
    initialized = False
    try:
        ctypes.oledll.ole32.CoInitialize(None)
        initialized = True
        _check_hresult(
            ctypes.oledll.ole32.CoCreateInstance(
                ctypes.byref(CLSID_SHELL_LINK),
                None,
                CLSCTX_INPROC_SERVER,
                ctypes.byref(IID_ISHELL_LINK_W),
                ctypes.byref(shell_link),
            )
        )
        persist_file = _query_interface(shell_link, IID_IPERSIST_FILE)
        try:
            _persist_load(persist_file, shortcut_path)
            return _shell_link_get_path(shell_link)
        finally:
            _release(persist_file)
    except Exception:
        return ""
    finally:
        if shell_link:
            _release(shell_link)
        if initialized:
            ctypes.oledll.ole32.CoUninitialize()


def write_shortcut(shortcut_path: Path, target_path: Path, *, working_dir: Path | None = None, icon_path: Path | None = None) -> str:
    if os.name != "nt":
        return ""
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    shell_link = ctypes.c_void_p()
    initialized = False
    try:
        ctypes.oledll.ole32.CoInitialize(None)
        initialized = True
        _check_hresult(
            ctypes.oledll.ole32.CoCreateInstance(
                ctypes.byref(CLSID_SHELL_LINK),
                None,
                CLSCTX_INPROC_SERVER,
                ctypes.byref(IID_ISHELL_LINK_W),
                ctypes.byref(shell_link),
            )
        )
        _shell_link_set_path(shell_link, target_path)
        _shell_link_set_working_directory(shell_link, working_dir or target_path.parent)
        _shell_link_set_icon(shell_link, icon_path or target_path)
        persist_file = _query_interface(shell_link, IID_IPERSIST_FILE)
        try:
            _persist_save(persist_file, shortcut_path)
        finally:
            _release(persist_file)
        return read_shortcut_target(shortcut_path)
    finally:
        if shell_link:
            _release(shell_link)
        if initialized:
            ctypes.oledll.ole32.CoUninitialize()


def looks_related_shortcut(shortcut_path: Path, target_path: str, display_name: str) -> bool:
    target_name = Path(target_path).name if target_path else ""
    base_name = shortcut_path.stem
    return (
        target_name.casefold() == APP_EXE_NAME.casefold()
        or base_name == display_name
        or any(token in base_name.casefold() for token in ("tongyang", "customs"))
        or any(token in base_name for token in ("通洋", "報關", "报关"))
    )


def _query_interface(com_object: ctypes.c_void_p, iid: GUID) -> ctypes.c_void_p:
    target = ctypes.c_void_p()
    vtbl = _vtbl(com_object)
    query_interface = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(vtbl[0])
    _check_hresult(query_interface(com_object, ctypes.byref(iid), ctypes.byref(target)))
    return target


def _persist_load(persist_file: ctypes.c_void_p, shortcut_path: Path) -> None:
    vtbl = _vtbl(persist_file)
    load = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong)(vtbl[5])
    _check_hresult(load(persist_file, str(shortcut_path), STGM_READ))


def _persist_save(persist_file: ctypes.c_void_p, shortcut_path: Path) -> None:
    vtbl = _vtbl(persist_file)
    save = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)(vtbl[6])
    _check_hresult(save(persist_file, str(shortcut_path), 1))


def _shell_link_get_path(shell_link: ctypes.c_void_p) -> str:
    buffer = ctypes.create_unicode_buffer(MAX_PATH)
    vtbl = _vtbl(shell_link)
    get_path = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong)(vtbl[3])
    _check_hresult(get_path(shell_link, buffer, MAX_PATH, None, 0))
    return buffer.value


def _shell_link_set_path(shell_link: ctypes.c_void_p, target_path: Path) -> None:
    vtbl = _vtbl(shell_link)
    set_path = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p)(vtbl[20])
    _check_hresult(set_path(shell_link, str(target_path)))


def _shell_link_set_working_directory(shell_link: ctypes.c_void_p, working_dir: Path) -> None:
    vtbl = _vtbl(shell_link)
    set_working_directory = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p)(vtbl[9])
    _check_hresult(set_working_directory(shell_link, str(working_dir)))


def _shell_link_set_icon(shell_link: ctypes.c_void_p, icon_path: Path) -> None:
    vtbl = _vtbl(shell_link)
    set_icon_location = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)(vtbl[17])
    _check_hresult(set_icon_location(shell_link, str(icon_path), 0))


def _release(com_object: ctypes.c_void_p) -> None:
    vtbl = _vtbl(com_object)
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
    release(com_object)


def _vtbl(com_object: ctypes.c_void_p):
    return ctypes.cast(com_object, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents


def _check_hresult(result: int) -> None:
    if result < 0:
        raise OSError(result, f"Windows shortcut COM call failed: HRESULT 0x{result & 0xFFFFFFFF:08X}")
