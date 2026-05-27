from __future__ import annotations

import multiprocessing
import importlib
import json
import os
import sys
import time
from pathlib import Path

from v2.core.runtime_log import log_exception, log_runtime


def _run_runtime_self_test(output_path: str) -> int:
    modules = ["fitz", "pytesseract", "pdf2image", "PIL", "cv2", "numpy", "openpyxl", "pandas"]
    results: dict[str, object] = {
        "executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
        "modules": {},
    }
    ok = True
    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
            results["modules"][module_name] = {
                "ok": True,
                "version": str(getattr(module, "__version__", "")),
            }
        except Exception as exc:
            ok = False
            results["modules"][module_name] = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
    try:
        from v2.ocr import OcrEngine

        available, message = OcrEngine().is_available()
        results["ocr"] = {"available": available, "message": message}
    except Exception as exc:
        ok = False
        results["ocr"] = {"available": False, "message": f"{type(exc).__name__}: {exc}"}
    Path(output_path).write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if ok else 2


def _install_exception_hook() -> None:
    def handle(exc_type, exc, tb) -> None:
        log_runtime("unhandled main-thread exception\n" + "".join(__import__("traceback").format_exception(exc_type, exc, tb)))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = handle


def main() -> int:
    if "--runtime-self-test" in sys.argv:
        index = sys.argv.index("--runtime-self-test")
        output_path = sys.argv[index + 1] if len(sys.argv) > index + 1 else "runtime-self-test.json"
        return _run_runtime_self_test(output_path)

    startup_started = time.perf_counter()
    multiprocessing.freeze_support()
    _install_exception_hook()
    if getattr(sys, "frozen", False):
        try:
            from v2.core.deployment import ensure_runtime_layout

            deployment = ensure_runtime_layout(relaunch=True)
            log_runtime("deployment finalizer " + json.dumps(deployment, ensure_ascii=False, sort_keys=True))
            if deployment.get("relaunching"):
                os._exit(0)
        except Exception as exc:
            log_exception("deployment finalizer failed", exc)
    log_runtime(
        "application startup "
        f"executable={sys.executable} argv={sys.argv} path_entries={len(sys.path)}"
    )
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("通洋報關平台")
    app.setOrganizationName("Tong Yang")

    try:
        from v2.ui.main_window import CustomsErpWindow

        window = CustomsErpWindow()
    except Exception as exc:
        log_exception("main window startup", exc)
        raise
    log_runtime(f"startup timing main_window_ready_ms={(time.perf_counter() - startup_started) * 1000:.0f}")
    window.show()
    log_runtime(f"startup timing shown_ms={(time.perf_counter() - startup_started) * 1000:.0f}")
    exit_code = app.exec()
    log_runtime(f"application exit code={exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
