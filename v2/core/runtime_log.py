from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import sys
import traceback


def runtime_log_path() -> Path:
    try:
        from v2.core.settings import logs_dir

        return logs_dir() / "runtime.log"
    except Exception:
        base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
        path = base / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path / "runtime.log"


def log_runtime(message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    frozen = getattr(sys, "frozen", False)
    meipass = getattr(sys, "_MEIPASS", "")
    line = f"[{stamp}] pid={os.getpid()} frozen={frozen} meipass={meipass} {message}\n"
    path = runtime_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        fallback = Path(os.environ.get("TEMP", str(Path.home()))) / "TongYangCustomsPlatform_runtime.log"
        with fallback.open("a", encoding="utf-8") as handle:
            handle.write(line)


def log_exception(context: str, exc: BaseException | None = None) -> str:
    if exc is None:
        text = traceback.format_exc()
    else:
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log_runtime(f"{context} exception\n{text}")
    return text
