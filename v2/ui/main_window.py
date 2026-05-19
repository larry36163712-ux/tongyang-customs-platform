from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from v2.core.backtesting import BacktestAnalyticsService
from v2.core.checking import InvoicePackingChecker
from v2.core.ds2_gateway import Ds2Gateway
from v2.core.models import CheckStatus, ParsedDocument
from v2.core.parser_engine import SemanticParserEngine
from v2.core.print_workflow import RELEASE_METHODS, ImportPrintWorkflow
from v2.core.settings import V2Settings, load_settings, save_settings
from v2.core.template_learning import CustomerTemplateLearningService
from v2.core.updater import UpdateCheck, V2Updater


class CustomsErpWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AI Customs ERP V2")
        self.resize(1280, 820)

        self.settings: V2Settings = load_settings()
        self.parser = SemanticParserEngine()
        self.checker = InvoicePackingChecker(self.parser)
        self.templates = CustomerTemplateLearningService()
        self.analytics = BacktestAnalyticsService(self.templates)
        self.ds2 = Ds2Gateway()
        self.latest_update: UpdateCheck | None = None

        self.nav = QListWidget()
        self.stack = QStackedWidget()
        self.release_group = QButtonGroup(self)
        self.print_status = QLabel()
        self.update_status = QLabel()

        self._build_menu()
        self._build_shell()
        self._apply_theme()

        if self.settings.update.check_on_startup:
            QTimer.singleShot(800, self._check_updates_on_startup)

    def _build_menu(self) -> None:
        version_action = QAction("V2 beta", self)
        version_action.setEnabled(False)
        settings_action = QAction("設定", self)
        settings_action.triggered.connect(self._open_settings_dialog)
        check_update_action = QAction("檢查更新", self)
        check_update_action.triggered.connect(lambda: self._check_updates(interactive=True))
        self.menuBar().addAction(version_action)
        self.menuBar().addAction(settings_action)
        self.menuBar().addAction(check_update_action)

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

        self.stack.addWidget(self._import_check_page())
        self.stack.addWidget(self._review_page("出口核對", "出口核對架構保留，第二階段尚未啟用出口規則。"))
        self.stack.addWidget(self._print_page())
        self.stack.addWidget(self._analytics_page())

        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.nav.setCurrentRow(0)

    def _import_check_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        header = QLabel("進口核對")
        header.setObjectName("PageTitle")
        desc = QLabel("INV vs PKG 語意 parser 與基礎欄位核對。")
        desc.setObjectName("Muted")
        layout.addWidget(header)
        layout.addWidget(desc)

        input_row = QHBoxLayout()
        invoice_text = QTextEdit()
        invoice_text.setPlaceholderText("貼上 INV 文字\nQuantity: 120 PCS\nNet Weight: 400\nAmount: USD 5000")
        packing_text = QTextEdit()
        packing_text.setPlaceholderText("貼上 PKG 文字\nQTY: 120 PCS\nNW: 400\nGW: 450")
        input_row.addWidget(invoice_text)
        input_row.addWidget(packing_text)
        layout.addLayout(input_row)

        action_row = QHBoxLayout()
        run_button = QPushButton("執行核對")
        summary = QLabel("尚未核對")
        summary.setObjectName("StatusNeutral")
        action_row.addWidget(run_button)
        action_row.addWidget(summary, 1)
        layout.addLayout(action_row)

        result_row = QHBoxLayout()
        diff_list = QTextEdit()
        diff_list.setReadOnly(True)
        diff_list.setPlaceholderText("差異列表")
        parser_debug = QTextEdit()
        parser_debug.setReadOnly(True)
        parser_debug.setPlaceholderText("Parser debug")
        result_row.addWidget(diff_list)
        result_row.addWidget(parser_debug)
        layout.addLayout(result_row, 1)

        run_button.clicked.connect(lambda: self._run_import_check(invoice_text, packing_text, summary, diff_list, parser_debug))
        return page

    def _review_page(self, title: str, description: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)
        header = QLabel(title)
        header.setObjectName("PageTitle")
        desc = QLabel(description)
        desc.setObjectName("Muted")
        layout.addWidget(header)
        layout.addWidget(desc)
        layout.addStretch(1)
        return page

    def _print_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        title = QLabel("一鍵印單")
        title.setObjectName("PageTitle")
        note = QLabel("目前只建立進口 workflow UI，不控制印表機。")
        note.setObjectName("Muted")
        layout.addWidget(title)
        layout.addWidget(note)

        method_row = QHBoxLayout()
        for index, method in enumerate(RELEASE_METHODS):
            radio = QRadioButton(method)
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

    def _run_import_check(
        self,
        invoice_text: QTextEdit,
        packing_text: QTextEdit,
        summary: QLabel,
        diff_list: QTextEdit,
        parser_debug: QTextEdit,
    ) -> None:
        report = self.checker.check_texts(invoice_text.toPlainText(), packing_text.toPlainText())
        summary.setText(f"{report.status.value} - {report.summary}")
        summary.setObjectName("StatusOk" if report.status == CheckStatus.MATCH else "StatusFail")
        summary.style().unpolish(summary)
        summary.style().polish(summary)

        diff_lines = ["差異列表:"]
        for result in report.results:
            diff_lines.append(
                f"- {result.status.value} | {result.message} | INV={result.invoice_value or '-'} | PKG={result.packing_value or '-'}"
            )
        diff_list.setText("\n".join(diff_lines))

        parser_debug.setText(
            "\n\n".join(
                (
                    "INV parser debug:\n" + self._format_parsed_document(report.invoice),
                    "PKG parser debug:\n" + self._format_parsed_document(report.packing),
                )
            )
        )

    def _format_parsed_document(self, document: ParsedDocument) -> str:
        lines = [f"type={document.document_type.value}", f"template={document.template_id}"]
        for field in document.fields:
            lines.append(
                f"- {field.canonical.value}: {field.value} | label={field.source_label} | confidence={field.confidence} | evidence={field.evidence}"
            )
        if document.warnings:
            lines.extend(f"warning: {warning}" for warning in document.warnings)
        return "\n".join(lines)

    def _preview_print_workflow(self, steps: QTextEdit) -> None:
        selected = self.release_group.checkedButton()
        method = selected.text() if selected else "C1"
        workflow = ImportPrintWorkflow(method, 1)
        warnings = workflow.validate()
        steps.setText("\n".join(f"{i + 1}. {step}" for i, step in enumerate(workflow.preview_steps())))
        self.print_status.setText(" / ".join(warnings) if warnings else f"已建立 {method} 進口待印流程。")

    def _check_updates_on_startup(self) -> None:
        result = self._check_updates(interactive=False)
        if result and result.status == "available":
            self._prompt_update(result)

    def _check_updates(self, interactive: bool) -> UpdateCheck | None:
        updater = V2Updater(self.settings.version, self.settings.update)
        result = updater.check()
        self.latest_update = result
        if interactive:
            if result.status == "available":
                self._prompt_update(result)
            else:
                QMessageBox.information(self, "更新", result.message)
        return result

    def _prompt_update(self, result: UpdateCheck) -> None:
        if not result.manifest:
            return
        reply = QMessageBox.question(
            self,
            "發現新版",
            f"{result.message}\n\n是否下載並更新？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        apply_result = V2Updater(self.settings.version, self.settings.update).apply(result.manifest)
        QMessageBox.information(self, "更新", apply_result.message)

    def _open_settings_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("設定")
        layout = QVBoxLayout(dialog)

        enabled = QCheckBox("自動更新")
        enabled.setChecked(self.settings.update.enabled)
        startup = QCheckBox("啟動時檢查更新")
        startup.setChecked(self.settings.update.check_on_startup)
        channel = QComboBox()
        channel.addItems(["stable", "beta"])
        channel.setCurrentText(self.settings.update.channel if self.settings.update.channel in {"stable", "beta"} else "stable")

        layout.addWidget(enabled)
        layout.addWidget(startup)
        layout.addWidget(QLabel("更新 channel"))
        layout.addWidget(channel)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.settings.update.enabled = enabled.isChecked()
        self.settings.update.check_on_startup = startup.isChecked()
        self.settings.update.channel = channel.currentText()
        save_settings(self.settings)
        QMessageBox.information(self, "設定", "設定已儲存。")

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
            #StatusOk {
                color: #7DD3A8;
                font-weight: 700;
            }
            #StatusFail {
                color: #F38B8B;
                font-weight: 700;
            }
            #StatusNeutral {
                color: #9DAAB8;
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
            QRadioButton, QCheckBox, QComboBox {
                color: #D9E1EA;
                spacing: 8px;
                padding: 8px 10px;
            }
            QComboBox {
                background: #1A1F26;
                border: 1px solid #2E3642;
                border-radius: 6px;
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
