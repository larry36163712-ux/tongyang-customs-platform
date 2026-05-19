from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from v2.core.backtesting import BacktestAnalyticsService
from v2.core.ds2_gateway import Ds2Gateway
from v2.core.parser_engine import SemanticParserEngine
from v2.core.print_workflow import RELEASE_METHODS, ImportPrintWorkflow
from v2.core.template_learning import CustomerTemplateLearningService


class CustomsErpWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AI Customs ERP V2")
        self.resize(1280, 820)

        self.parser = SemanticParserEngine()
        self.templates = CustomerTemplateLearningService()
        self.analytics = BacktestAnalyticsService(self.templates)
        self.ds2 = Ds2Gateway()

        self.nav = QListWidget()
        self.stack = QStackedWidget()
        self.release_group = QButtonGroup(self)
        self.print_status = QLabel()

        self._build_menu()
        self._build_shell()
        self._apply_theme()

    def _build_menu(self) -> None:
        version_action = QAction("V2 beta", self)
        version_action.setEnabled(False)
        self.menuBar().addAction(version_action)

    def _build_shell(self) -> None:
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(20, 24, 16, 24)
        sidebar_layout.setSpacing(18)

        brand = QLabel("AI Customs ERP")
        brand.setObjectName("Brand")
        subtitle = QLabel("Tong Yang V2")
        subtitle.setObjectName("Subtitle")
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(subtitle)
        sidebar_layout.addSpacing(12)

        self.nav.setObjectName("Nav")
        for label in ("進口核對", "出口核對", "一鍵印單", "回測分析"):
            item = QListWidgetItem(label)
            item.setSizeHint(item.sizeHint().expandedTo(item.sizeHint()))
            self.nav.addItem(item)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        sidebar_layout.addWidget(self.nav, 1)

        ds2_status = QLabel(self.ds2.status())
        ds2_status.setObjectName("Muted")
        ds2_status.setWordWrap(True)
        sidebar_layout.addWidget(ds2_status)

        self.stack.addWidget(self._review_page("進口核對", "INV / PKG / B/L / 資料清表語意核對"))
        self.stack.addWidget(self._review_page("出口核對", "第一階段只建立入口，出口細節尚未啟用"))
        self.stack.addWidget(self._print_page())
        self.stack.addWidget(self._analytics_page())

        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.nav.setCurrentRow(0)

    def _review_page(self, title: str, description: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        header = QLabel(title)
        header.setObjectName("PageTitle")
        desc = QLabel(description)
        desc.setObjectName("Muted")

        editor = QTextEdit()
        editor.setPlaceholderText("貼上文件文字進行語意 preview，例如 Quantity: 120 PCS")
        editor.setMinimumHeight(220)

        result = QTextEdit()
        result.setReadOnly(True)
        result.setMinimumHeight(220)

        parse_button = QPushButton("語意 preview")
        parse_button.clicked.connect(lambda: self._run_parser_preview(editor, result))

        layout.addWidget(header)
        layout.addWidget(desc)
        layout.addWidget(editor)
        layout.addWidget(parse_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(result)
        return page

    def _print_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        title = QLabel("一鍵印單")
        title.setObjectName("PageTitle")
        note = QLabel("第一階段只建立進口 workflow UI，不控制印表機。")
        note.setObjectName("Muted")
        layout.addWidget(title)
        layout.addWidget(note)

        method_row = QHBoxLayout()
        for index, method in enumerate(RELEASE_METHODS):
            radio = QRadioButton(method)
            radio.setObjectName("Segment")
            self.release_group.addButton(radio)
            method_row.addWidget(radio)
            if index == 0:
                radio.setChecked(True)
        method_row.addStretch(1)
        layout.addLayout(method_row)

        steps = QTextEdit()
        steps.setReadOnly(True)
        workflow = ImportPrintWorkflow("C1", 1)
        steps.setText("\n".join(f"{i + 1}. {step}" for i, step in enumerate(workflow.preview_steps())))
        layout.addWidget(steps)

        preview = QPushButton("建立待印流程")
        preview.clicked.connect(lambda: self._preview_print_workflow(steps))
        layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignLeft)

        self.print_status.setObjectName("Muted")
        layout.addWidget(self.print_status)
        layout.addStretch(1)
        return page

    def _analytics_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        title = QLabel("回測分析中心")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        for index, metric in enumerate(self.analytics.summary_metrics()):
            card = QFrame()
            card.setObjectName("MetricCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 16, 18, 16)
            label = QLabel(metric.label)
            label.setObjectName("Muted")
            value = QLabel(metric.value)
            value.setObjectName("MetricValue")
            trend = QLabel(metric.trend)
            trend.setObjectName("Muted")
            card_layout.addWidget(label)
            card_layout.addWidget(value)
            card_layout.addWidget(trend)
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid)

        profiles = QTextEdit()
        profiles.setReadOnly(True)
        profiles.setText(
            "\n".join(
                f"{p.customer} / {p.supplier} / {p.document_type.value} / samples={p.sample_count} / failures={p.failure_count}"
                for p in self.templates.profiles()
            )
        )
        layout.addWidget(profiles)
        return page

    def _run_parser_preview(self, editor: QTextEdit, result: QTextEdit) -> None:
        parsed = self.parser.parse_preview(editor.toPlainText())
        lines = [
            f"文件類型: {parsed.document_type.value}",
            f"客戶: {parsed.customer}",
            f"供應商: {parsed.supplier}",
            f"模板群組: {parsed.template_id}",
            "",
            "語意欄位:",
        ]
        lines.extend(
            f"- {field.canonical.value}: {field.value} ({field.source_label}, confidence={field.confidence})"
            for field in parsed.fields
        )
        if parsed.warnings:
            lines.append("")
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in parsed.warnings)
        result.setText("\n".join(lines))

    def _preview_print_workflow(self, steps: QTextEdit) -> None:
        selected = self.release_group.checkedButton()
        method = selected.text() if selected else "C1"
        workflow = ImportPrintWorkflow(method, 1)
        warnings = workflow.validate()
        steps.setText("\n".join(f"{i + 1}. {step}" for i, step in enumerate(workflow.preview_steps())))
        self.print_status.setText(" / ".join(warnings) if warnings else f"已建立 {method} 進口待印流程。")

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #111418;
                color: #E8EDF2;
                font-family: "Microsoft JhengHei UI", "Segoe UI";
                font-size: 14px;
            }
            QMenuBar {
                background: #111418;
                color: #9DAAB8;
                border-bottom: 1px solid #252B33;
            }
            #Sidebar {
                min-width: 260px;
                max-width: 260px;
                background: #171B21;
                border-right: 1px solid #252B33;
            }
            #Brand {
                font-size: 22px;
                font-weight: 700;
                color: #F4F7FA;
            }
            #Subtitle, #Muted {
                color: #9DAAB8;
            }
            #PageTitle {
                font-size: 28px;
                font-weight: 700;
                color: #F4F7FA;
            }
            #Nav {
                background: transparent;
                border: 0;
                outline: 0;
            }
            #Nav::item {
                min-height: 44px;
                padding: 8px 12px;
                border-radius: 6px;
                color: #C8D1DA;
            }
            #Nav::item:selected {
                background: #235D74;
                color: #FFFFFF;
            }
            QTextEdit {
                background: #1A1F26;
                border: 1px solid #2E3642;
                border-radius: 6px;
                color: #E8EDF2;
                padding: 10px;
            }
            QPushButton {
                background: #2F7D95;
                color: #FFFFFF;
                border: 0;
                border-radius: 6px;
                padding: 9px 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #3890AB;
            }
            QRadioButton {
                color: #D9E1EA;
                spacing: 8px;
                padding: 8px 10px;
            }
            #MetricCard {
                background: #1A1F26;
                border: 1px solid #2E3642;
                border-radius: 6px;
            }
            #MetricValue {
                font-size: 24px;
                font-weight: 700;
                color: #F4F7FA;
            }
            """
        )

