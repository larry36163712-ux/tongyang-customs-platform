from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from v2.ui.main_window import CustomsErpWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AI Customs ERP V2")
    app.setOrganizationName("Tong Yang")

    window = CustomsErpWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

