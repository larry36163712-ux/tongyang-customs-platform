from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from v2.core.runtime_log import log_runtime


CJK_FONT_STACK = (
    '"Noto Sans TC", "Microsoft JhengHei UI", "Microsoft JhengHei", '
    '"PMingLiU", "MingLiU", "Segoe UI"'
)


@dataclass(frozen=True)
class FontBootstrapResult:
    family: str
    source: str
    loaded_files: tuple[str, ...]


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def _candidate_font_files() -> list[Path]:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    runtime_root = _runtime_root()
    app_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else runtime_root
    font_names = [
        "NotoSansTC-VF.ttf",
        "NotoSansTC-Regular.ttf",
        "NotoSansTC-Regular.otf",
        "NotoSansCJKtc-Regular.otf",
        "msjh.ttc",
        "msjhbd.ttc",
        "msjhl.ttc",
        "mingliu.ttc",
        "mingliub.ttc",
        "kaiu.ttf",
    ]
    roots = [
        runtime_root / "assets" / "fonts",
        app_root / "assets" / "fonts",
        windir / "Fonts",
    ]
    candidates: list[Path] = []
    for root in roots:
        for name in font_names:
            candidates.append(root / name)
    return candidates


def install_cjk_font(app: QApplication) -> FontBootstrapResult:
    loaded_files: list[str] = []
    preferred_families = [
        "Noto Sans TC",
        "Microsoft JhengHei UI",
        "Microsoft JhengHei",
        "PMingLiU",
        "MingLiU",
        "Segoe UI",
    ]

    for font_file in _candidate_font_files():
        if not font_file.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        if font_id < 0:
            continue
        loaded_files.append(str(font_file))

    available = set(QFontDatabase.families())
    chosen = next((family for family in preferred_families if family in available), "Segoe UI")
    app.setFont(QFont(chosen, 10))
    log_runtime(
        "qt cjk font bootstrap "
        f"family={chosen} loaded_files={loaded_files} available_families={len(available)}"
    )
    source = "application/system font file" if loaded_files else "qt fallback"
    return FontBootstrapResult(family=chosen, source=source, loaded_files=tuple(loaded_files))
