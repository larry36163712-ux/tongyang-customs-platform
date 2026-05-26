from __future__ import annotations

import multiprocessing
import sys

from PySide6.QtWidgets import QApplication

from v2.core.runtime_log import log_exception, log_runtime
from v2.ui.main_window import CustomsErpWindow


def _install_exception_hook() -> None:
    def handle(exc_type, exc, tb) -> None:
        log_runtime("unhandled main-thread exception\n" + "".join(__import__("traceback").format_exception(exc_type, exc, tb)))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = handle


def main() -> int:
    multiprocessing.freeze_support()
    _install_exception_hook()
    log_runtime(
        "application startup "
        f"executable={sys.executable} argv={sys.argv} path_entries={len(sys.path)}"
    )
    app = QApplication(sys.argv)
    app.setApplicationName("通洋報關平台")
    app.setOrganizationName("Tong Yang")

    try:
        window = CustomsErpWindow()
    except Exception as exc:
        log_exception("main window startup", exc)
        raise
    window.show()
    exit_code = app.exec()
    log_runtime(f"application exit code={exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
