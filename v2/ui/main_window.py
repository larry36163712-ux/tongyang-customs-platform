from __future__ import annotations

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QApplication,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from v2.core.backtesting import BacktestAnalyticsService
from v2.core.checking import DeclarationDocumentChecker
from v2.core.document_loader import DocumentLoader, LoadedDocument
from v2.core.ds2_gateway import Ds2Gateway
from v2.core.models import CheckStatus, DocumentType, ParsedDocument
from v2.core.parser_engine import SemanticParserEngine
from v2.core.print_workflow import RELEASE_METHODS, ImportPrintWorkflow
from v2.core.settings import V2Settings, load_settings, logs_dir, resolve_local_version, save_settings
from v2.core.template_learning import CustomerTemplateLearningService
from v2.core.updater import UpdateCheck, V2Updater


DOCUMENT_LABELS = {
    DocumentType.DS2_DECLARATION: "DS2 報單",
    DocumentType.INVOICE: "INV",
    DocumentType.PACKING_LIST: "PKG",
    DocumentType.BILL_OF_LADING: "B/L",
    DocumentType.ARRIVAL_NOTICE: "到貨通知",
    DocumentType.CLEARANCE_LIST: "清表",
    DocumentType.DATA_CLEARANCE: "資料清表",
    DocumentType.MATERIAL_CLEARANCE: "用料清表",
    DocumentType.DRAWBACK_CLEARANCE: "核退清表",
    DocumentType.UNKNOWN: "未知文件",
}

STATUS_LABELS = {
    CheckStatus.MATCH: "一致",
    CheckStatus.MISMATCH: "不一致",
    CheckStatus.MISSING: "缺少欄位",
    CheckStatus.HIGH_RISK: "高風險 warning",
}

FIELD_LABELS = {
    "quantity": "數量",
    "package_count": "件數",
    "unit": "單位",
    "item_no": "項次",
    "description": "品名",
    "gross_weight": "毛重",
    "net_weight": "淨重",
    "amount": "金額",
    "currency": "幣別",
    "hs_code": "稅則",
    "port": "港口",
    "container_no": "櫃號",
    "seal_no": "封條",
    "vessel_voyage": "船名航次",
    "origin": "產地",
    "customer": "客戶",
    "supplier": "供應商",
}


class DocumentDropList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("UploadList")

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class ToastNotification(QFrame):
    action_clicked = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setFixedWidth(360)
        self.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self.title = QLabel()
        self.title.setObjectName("ToastTitle")
        self.title.setWordWrap(True)
        self.message = QLabel()
        self.message.setObjectName("ToastMessage")
        self.message.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setObjectName("ToastProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        self.action = QPushButton("立即更新")
        self.action.setObjectName("ToastAction")
        self.action.clicked.connect(self.action_clicked.emit)

        layout.addWidget(self.title)
        layout.addWidget(self.message)
        layout.addWidget(self.progress)
        layout.addWidget(self.action, 0, Qt.AlignmentFlag.AlignRight)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, title: str, message: str, *, action_visible: bool = False, timeout_ms: int = 6000) -> None:
        self.title.setText(title)
        self.message.setText(message)
        self.action.setVisible(action_visible)
        self.action.setEnabled(True)
        self.progress.hide()
        self.progress.setValue(0)
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        if timeout_ms > 0:
            self._timer.start(timeout_ms)

    def set_progress(self, title: str, message: str, percent: int) -> None:
        self.title.setText(title)
        self.message.setText(message)
        self.action.setVisible(False)
        self.progress.show()
        self.progress.setValue(max(0, min(100, percent)))
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if not parent:
            return
        margin = 24
        x = parent.width() - self.width() - margin
        y = parent.height() - self.height() - margin
        self.move(max(margin, x), max(margin, y))


class UpdateApplyWorker(QObject):
    progress = Signal(str, int, str)
    finished = Signal(object)

    def __init__(self, version: str, settings: object, manifest: object) -> None:
        super().__init__()
        self.version = version
        self.settings = settings
        self.manifest = manifest

    @Slot()
    def run(self) -> None:
        result = V2Updater(self.version, self.settings).apply(
            self.manifest,
            progress=lambda stage, percent, message: self.progress.emit(stage, percent, message),
        )
        self.finished.emit(result)


class CustomsErpWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("通洋報關平台")
        self.resize(1320, 860)

        self.settings: V2Settings = load_settings()
        self.parser = SemanticParserEngine()
        self.loader = DocumentLoader(self.parser)
        self.checker = DeclarationDocumentChecker(self.parser)
        self.templates = CustomerTemplateLearningService()
        self.analytics = BacktestAnalyticsService(self.templates)
        self.ds2 = Ds2Gateway()
        self.latest_update: UpdateCheck | None = None

        self.nav = QListWidget()
        self.stack = QStackedWidget()
        self.release_group = QButtonGroup(self)
        self.print_status = QLabel()
        self.loaded_documents: list[LoadedDocument] = []

        self.status_dot = QLabel()
        self.status_channel = QLabel()
        self.status_version = QLabel()
        self.status_update = QLabel()
        self.toast: ToastNotification | None = None
        self.update_thread: QThread | None = None
        self.update_worker: UpdateApplyWorker | None = None

        self._build_menu()
        self._build_shell()
        self._apply_theme()
        self._set_update_status("尚未檢查更新", "neutral")

        if self.settings.update.check_on_startup:
            QTimer.singleShot(800, self._check_updates_on_startup)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self.toast and self.toast.isVisible():
            self.toast._reposition()

    def _build_menu(self) -> None:
        settings_action = QAction("設定", self)
        settings_action.triggered.connect(self._open_settings_dialog)
        check_update_action = QAction("檢查更新", self)
        check_update_action.triggered.connect(lambda: self._check_updates(interactive=True))
        self.menuBar().addAction(settings_action)
        self.menuBar().addAction(check_update_action)

    def _build_shell(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        body = QWidget()
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = self._build_sidebar()
        self.stack.addWidget(self._import_check_page())
        self.stack.addWidget(self._review_page("出口核對", "出口文件 workflow 已預留，後續階段接入 DS2 與出口文件比對。"))
        self.stack.addWidget(self._print_page())
        self.stack.addWidget(self._analytics_page())

        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)

        root_layout.addWidget(body, 1)
        root_layout.addWidget(self._build_global_status_bar())
        self.setCentralWidget(root)

        self.toast = ToastNotification(root)
        self.toast.action.clicked.connect(self._apply_latest_update)
        self.nav.setCurrentRow(0)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(22, 26, 18, 22)
        sidebar_layout.setSpacing(18)

        brand = QLabel("通洋報關平台")
        brand.setObjectName("Brand")
        subtitle = QLabel("AI Customs ERP")
        subtitle.setObjectName("Subtitle")
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(subtitle)
        sidebar_layout.addSpacing(10)

        self.nav.setObjectName("Nav")
        for label in ("進口核對", "出口核對", "一鍵印單", "回測分析"):
            item = QListWidgetItem(label)
            item.setSizeHint(item.sizeHint().expandedTo(item.sizeHint()))
            self.nav.addItem(item)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        sidebar_layout.addWidget(self.nav, 1)

        ds2_status = QLabel(self.ds2.status())
        ds2_status.setObjectName("SidebarNote")
        ds2_status.setWordWrap(True)
        sidebar_layout.addWidget(ds2_status)
        return sidebar

    def _build_global_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("GlobalStatusBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(8)

        channel = self.settings.update.channel.title()
        self.status_dot.setText("●")
        self.status_dot.setObjectName("StatusDot")
        self.status_channel.setText(channel)
        self.status_channel.setObjectName("StatusChannel")
        self.status_version.setText(self.settings.version)
        self.status_version.setObjectName("StatusVersion")
        self.status_update.setObjectName("StatusMessage")

        layout.addWidget(self.status_dot)
        layout.addWidget(self.status_channel)
        layout.addWidget(self.status_version)
        layout.addSpacing(14)
        layout.addWidget(self.status_update)
        layout.addStretch(1)
        return bar

    def _import_check_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(18)

        header = QLabel("進口核對")
        header.setObjectName("PageTitle")
        desc = QLabel("以 DS2 報單為核心，比對 INV / PKG / B/L / 到貨通知 / 清表。")
        desc.setObjectName("PageDescription")
        layout.addWidget(header)
        layout.addWidget(desc)

        upload_card = QFrame()
        upload_card.setObjectName("Panel")
        upload_card_layout = QVBoxLayout(upload_card)
        upload_card_layout.setContentsMargins(18, 18, 18, 18)
        upload_card_layout.setSpacing(14)

        section_title = QLabel("文件上傳")
        section_title.setObjectName("SectionTitle")
        upload_card_layout.addWidget(section_title)

        upload_row = QHBoxLayout()
        upload_row.setSpacing(16)
        upload_list = DocumentDropList()
        upload_list.setMinimumHeight(190)
        self._set_upload_placeholder(upload_list)

        upload_actions = QVBoxLayout()
        upload_actions.setSpacing(10)
        choose_button = QPushButton("選擇檔案")
        clear_button = QPushButton("清除文件")
        clear_button.setObjectName("SecondaryButton")
        upload_hint = QLabel("支援 PDF / TXT / CSV / TSV")
        upload_hint.setObjectName("Hint")
        upload_actions.addWidget(choose_button)
        upload_actions.addWidget(clear_button)
        upload_actions.addWidget(upload_hint)
        upload_actions.addStretch(1)
        upload_row.addWidget(upload_list, 1)
        upload_row.addLayout(upload_actions)
        upload_card_layout.addLayout(upload_row)
        layout.addWidget(upload_card)

        action_row = QHBoxLayout()
        run_button = QPushButton("開始核對")
        summary = QLabel("等待文件")
        summary.setObjectName("StatusNeutral")
        action_row.addWidget(run_button)
        action_row.addWidget(summary, 1)
        layout.addLayout(action_row)

        result_row = QHBoxLayout()
        result_row.setSpacing(16)
        diff_list = QTextEdit()
        diff_list.setReadOnly(True)
        diff_list.setObjectName("ResultBox")
        diff_list.setPlaceholderText("核對結果會顯示在這裡")
        parser_debug = QTextEdit()
        parser_debug.setReadOnly(True)
        parser_debug.setObjectName("DebugBox")
        parser_debug.setPlaceholderText("Parser debug")
        result_row.addWidget(diff_list)
        result_row.addWidget(parser_debug)
        layout.addLayout(result_row, 1)

        upload_list.files_dropped.connect(lambda paths: self._add_documents(paths, upload_list, upload_hint, parser_debug))
        choose_button.clicked.connect(lambda: self._choose_documents(upload_list, upload_hint, parser_debug))
        clear_button.clicked.connect(lambda: self._clear_documents(upload_list, upload_hint, diff_list, parser_debug, summary))
        run_button.clicked.connect(lambda: self._run_import_check(summary, diff_list, parser_debug))
        return page

    def _review_page(self, title: str, description: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(18)
        header = QLabel(title)
        header.setObjectName("PageTitle")
        desc = QLabel(description)
        desc.setObjectName("PageDescription")
        layout.addWidget(header)
        layout.addWidget(desc)
        layout.addStretch(1)
        return page

    def _print_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(18)

        title = QLabel("一鍵印單")
        title.setObjectName("PageTitle")
        note = QLabel("目前建立進口印單 workflow，不控制印表機；請手動選擇 C1 / C2 / C3M / C3X。")
        note.setObjectName("PageDescription")
        layout.addWidget(title)
        layout.addWidget(note)

        method_row = QHBoxLayout()
        method_row.setSpacing(12)
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

        preview = QPushButton("產生流程預覽")
        preview.clicked.connect(lambda: self._preview_print_workflow(steps))
        layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignLeft)

        self.print_status.setObjectName("Hint")
        layout.addWidget(self.print_status)
        layout.addStretch(1)
        return page

    def _analytics_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(18)

        title = QLabel("回測分析")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        for index, metric in enumerate(self.analytics.summary_metrics()):
            card = QFrame()
            card.setObjectName("MetricCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 16, 18, 16)
            card_layout.setSpacing(8)
            label = QLabel(metric.label)
            label.setObjectName("Hint")
            value = QLabel(metric.value)
            value.setObjectName("MetricValue")
            trend = QLabel(metric.trend)
            trend.setObjectName("Hint")
            card_layout.addWidget(label)
            card_layout.addWidget(value)
            card_layout.addWidget(trend)
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid)

        profiles = QTextEdit()
        profiles.setReadOnly(True)
        profiles.setText(
            "\n".join(
                f"{p.customer} / {p.supplier} / {self._document_label(p.document_type)} / samples={p.sample_count} / failures={p.failure_count}"
                for p in self.templates.profiles()
            )
        )
        layout.addWidget(profiles)
        return page

    def _run_import_check(
        self,
        summary: QLabel,
        diff_list: QTextEdit,
        parser_debug: QTextEdit,
    ) -> None:
        report = self.checker.check_documents([item.parsed for item in self.loaded_documents])
        status_text = self._status_label(report.status)
        summary.setText(f"{status_text} - {report.summary}")
        summary.setObjectName("StatusOk" if report.status == CheckStatus.MATCH else "StatusFail")
        summary.style().unpolish(summary)
        summary.style().polish(summary)

        diff_lines = ["核對結果"]
        if report.high_risk_warnings:
            diff_lines.append("")
            diff_lines.append("高風險 warning")
            diff_lines.extend(f"- {warning}" for warning in report.high_risk_warnings)
            diff_lines.append("")
        for result in report.results:
            values = " | ".join(f"{name}={value}" for name, value in result.document_values.items()) or "-"
            diff_lines.append(
                f"- {self._status_label(result.status)} | {result.message} | DS2={result.declaration_value or '-'} | 文件={values}"
            )
        diff_list.setText("\n".join(diff_lines))
        parser_debug.setText(self._format_debug_documents([item.parsed for item in self.loaded_documents]))

    def _choose_documents(self, upload_list: DocumentDropList, upload_hint: QLabel, parser_debug: QTextEdit) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "選擇核對文件",
            "",
            "Documents (*.pdf *.txt *.csv *.tsv);;All Files (*.*)",
        )
        if paths:
            self._add_documents(paths, upload_list, upload_hint, parser_debug)

    def _add_documents(
        self,
        paths: list[str],
        upload_list: DocumentDropList,
        upload_hint: QLabel,
        parser_debug: QTextEdit,
    ) -> None:
        loaded = self.loader.load_paths(paths)
        existing = {str(item.path) for item in self.loaded_documents}
        self.loaded_documents.extend(item for item in loaded if str(item.path) not in existing)
        self._refresh_upload_list(upload_list, upload_hint)
        parser_debug.setText(self._format_debug_documents([item.parsed for item in self.loaded_documents]))

    def _clear_documents(
        self,
        upload_list: DocumentDropList,
        upload_hint: QLabel,
        diff_list: QTextEdit,
        parser_debug: QTextEdit,
        summary: QLabel,
    ) -> None:
        self.loaded_documents.clear()
        upload_list.clear()
        self._set_upload_placeholder(upload_list)
        upload_hint.setText("支援 PDF / TXT / CSV / TSV")
        diff_list.clear()
        parser_debug.clear()
        summary.setText("等待文件")
        summary.setObjectName("StatusNeutral")
        summary.style().unpolish(summary)
        summary.style().polish(summary)

    def _refresh_upload_list(self, upload_list: DocumentDropList, upload_hint: QLabel) -> None:
        upload_list.clear()
        for item in self.loaded_documents:
            upload_list.addItem(
                f"{self._document_label(item.parsed.document_type)} | {item.path.name} | fields={len(item.parsed.fields)}"
            )
        upload_hint.setText(f"已載入 {len(self.loaded_documents)} 份文件")

    def _set_upload_placeholder(self, upload_list: QListWidget) -> None:
        upload_list.addItem("拖曳 DS2 報單 / INV / PKG / B/L / 到貨通知 / 清表到這裡")
        upload_list.addItem("或使用右側按鈕選擇檔案")

    def _format_debug_documents(self, documents: list[ParsedDocument]) -> str:
        if not documents:
            return "尚未載入文件。"
        return "\n\n".join(self._format_parsed_document(document) for document in documents)

    def _format_parsed_document(self, document: ParsedDocument) -> str:
        lines = [
            f"source={document.source_name or '-'}",
            f"type={self._document_label(document.document_type)}",
            f"template={document.template_id}",
        ]
        for field in document.fields:
            label = FIELD_LABELS.get(field.canonical.value, field.canonical.value)
            lines.append(
                f"- {label}: {field.value} | label={field.source_label} | confidence={field.confidence} | evidence={field.evidence}"
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
        if result and result.should_show_popup:
            self._show_update_toast(result)

    def _check_updates(self, interactive: bool) -> UpdateCheck | None:
        updater = V2Updater(self.settings.version, self.settings.update)
        result = updater.check()
        self.latest_update = result
        self._sync_update_status(result)
        if result.should_show_popup:
            self._show_update_toast(result)
        elif interactive:
            self._show_toast("更新狀態", result.message, action_visible=False, timeout_ms=4200)
        return result

    def _show_update_toast(self, result: UpdateCheck) -> None:
        if not result.manifest:
            return
        self._show_toast("新版本可用", result.manifest.version, action_visible=True, timeout_ms=0)

    def _show_toast(self, title: str, message: str, *, action_visible: bool, timeout_ms: int) -> None:
        if self.toast:
            self.toast.show_message(title, message, action_visible=action_visible, timeout_ms=timeout_ms)

    def _apply_latest_update(self) -> None:
        if not self.latest_update or not self.latest_update.manifest:
            self._show_toast("更新狀態", "目前沒有可套用的新版資訊，請重新檢查更新。", action_visible=False, timeout_ms=5000)
            return
        if self.update_thread and self.update_thread.isRunning():
            self._show_toast("正在更新", "更新流程正在執行中。", action_visible=False, timeout_ms=3000)
            return
        self._write_update_progress("ui update button clicked")
        self._set_update_status("正在下載新版...", "available")
        if self.toast:
            self.toast.set_progress("正在更新", "downloading", 0)

        self.update_thread = QThread(self)
        self.update_worker = UpdateApplyWorker(self.settings.version, self.settings.update, self.latest_update.manifest)
        self.update_worker.moveToThread(self.update_thread)
        self.update_thread.started.connect(self.update_worker.run)
        self.update_worker.progress.connect(self._on_update_progress)
        self.update_worker.finished.connect(self._on_update_finished)
        self.update_worker.finished.connect(self.update_thread.quit)
        self.update_worker.finished.connect(self.update_worker.deleteLater)
        self.update_thread.finished.connect(self.update_thread.deleteLater)
        self.update_thread.finished.connect(self._clear_update_worker)
        self.update_thread.start()

    @Slot(str, int, str)
    def _on_update_progress(self, stage: str, percent: int, message: str) -> None:
        stage_labels = {
            "downloading": "downloading",
            "verifying": "verifying",
            "replacing": "replacing",
            "restarting": "restarting",
        }
        label = stage_labels.get(stage, stage)
        self._set_update_status(label, "available")
        if self.toast:
            self.toast.set_progress("正在更新", f"{label} - {message}", percent)

    @Slot(object)
    def _on_update_finished(self, apply_result: UpdateCheck) -> None:
        self.settings.version = resolve_local_version(self.settings.version)
        state = "available" if apply_result.status != "error" else "neutral"
        self._set_update_status(apply_result.message, state)
        self._show_toast("更新狀態", apply_result.message, action_visible=False, timeout_ms=5000)

    @Slot()
    def _clear_update_worker(self) -> None:
        self.update_thread = None
        self.update_worker = None

    def _sync_update_status(self, result: UpdateCheck) -> None:
        if result.should_show_popup:
            remote = result.manifest.version if result.manifest else ""
            self._set_update_status(f"發現新版本 {remote}", "available")
        elif result.status == "current":
            self._set_update_status("已是最新版本", "current")
        elif result.status == "disabled":
            self._set_update_status("自動更新已停用", "neutral")
        else:
            self._set_update_status(result.message, "neutral")

    def _set_update_status(self, text: str, state: str) -> None:
        self.settings.version = resolve_local_version(self.settings.version)
        self.status_channel.setText(self.settings.update.channel.title())
        self.status_version.setText(self.settings.version)
        self.status_update.setText(text)
        self.status_dot.setProperty("state", state)
        self.status_update.setProperty("state", state)
        for widget in (self.status_dot, self.status_update):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _write_update_progress(self, message: str) -> None:
        path = logs_dir() / "update-debug.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[UI] {message}\n")

    def _open_settings_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("設定")
        dialog.setObjectName("SettingsDialog")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        enabled = QCheckBox("啟用自動更新")
        enabled.setChecked(self.settings.update.enabled)
        startup = QCheckBox("啟動時檢查更新")
        startup.setChecked(self.settings.update.check_on_startup)
        channel = QComboBox()
        channel.addItems(["dev", "stable"])
        channel.setCurrentText(self.settings.update.channel if self.settings.update.channel in {"dev", "stable"} else "stable")

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
        self._set_update_status("設定已儲存", "neutral")
        QMessageBox.information(self, "設定", "設定已儲存。")

    def _document_label(self, document_type: DocumentType) -> str:
        return DOCUMENT_LABELS.get(document_type, document_type.value)

    def _status_label(self, status: CheckStatus) -> str:
        return STATUS_LABELS.get(status, status.value)

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #0F1318;
                color: #E7EDF3;
                font-family: "Microsoft JhengHei UI", "Segoe UI";
                font-size: 14px;
            }
            QMenuBar {
                background: #0F1318;
                color: #A8B4C2;
                border-bottom: 1px solid #202832;
                padding: 4px 10px;
            }
            QMenuBar::item {
                padding: 7px 12px;
                border-radius: 6px;
            }
            QMenuBar::item:selected {
                background: #1B2530;
                color: #FFFFFF;
            }
            #Sidebar {
                min-width: 268px;
                max-width: 268px;
                background: #121820;
                border-right: 1px solid #25303B;
            }
            #Brand {
                font-size: 22px;
                font-weight: 700;
                color: #F7FAFC;
            }
            #Subtitle {
                color: #8290A2;
                font-size: 12px;
                letter-spacing: 0;
            }
            #SidebarNote {
                color: #8290A2;
                background: #17202A;
                border: 1px solid #283442;
                border-radius: 6px;
                padding: 12px;
            }
            #PageTitle {
                font-size: 27px;
                font-weight: 700;
                color: #F7FAFC;
            }
            #PageDescription, #Hint {
                color: #99A7B7;
            }
            #SectionTitle {
                color: #DCE5EE;
                font-size: 15px;
                font-weight: 700;
            }
            #Panel, #MetricCard {
                background: #151B23;
                border: 1px solid #293543;
                border-radius: 8px;
            }
            #MetricValue {
                font-size: 24px;
                font-weight: 700;
                color: #F7FAFC;
            }
            #Nav {
                background: transparent;
                border: 0;
                outline: 0;
            }
            #Nav::item {
                min-height: 42px;
                padding: 8px 12px;
                border-radius: 7px;
                color: #B8C4D2;
            }
            #Nav::item:hover {
                background: #1B2530;
                color: #F7FAFC;
            }
            #Nav::item:selected {
                background: #1E5F74;
                color: #FFFFFF;
            }
            QListWidget#UploadList {
                background: #10161D;
                border: 1px dashed #3A4858;
                border-radius: 8px;
                padding: 10px;
                color: #C8D3DF;
            }
            QListWidget#UploadList::item {
                min-height: 30px;
                padding: 6px 8px;
                border-radius: 5px;
            }
            QListWidget#UploadList::item:hover {
                background: #1B2530;
            }
            QTextEdit {
                background: #10161D;
                border: 1px solid #293543;
                border-radius: 8px;
                color: #E7EDF3;
                padding: 12px;
                selection-background-color: #256D83;
            }
            QPushButton {
                background: #26758C;
                color: #FFFFFF;
                border: 0;
                border-radius: 7px;
                padding: 9px 16px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #2F8EA8;
            }
            QPushButton:pressed {
                background: #1F6073;
            }
            QPushButton#SecondaryButton {
                background: #1B2530;
                color: #D7E0EA;
                border: 1px solid #314052;
            }
            QPushButton#SecondaryButton:hover {
                background: #243141;
            }
            QRadioButton, QCheckBox {
                color: #D7E0EA;
                spacing: 8px;
                padding: 8px 6px;
            }
            QComboBox {
                color: #D7E0EA;
                background: #10161D;
                border: 1px solid #314052;
                border-radius: 7px;
                padding: 8px 10px;
            }
            #StatusOk {
                color: #74D79A;
                font-weight: 700;
            }
            #StatusFail {
                color: #FF8B8B;
                font-weight: 700;
            }
            #StatusNeutral {
                color: #9AA8B8;
                font-weight: 700;
            }
            #GlobalStatusBar {
                background: #10161D;
                border-top: 1px solid #26313D;
            }
            #StatusDot {
                font-size: 16px;
                color: #91A0B2;
            }
            #StatusDot[state="current"] {
                color: #74D79A;
            }
            #StatusDot[state="available"] {
                color: #F3C969;
            }
            #StatusChannel, #StatusVersion {
                color: #F3F6FA;
                font-weight: 700;
            }
            #StatusMessage {
                color: #9AA8B8;
            }
            #StatusMessage[state="current"] {
                color: #74D79A;
            }
            #StatusMessage[state="available"] {
                color: #F3C969;
            }
            #Toast {
                background: #17202A;
                border: 1px solid #3A4858;
                border-radius: 8px;
            }
            #ToastTitle {
                color: #F7FAFC;
                font-weight: 700;
                font-size: 15px;
            }
            #ToastMessage {
                color: #C8D3DF;
            }
            #ToastAction {
                padding: 8px 14px;
            }
            #ToastProgress {
                background: #10161D;
                border: 1px solid #314052;
                border-radius: 5px;
                height: 9px;
                text-align: center;
                color: transparent;
            }
            #ToastProgress::chunk {
                background: #F3C969;
                border-radius: 4px;
            }
            QDialog {
                background: #121820;
            }
            """
        )
