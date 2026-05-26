from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
import traceback

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QApplication,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from engine.report import AuditReportEngine, SectionController
from v2.core.backtesting import BacktestAnalyticsService
from v2.core.checking import DeclarationDocumentChecker
from v2.core.document_loader import DocumentLoader, LoadedDocument
from v2.core.ds2_gateway import Ds2Gateway
from v2.core.models import CheckStatus, DocumentType, ParsedDocument
from v2.core.parser_engine import SemanticParserEngine
from v2.core.print_workflow import RELEASE_METHODS, ImportPrintWorkflow
from v2.core.settings import V2Settings, load_settings, logs_dir, resolve_local_version, save_settings, version_debug_log
from v2.core.template_learning import CustomerTemplateLearningService
from v2.core.updater import UpdateCheck, V2Updater
from v2.workflow import CaseWorkflow, DocumentWorkflowEngine, WorkflowResult
from v2.workflow.models import CaseStatus


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


@dataclass(frozen=True)
class WorkflowDocumentViewModel:
    document_type: str
    document_name: str
    parser_confidence: str
    page_range: str
    parser_name: str


@dataclass(frozen=True)
class WorkflowCaseViewModel:
    status: str
    status_key: str
    case_id: str
    invoice_no: str
    bl_no: str
    booking_no: str
    document_count: str
    missing_status: str
    updated_at: str


@dataclass(frozen=True)
class WorkflowFailure:
    stage: str
    message: str
    traceback_text: str


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


class WorkflowRunWorker(QObject):
    progress = Signal(str, int, str)
    finished = Signal(object)

    def __init__(self, paths: list[str], direction: str) -> None:
        super().__init__()
        self.paths = paths
        self.direction = direction

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit("Upload", 3, f"queued {len(self.paths)} file(s)")
            result = DocumentWorkflowEngine().process_paths(
                self.paths,
                direction=self.direction,
                progress=lambda stage, percent, message: self.progress.emit(stage, percent, message),
            )
        except Exception as exc:
            traceback_text = getattr(exc, "traceback_text", "") or traceback.format_exc()
            stage = getattr(exc, "stage", "workflow pipeline")
            message = str(exc)
            print(f"[workflow] {stage} failed: {message}", flush=True)
            print(traceback_text, flush=True)
            result = WorkflowFailure(stage=stage, message=message, traceback_text=traceback_text)
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
        self.audit_report_engine = AuditReportEngine()
        self.section_controller = SectionController()
        self.templates = CustomerTemplateLearningService()
        self.analytics = BacktestAnalyticsService(self.templates)
        self.ds2 = Ds2Gateway()
        self.latest_update: UpdateCheck | None = None
        self.workflow_result: WorkflowResult | None = None
        self.workflow_results: dict[str, WorkflowResult] = {}
        self.current_workflow_cases: dict[str, CaseWorkflow] = {}

        self.nav = QListWidget()
        self.stack = QStackedWidget()
        self.release_group = QButtonGroup(self)
        self.print_status = QLabel()
        self.loaded_documents: list[LoadedDocument] = []

        self.status_dot = QLabel()
        self.status_channel = QLabel()
        self.status_version = QLabel()
        self.status_update = QLabel()
        self.workflow_case_list: QListWidget | None = None
        self.workflow_tree: QTreeWidget | None = None
        self.workflow_table: QTableWidget | None = None
        self.workflow_diff: QTextEdit | None = None
        self.workflow_debug: QTextEdit | None = None
        self.workflow_views: dict[str, dict[str, object]] = {}
        self.toast: ToastNotification | None = None
        self.workflow_thread: QThread | None = None
        self.workflow_worker: WorkflowRunWorker | None = None
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
        self.stack.addWidget(self._case_workflow_page())
        self.stack.addWidget(self._direction_workflow_page("import", "進口核對", "INV / PKG / B/L / 清表 / Arrival Notice / DS2 PDF / DS2 TXT"))
        self.stack.addWidget(self._direction_workflow_page("export", "出口核對", "INV / PKG / S/O / Booking / Booking Confirmation / Shipping Order / B/L / 裝箱明細 / 清表 / 出口報單"))
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
        for label in ("案件工作流", "進口核對", "出口核對", "一鍵印單", "回測分析"):
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

    def _case_workflow_page(self) -> QWidget:
        return self._workflow_page("case", "AI Customs Audit Workspace", "import")

    def _workflow_page(self, view_name: str, title_text: str, direction: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        title = QLabel(title_text)
        title.setObjectName("PageTitle")
        mode = QComboBox()
        mode.addItems(["import", "export"])
        mode.setCurrentText(direction)
        mode.setObjectName("WorkflowMode")
        upload_button = QPushButton("選擇文件")
        upload_button.clicked.connect(lambda: self._choose_workflow_documents(mode.currentText(), view_name))
        header_row.addWidget(title)
        header_row.addStretch(1)
        header_row.addWidget(QLabel("流程"))
        header_row.addWidget(mode)
        header_row.addWidget(upload_button)
        layout.addLayout(header_row)

        upload_panel = QFrame()
        upload_panel.setObjectName("WorkflowUpload")
        upload_layout = QVBoxLayout(upload_panel)
        upload_layout.setContentsMargins(14, 12, 14, 12)
        upload_layout.setSpacing(10)
        upload_list = DocumentDropList()
        upload_list.setMinimumHeight(78)
        upload_list.addItem("拖曳多份 PDF / 影像 / TXT 到這裡，或按「選擇文件」批次上傳")
        upload_list.files_dropped.connect(lambda paths: self._run_workflow(paths, mode.currentText(), view_name))
        upload_layout.addWidget(upload_list)

        progress_row = QHBoxLayout()
        upload_progress = QProgressBar()
        upload_progress.setRange(0, 100)
        upload_progress.setValue(0)
        upload_progress.setFormat("Upload 0%")
        ocr_progress = QProgressBar()
        ocr_progress.setRange(0, 100)
        ocr_progress.setValue(0)
        ocr_progress.setFormat("OCR 0%")
        workflow_progress = QProgressBar()
        workflow_progress.setRange(0, 100)
        workflow_progress.setValue(0)
        workflow_progress.setFormat("流程處理")
        progress_row.addWidget(upload_progress)
        progress_row.addWidget(ocr_progress)
        progress_row.addWidget(workflow_progress)
        upload_layout.addLayout(progress_row)
        layout.addWidget(upload_panel)

        status_bar = QFrame()
        status_bar.setObjectName("WorkflowStatusBar")
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(12, 8, 12, 8)
        status_layout.setSpacing(8)
        status_steps: list[QLabel] = []
        for index, step in enumerate(["上傳", "讀取", "分類", "組案", "核對", "摘要", "完成"]):
            if index:
                arrow = QLabel(">")
                arrow.setObjectName("WorkflowArrow")
                status_layout.addWidget(arrow)
            label = QLabel(step)
            label.setObjectName("WorkflowStep")
            label.setProperty("state", "pending")
            status_steps.append(label)
            status_layout.addWidget(label)
        status_layout.addStretch(1)
        status_bar.hide()

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setObjectName("AuditSplitter")
        body.setChildrenCollapsible(False)

        document_status_bar = QFrame()
        document_status_bar.setObjectName("DocumentStatusBar")
        document_status_layout = QHBoxLayout(document_status_bar)
        document_status_layout.setContentsMargins(10, 10, 10, 10)
        document_status_layout.setSpacing(6)
        document_status_layout.addStretch(1)
        document_status_bar.hide()

        self.workflow_tree = QTreeWidget()
        self.workflow_tree.setHeaderLabels(["文件", "完整度", "文件名稱", "頁數"])
        self.workflow_tree.setObjectName("ResultBox")
        self.workflow_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.workflow_tree.setMinimumHeight(170)

        compare_table = QTableWidget()
        compare_table.setColumnCount(4)
        compare_table.setHorizontalHeaderLabels(["欄位", "文件值", "報單值", "結果"])
        compare_table.setObjectName("CompareTable")
        compare_table.verticalHeader().setVisible(False)
        compare_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        compare_table.setSortingEnabled(True)
        compare_table.setMinimumHeight(430)

        compare_search = QLineEdit()
        compare_search.setPlaceholderText("搜尋欄位、文件值、報單值")
        compare_search.setObjectName("CompareSearch")
        compare_only_issues = QCheckBox("只顯示異常")
        compare_only_issues.setChecked(False)
        compare_search.textChanged.connect(lambda _text, view=view_name: self._apply_compare_filters(view))
        compare_only_issues.toggled.connect(lambda _checked, view=view_name: self._apply_compare_filters(view))

        audit_report_view = QTextEdit()
        audit_report_view.setReadOnly(True)
        audit_report_view.setObjectName("AuditReportView")
        audit_report_view.setPlaceholderText("完整人工核對報告會顯示在這裡")

        audit_summary = QTextEdit()
        audit_summary.setReadOnly(True)
        audit_summary.setObjectName("RiskSummaryCard")
        audit_summary.setPlaceholderText("異常摘要 / 高風險提示")

        self.workflow_debug = QTextEdit()
        self.workflow_debug.setReadOnly(True)
        self.workflow_debug.setObjectName("DebugBox")
        self.workflow_debug.hide()
        debug_toggle = QPushButton("開發者模式")
        debug_toggle.setObjectName("SecondaryButton")
        debug_toggle.setCheckable(True)
        debug_toggle.setChecked(False)
        debug_toggle.toggled.connect(self.workflow_debug.setVisible)

        audit_workspace = QFrame()
        audit_workspace.setObjectName("AuditWorkspace")
        center = QVBoxLayout(audit_workspace)
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(10)
        center.addWidget(QLabel("AI Customs Audit Report"))
        center.addWidget(audit_report_view, 1)

        summary_panel = QFrame()
        summary_panel.setObjectName("AuditSummaryPanel")
        summary_layout = QVBoxLayout(summary_panel)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(10)
        summary_layout.addWidget(QLabel("異常摘要 / 高風險提示"))
        summary_layout.addWidget(audit_summary, 1)
        self.workflow_debug.hide()

        body.addWidget(audit_workspace)
        body.addWidget(summary_panel)
        body.setStretchFactor(0, 7)
        body.setStretchFactor(1, 3)
        body.setSizes([980, 340])
        layout.addWidget(body, 1)
        self.workflow_views[view_name] = {
            "tree": self.workflow_tree,
            "table": compare_table,
            "audit_report": audit_report_view,
            "summary": audit_summary,
            "document_status_bar": document_status_bar,
            "document_status_layout": document_status_layout,
            "debug": self.workflow_debug,
            "debug_toggle": debug_toggle,
            "compare_search": compare_search,
            "compare_only_issues": compare_only_issues,
            "upload": upload_list,
            "upload_progress": upload_progress,
            "ocr_progress": ocr_progress,
            "workflow_progress": workflow_progress,
            "status_steps": status_steps,
            "mode": mode,
        }
        return page

    def _direction_workflow_page(self, mode: str, title_text: str, description: str) -> QWidget:
        return self._workflow_page(mode, title_text, mode)

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

    def _choose_workflow_documents(self, direction: str = "import", view_name: str = "case") -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "匯入案件文件",
            "",
            "Documents (*.pdf *.txt *.csv *.tsv *.xlsx *.png *.jpg *.jpeg *.tif *.tiff);;All Files (*.*)",
        )
        if paths:
            self._run_workflow(paths, direction, view_name)

    def _run_workflow(self, paths: list[str], direction: str = "import", view_name: str = "case") -> None:
        if self.workflow_thread and self.workflow_thread.isRunning():
            self._show_toast("工作流處理中", "目前文件仍在處理。", action_visible=False, timeout_ms=3000)
            return
        view = self.workflow_views.get(view_name, {})
        case_list = view.get("case_list")
        tree = view.get("tree")
        table = view.get("table")
        audit_report = view.get("audit_report")
        summary = view.get("summary")
        debug = view.get("debug")
        upload = view.get("upload")
        if isinstance(upload, QListWidget):
            upload.clear()
            for path in paths:
                upload.addItem(path)
        if isinstance(case_list, QTableWidget):
            case_list.setRowCount(1)
            for col, value in enumerate(["processing", "處理中", "-", "-", "-", str(len(paths)), "-", "-"]):
                case_list.setItem(0, col, QTableWidgetItem(value))
        if isinstance(tree, QTreeWidget):
            tree.clear()
        if isinstance(table, QTableWidget):
            table.setRowCount(0)
        if isinstance(audit_report, QTextEdit):
            audit_report.setText("文件處理中...\n\n正在執行 OCR、parser、workflow grouping 與 audit report generation。")
        if isinstance(summary, QTextEdit):
            summary.setText("等待 OCR / parser / audit 結果。")
        if isinstance(debug, QTextEdit):
            debug.clear()
        self._set_workflow_progress(view_name, "Upload", 3, "workflow task queued")

        self.workflow_thread = QThread(self)
        self.workflow_thread.setProperty("workflow_view", view_name)
        self.workflow_worker = WorkflowRunWorker(paths, direction)
        self.workflow_worker.moveToThread(self.workflow_thread)
        self.workflow_thread.started.connect(self.workflow_worker.run)
        self.workflow_worker.progress.connect(self._on_workflow_progress)
        self.workflow_worker.finished.connect(self._on_workflow_finished)
        self.workflow_worker.finished.connect(self.workflow_thread.quit)
        self.workflow_worker.finished.connect(self.workflow_worker.deleteLater)
        self.workflow_thread.finished.connect(self.workflow_thread.deleteLater)
        self.workflow_thread.finished.connect(self._clear_workflow_worker)
        self.workflow_thread.start()

    @Slot(str, int, str)
    def _on_workflow_progress(self, stage: str, percent: int, message: str) -> None:
        view_name = self.workflow_thread.property("workflow_view") if self.workflow_thread else "case"
        self._set_workflow_progress(str(view_name), stage, percent, message)

    @Slot(object)
    def _on_workflow_finished(self, result: object) -> None:
        if isinstance(result, WorkflowFailure) or isinstance(result, Exception):
            view_name = self.workflow_thread.property("workflow_view") if self.workflow_thread else "case"
            view = self.workflow_views.get(str(view_name), {})
            case_list = view.get("case_list")
            audit_report = view.get("audit_report")
            summary = view.get("summary")
            debug = view.get("debug")
            stage = result.stage if isinstance(result, WorkflowFailure) else "workflow pipeline"
            message = result.message if isinstance(result, WorkflowFailure) else str(result)
            traceback_text = result.traceback_text if isinstance(result, WorkflowFailure) else ""
            failure_text = self._format_workflow_failure(stage, message, traceback_text)
            if isinstance(case_list, QTableWidget):
                case_list.setRowCount(1)
                for col, value in enumerate(["exception", "處理失敗", "-", "-", "-", "-", "-", datetime.now().strftime("%H:%M")]):
                    case_list.setItem(0, col, QTableWidgetItem(value))
            if isinstance(audit_report, QTextEdit):
                audit_report.setText(failure_text)
            if isinstance(summary, QTextEdit):
                summary.setText(f"❌ {stage} failed\n\n{message}")
            if isinstance(debug, QTextEdit):
                debug.setText(failure_text)
            self._set_workflow_progress(str(view_name), "Exception", 100, message)
            return
        view_name = self.workflow_thread.property("workflow_view") if self.workflow_thread else "case"
        self.workflow_result = result
        self.workflow_results[str(view_name)] = result
        self._set_workflow_progress(str(view_name), "Completed", 100, f"完成 {len(result.cases)} 個案件")
        self._refresh_workflow_cases(str(view_name))

    @Slot()
    def _clear_workflow_worker(self) -> None:
        self.workflow_thread = None
        self.workflow_worker = None

    def _format_workflow_failure(self, stage: str, message: str, traceback_text: str) -> str:
        details = traceback_text.strip() or "No traceback captured."
        return (
            f"❌ {stage} failed\n\n"
            f"原因:\n{message}\n\n"
            "Pipeline 已停止，避免畫面永久停在 loading 狀態。\n\n"
            f"Exception log:\n{details}"
        )

    def _set_workflow_progress(self, view_name: str, stage: str, percent: int, message: str) -> None:
        view = self.workflow_views.get(view_name, {})
        upload_progress = view.get("upload_progress")
        ocr_progress = view.get("ocr_progress")
        workflow_progress = view.get("workflow_progress")
        if isinstance(upload_progress, QProgressBar):
            upload_value = 100 if percent >= 8 else percent
            upload_progress.setValue(upload_value)
            upload_progress.setFormat(f"Upload {upload_value}%")
        if isinstance(ocr_progress, QProgressBar):
            ocr_value = 100 if percent >= 42 else max(0, percent - 8)
            ocr_progress.setValue(min(100, ocr_value))
            ocr_progress.setFormat(f"OCR {min(100, ocr_value)}%")
        if isinstance(workflow_progress, QProgressBar):
            workflow_value = max(0, percent - 42)
            workflow_progress.setValue(min(100, workflow_value))
            workflow_progress.setFormat("流程處理")
        steps = view.get("status_steps")
        if isinstance(steps, list):
            active_index = -1
            for index, label in enumerate(steps):
                if isinstance(label, QLabel) and label.text() == stage:
                    active_index = index
                    break
            if stage == "Exception":
                active_index = len(steps) - 1
            for index, label in enumerate(steps):
                if not isinstance(label, QLabel):
                    continue
                state = "done" if index < active_index else "active" if index == active_index else "pending"
                if stage == "Exception" and index == active_index:
                    state = "error"
                label.setProperty("state", state)
                label.setToolTip(message)
                label.style().unpolish(label)
                label.style().polish(label)

    def _refresh_workflow_cases(self, view_name: str = "case") -> None:
        result = self.workflow_results.get(view_name) or self.workflow_result
        view = self.workflow_views.get(view_name, {})
        case_list = view.get("case_list")
        if result and not isinstance(case_list, QTableWidget):
            if result.cases:
                self._render_workflow_case(result.cases[0], view_name)
            else:
                self._render_workflow_result_without_case(result, view_name)
                debug = view.get("debug")
                if isinstance(debug, QTextEdit):
                    debug.setText("未建立 workflow。請確認文件內是否包含可辨識的 INV / B/L / Booking / DS2 資訊。")
            return
        if not result or not isinstance(case_list, QTableWidget):
            return
        case_list.setRowCount(len(result.cases))
        for row, case in enumerate(result.cases):
            vm = self._case_view_model(case)
            values = [
                vm.status,
                vm.case_id,
                vm.document_count,
                vm.missing_status,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setBackground(QBrush(QColor(self._case_status_color(vm.status_key))))
                case_list.setItem(row, col, item)
        case_list.resizeColumnsToContents()
        if result.cases:
            case_list.selectRow(0)
        else:
            debug = view.get("debug")
            if isinstance(debug, QTextEdit):
                debug.setText("未建立案件。請確認文件內是否包含可辨識的 INV / B/L / Booking / DS2 資訊。")

    def _case_view_model(self, case: CaseWorkflow) -> WorkflowCaseViewModel:
        keys = case.match_keys
        status_key = self._case_status_key(case)
        return WorkflowCaseViewModel(
            status=self._case_status_label(status_key),
            status_key=status_key,
            case_id=case.case_id,
            invoice_no=keys.get("invoice_no", "-"),
            bl_no=keys.get("bl_no", "-"),
            booking_no=keys.get("booking_no") or keys.get("shipping_order_no") or "-",
            document_count=f"{len(case.documents)}份",
            missing_status="待補 " + "、".join(case.missing_documents) if case.missing_documents else self._case_action_label(case),
            updated_at=datetime.now().strftime("%H:%M"),
        )

    def _document_view_model(self, segment) -> WorkflowDocumentViewModel:
        parsed = segment.parsed
        document_type = self._document_label(parsed.document_type) if parsed else self._document_label(segment.detected_type)
        parser_name = segment.parser_result.parser_name if segment.parser_result else "-"
        return WorkflowDocumentViewModel(
            document_type=document_type,
            document_name=segment.source_name,
            parser_confidence=f"{segment.confidence:.2f}",
            page_range=f"{segment.page_start}-{segment.page_end}",
            parser_name=parser_name,
        )

    def _case_status_key(self, case: CaseWorkflow) -> str:
        state = getattr(case, "workflow_state", "")
        if state in {"AUDIT_COMPLETED", "READY_FOR_AUDIT"}:
            return "completed"
        if state in {"WAITING_BL", "WAITING_DECLARATION", "PARTIAL_WORKFLOW"}:
            return "missing_docs"
        if state == "LOW_CONFIDENCE":
            return "processing"
        if state == "NEEDS_HUMAN_REVIEW":
            return "exception"
        if case.status == CaseStatus.COMPLETE:
            return "completed"
        if case.status == CaseStatus.MISSING_DOCUMENTS:
            return "missing_docs"
        if case.status == CaseStatus.EXCEPTION:
            return "exception"
        return "processing"

    def _case_status_label(self, status_key: str) -> str:
        return {
            "completed": "核對完成",
            "missing_docs": "待補件",
            "exception": "需人工確認",
            "processing": "可核對",
        }.get(status_key, status_key)

    def _case_action_label(self, case: CaseWorkflow) -> str:
        if getattr(case, "workflow_state", "") in {"READY_FOR_AUDIT", "AUDIT_COMPLETED"}:
            return "可核對"
        if getattr(case, "workflow_state", "") == "LOW_CONFIDENCE":
            return "確認同票"
        if case.rule_findings:
            return "確認規則"
        return "無"

    def _case_status_color(self, status_key: str) -> str:
        return {
            "completed": "#244E35",
            "missing_docs": "#5B4A20",
            "exception": "#5A2A2A",
            "processing": "#1F4B63",
        }.get(status_key, "#1B2530")

    def _select_workflow_case(self, row: int, view_name: str = "case") -> None:
        result = self.workflow_results.get(view_name) or self.workflow_result
        if not result or row < 0 or row >= len(result.cases):
            return
        self._render_workflow_case(result.cases[row], view_name)

    def _apply_workflow_nav_filter(self, text: str, view_name: str = "case") -> None:
        view = self.workflow_views.get(view_name, {})
        search = view.get("compare_search")
        only_issues = view.get("compare_only_issues")
        if isinstance(search, QLineEdit):
            mapping = {
                "文件完整度": "",
                "報單核對": "",
                "清表核對": "清表",
                "稅額驗算": "稅則",
                "船名航次": "船名航次",
                "櫃號封條": "櫃號",
                "輸入規定": "輸入規定",
                "風險項目": "",
                "最終確認": "",
            }
            search.setText(mapping.get(text, ""))
        if isinstance(only_issues, QCheckBox):
            only_issues.setChecked(text in {"風險項目", "文件完整度"})
        self._apply_compare_filters(view_name)

    def _render_selected_section(self, item: QListWidgetItem | None, view_name: str = "case") -> None:
        if item is None:
            return
        case = self.current_workflow_cases.get(view_name)
        if not case:
            return
        section_key = item.data(Qt.ItemDataRole.UserRole) or self.section_controller.section_key_for_label(item.text())
        self._render_workflow_section(case, str(section_key), view_name)

    def _render_workflow_case(self, case: CaseWorkflow, view_name: str = "case") -> None:
        view = self.workflow_views.get(view_name, {})
        tree = view.get("tree")
        table = view.get("table")
        audit_report = view.get("audit_report")
        summary = view.get("summary")
        debug = view.get("debug")
        self.current_workflow_cases[view_name] = case
        self._render_document_status_bar(case, view_name)
        self._update_workflow_section_states(case, view_name)
        if isinstance(tree, QTreeWidget):
            tree.clear()
            vm = self._case_view_model(case)
            root = QTreeWidgetItem([vm.case_id, vm.status, "", ""])
            tree.addTopLevelItem(root)
            for item in self._document_checklist_items(case):
                root.addChild(item)
            root.setExpanded(True)

        if isinstance(table, QTableWidget):
            self._populate_compare_table(table, case)
            self._apply_compare_filters(view_name)
        if isinstance(audit_report, QTextEdit):
            audit_report.setText(self.audit_report_engine.build_text(case))
        if isinstance(summary, QTextEdit):
            summary.setText(self._format_risk_summary(case))
        elif isinstance(summary, QLabel):
            summary.setText(self._format_audit_summary_card(case))
        if isinstance(debug, QTextEdit):
            debug.setText(self._format_case_debug(case))

    def _render_workflow_result_without_case(self, result: WorkflowResult, view_name: str = "case") -> None:
        view = self.workflow_views.get(view_name, {})
        audit_report = view.get("audit_report")
        summary = view.get("summary")
        table = view.get("table")
        if isinstance(table, QTableWidget):
            table.setRowCount(0)
        text = self._format_intake_report(result)
        if isinstance(audit_report, QTextEdit):
            audit_report.setText(text)
        if isinstance(summary, QTextEdit):
            missing = self._infer_missing_documents_from_segments(result)
            if missing:
                summary.setText("\n".join(f"⚠ 缺少 {name}" for name in missing))
            else:
                summary.setText("⚠ 尚未建立可核對案件，請確認文件是否含 INV / PL / B/L / DS2 或 SO 關鍵資料。")

    def _format_intake_report(self, result: WorkflowResult) -> str:
        lines = [
            "AI Customs Audit Report",
            "目前已完成 OCR / parser，但尚未建立可完整核對的案件 workflow。",
            "",
            "一、文件完整度",
        ]
        if result.segments:
            for segment in result.segments:
                document_type = self._document_label(segment.parsed.document_type if segment.parsed else segment.detected_type)
                lines.append(f"- {document_type}: {segment.source_name} p.{segment.page_start}-{segment.page_end}")
        else:
            lines.append("- 尚未辨識到可核對文件")
        missing = self._infer_missing_documents_from_segments(result)
        if missing:
            lines.extend(["", "缺少文件：", "、".join(missing)])
        lines.extend([
            "",
            "二、核對狀態",
            "結果：",
            "⚠ 需補件或人工確認",
            "",
            "說明：",
            "系統已完成文件讀取與 parser，但缺少足夠的 grouping key 或必要文件，因此尚不能產生船名航次、件數、重量、CIF、稅則等完整核對段落。",
        ])
        return "\n".join(lines)

    def _infer_missing_documents_from_segments(self, result: WorkflowResult) -> list[str]:
        found = {
            self._document_label(segment.parsed.document_type if segment.parsed else segment.detected_type)
            for segment in result.segments
        }
        required = ["DS2 報單", "INV", "PKG", "B/L"] if result.direction != "export" else ["出口報單", "INV", "PKG", "BOOKING", "B/L"]
        return [name for name in required if name not in found and not (name == "PKG" and "PL / PKG" in found)]

    def _render_workflow_section(self, case: CaseWorkflow, section_key: str, view_name: str = "case") -> None:
        view = self.workflow_views.get(view_name, {})
        audit_report = view.get("audit_report")
        search = view.get("compare_search")
        only_issues = view.get("compare_only_issues")
        rendered = self.section_controller.render(case, section_key)
        if isinstance(audit_report, QTextEdit):
            audit_report.setText(rendered.text)
        if isinstance(search, QLineEdit):
            search.setText(self._section_search_term(section_key))
        if isinstance(only_issues, QCheckBox):
            only_issues.setChecked(section_key == "risk")
        self._apply_compare_filters(view_name)

    def _format_risk_summary(self, case: CaseWorkflow) -> str:
        lines: list[str] = []
        for missing in case.missing_documents:
            lines.append(f"⚠ 缺少 {missing}")
        if case.audit_report:
            for result in case.audit_report.results:
                if result.status == CheckStatus.MISMATCH:
                    lines.append(f"⚠ {FIELD_LABELS.get(result.field.value, result.field.value)} 不一致")
                elif result.status == CheckStatus.MISSING:
                    lines.append(f"⚠ {FIELD_LABELS.get(result.field.value, result.field.value)} 無法確認")
                elif result.status == CheckStatus.HIGH_RISK:
                    lines.append(f"⚠ {FIELD_LABELS.get(result.field.value, result.field.value)} 高風險")
            lines.extend(f"⚠ {warning}" for warning in case.audit_report.high_risk_warnings)
        lines.extend(f"⚠ {finding}" for finding in case.rule_findings)
        if not lines:
            lines.append("目前未發現阻擋申報的異常。")
        return "\n".join(dict.fromkeys(lines))

    def _update_workflow_section_states(self, case: CaseWorkflow, view_name: str = "case") -> None:
        view = self.workflow_views.get(view_name, {})
        nav = view.get("workflow_nav")
        if not isinstance(nav, QListWidget):
            return
        states = self.section_controller.states(case)
        for index in range(nav.count()):
            item = nav.item(index)
            key = item.data(Qt.ItemDataRole.UserRole)
            state = states.get(str(key))
            if not state:
                continue
            item.setText(f"{self._section_status_icon(state.status)} {state.label}")
            item.setToolTip(state.status)

    def _section_search_term(self, section_key: str) -> str:
        return {
            "document_completeness": "",
            "declaration": "",
            "clearance": "清表",
            "tax_amount": "稅則",
            "vessel_voyage": "船名航次",
            "port": "港口",
            "closing_date": "ETD",
            "package_count": "件數",
            "container": "櫃號",
            "weight": "重量",
            "amount": "金額",
            "unit_price": "金額",
            "cif": "金額",
            "exchange_rate": "幣別",
            "hs_code": "稅則",
            "statistics": "數量",
            "import_regulation": "稅則",
            "risk": "",
            "final_review": "",
        }.get(section_key, "")

    def _section_status_icon(self, status: str) -> str:
        return {
            "未核對": "○",
            "核對中": "◐",
            "已完成": "✓",
            "異常": "!",
            "需人工確認": "⚠",
        }.get(status, "○")

    def _render_document_status_bar(self, case: CaseWorkflow, view_name: str = "case") -> None:
        view = self.workflow_views.get(view_name, {})
        layout = view.get("document_status_layout")
        if not isinstance(layout, QHBoxLayout):
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for item in self._document_status_items(case):
            label = QLabel(item[0])
            label.setObjectName("DocumentStatusPill")
            label.setProperty("state", item[1])
            label.setToolTip(item[2])
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
        layout.addStretch(1)

    def _document_status_items(self, case: CaseWorkflow) -> list[tuple[str, str, str]]:
        present = {
            (segment.parsed.document_type if segment.parsed else segment.detected_type).value: segment
            for segment in case.documents
        }
        required = (
            [
                (DocumentType.INVOICE.value, "INV"),
                (DocumentType.PACKING_LIST.value, "PL"),
                (DocumentType.BILL_OF_LADING.value, "B/L"),
                (DocumentType.DS2_DECLARATION.value, "DS2"),
            ]
            if case.direction != "export"
            else [
                (DocumentType.INVOICE.value, "INV"),
                (DocumentType.PACKING_LIST.value, "PL"),
                (DocumentType.BOOKING.value, "BOOKING"),
                (DocumentType.BILL_OF_LADING.value, "B/L"),
                (DocumentType.EXPORT_DECLARATION.value, "報單"),
            ]
        )
        items: list[tuple[str, str, str]] = []
        for document_key, label in required:
            segment = present.get(document_key)
            if not segment:
                items.append((f"{label} ✗", "missing", "缺少此文件"))
            elif segment.confidence < 0.55:
                items.append((f"{label} ⚠", "warning", f"OCR 待確認: {segment.source_name}"))
            else:
                items.append((f"{label} ✓", "ok", segment.source_name))
        return items

    def _format_audit_summary_card(self, case: CaseWorkflow) -> str:
        text = self._format_audit_summary(case)
        lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("【")]
        priority = [line for line in lines if line.startswith(("✗", "⚠"))]
        confirmed = [line for line in lines if line.startswith("✓")]
        display = priority[:4] + confirmed[:3]
        if not display:
            display = ["⚠ 尚未產生欄位核對結果"]
        return "\n".join(display[:7])

    def _format_audit_summary(self, case: CaseWorkflow) -> str:
        if case.audit_summary:
            return case.audit_summary.human_text()
        if case.audit_report:
            return case.audit_report.summary
        if case.missing_documents:
            missing = "\n".join(f"✗ {name}" for name in case.missing_documents)
            return f"【文件狀態】\n{missing}\n\n【欄位核對】\n⚠ 尚未產生欄位核對結果\n\n【問題】\n1. 缺少必要文件"
        return "【文件狀態】\n⚠ 尚未辨識到可核對文件\n\n【欄位核對】\n⚠ 尚未產生欄位核對結果"

    def _document_checklist_items(self, case: CaseWorkflow) -> list[QTreeWidgetItem]:
        present = {
            (segment.parsed.document_type if segment.parsed else segment.detected_type).value: segment
            for segment in case.documents
        }
        required = (
            [
                (DocumentType.DS2_DECLARATION.value, "DS2 報單"),
                (DocumentType.INVOICE.value, "INV"),
                (DocumentType.PACKING_LIST.value, "PL / PKG"),
                (DocumentType.BILL_OF_LADING.value, "B/L"),
            ]
            if case.direction != "export"
            else [
                (DocumentType.EXPORT_DECLARATION.value, "出口報單"),
                (DocumentType.INVOICE.value, "INV"),
                (DocumentType.PACKING_LIST.value, "PL / PKG"),
                (DocumentType.BOOKING.value, "BOOKING"),
                (DocumentType.BILL_OF_LADING.value, "B/L"),
            ]
        )
        required_keys = {key for key, _label in required}
        items: list[QTreeWidgetItem] = []
        for document_key, document_label in required:
            segment = present.get(document_key)
            if segment:
                status = "✓ 已收到" if segment.confidence >= 0.55 else "⚠ OCR 待確認"
                item = QTreeWidgetItem([document_label, status, segment.source_name, f"{segment.page_start}-{segment.page_end}"])
                item.setToolTip(1, "文件已納入本案核對")
                if segment.confidence < 0.55:
                    item.setBackground(1, QBrush(QColor("#5B4A20")))
            else:
                item = QTreeWidgetItem([document_label, "✗ 待補", "-", "-"])
                item.setToolTip(1, "缺少此文件，需補件後才能完整核對")
                item.setBackground(1, QBrush(QColor("#5A2A2A")))
            items.append(item)
        extra_segments = [
            segment for segment in case.documents
            if (segment.parsed.document_type if segment.parsed else segment.detected_type).value not in required_keys
        ]
        for segment in extra_segments:
            document_type = segment.parsed.document_type if segment.parsed else segment.detected_type
            items.append(QTreeWidgetItem([self._document_label(document_type), "✓ 已收到", segment.source_name, f"{segment.page_start}-{segment.page_end}"]))
        return items

    def _format_case_diff(self, case: CaseWorkflow) -> str:
        colors = {
            "MATCH": "#74D79A",
            "MISMATCH": "#FF8B8B",
            "MISSING": "#F3C969",
            "HIGH_RISK": "#FF8B8B",
        }
        lines = [f"<b>{case.case_id}</b> - {case.status.value}<br>"]
        if case.missing_documents:
            lines.append(f"<span style='color:#F3C969'>缺文件：{', '.join(case.missing_documents)}</span><br>")
        if case.rule_findings:
            lines.append(f"<span style='color:#F3C969'>規則提醒：{' / '.join(case.rule_findings)}</span><br>")
        if not case.audit_report:
            return "".join(lines)
        lines.append(f"{case.audit_report.summary}<br><br>")
        for result in case.audit_report.results:
            status_name = result.status.name
            color = colors.get(status_name, "#C8D3DF")
            values = " | ".join(f"{name}: {value}" for name, value in result.document_values.items()) or "-"
            lines.append(
                f"<span style='color:{color}'>● {result.field.value}</span> "
                f"報單={result.declaration_value or '-'} / 文件={values}<br>"
            )
        return "".join(lines)

    def _populate_compare_table(self, table: QTableWidget, case: CaseWorkflow) -> None:
        table.setSortingEnabled(False)
        report = case.audit_report
        results = report.results if report else []
        if not results:
            fallback_rows = []
            if case.missing_documents:
                fallback_rows.extend((missing, "缺少文件", "-", "✗ 待補件") for missing in case.missing_documents)
            if case.rule_findings:
                fallback_rows.extend(("規則提醒", finding, "-", "⚠ 需確認") for finding in case.rule_findings)
            if not fallback_rows:
                fallback_rows.append(("欄位核對", "目前文件不足，尚不可比對欄位", "-", "⚠ 待補件"))
            table.setRowCount(len(fallback_rows))
            for row, cells in enumerate(fallback_rows):
                for col, value in enumerate(cells):
                    item = QTableWidgetItem(value)
                    if col == 3:
                        item.setBackground(QBrush(QColor("#5B4A20")))
                    table.setItem(row, col, item)
            table.setSortingEnabled(True)
            table.resizeColumnsToContents()
            return
        table.setRowCount(len(results))
        color_by_status = {
            CheckStatus.MATCH: "#244E35",
            CheckStatus.MISSING: "#5B4A20",
            CheckStatus.MISMATCH: "#5A2A2A",
            CheckStatus.HIGH_RISK: "#5A2A2A",
        }
        label_by_status = {
            CheckStatus.MATCH: "✓ 一致",
            CheckStatus.MISSING: "⚠ 無法確認",
            CheckStatus.MISMATCH: "✗ 不一致",
            CheckStatus.HIGH_RISK: "⚠ 高風險",
        }
        for row, result in enumerate(results):
            values = " | ".join(f"{name}: {value}" for name, value in result.document_values.items()) or "-"
            cells = [
                FIELD_LABELS.get(result.field.value, result.field.value),
                values,
                result.declaration_value or "-",
                label_by_status.get(result.status, result.status.value),
            ]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                item.setToolTip(result.message)
                table.setItem(row, col, item)
            status_item = table.item(row, 3)
            status_item.setToolTip(result.status.value)
            status_item.setBackground(QBrush(QColor(color_by_status.get(result.status, "#1B2530"))))
            if result.status in {CheckStatus.MISMATCH, CheckStatus.HIGH_RISK}:
                for col in range(table.columnCount()):
                    cell = table.item(row, col)
                    if cell:
                        cell.setBackground(QBrush(QColor("#3A2020")))
            elif result.status == CheckStatus.MISSING:
                for col in range(table.columnCount()):
                    cell = table.item(row, col)
                    if cell:
                        cell.setBackground(QBrush(QColor("#302814")))
        table.setSortingEnabled(True)
        table.resizeColumnsToContents()

    def _apply_compare_filters(self, view_name: str = "case") -> None:
        view = self.workflow_views.get(view_name, {})
        table = view.get("table")
        search = view.get("compare_search")
        only_issues = view.get("compare_only_issues")
        if not isinstance(table, QTableWidget):
            return
        query = search.text().strip().casefold() if isinstance(search, QLineEdit) else ""
        issue_only = only_issues.isChecked() if isinstance(only_issues, QCheckBox) else False
        normal_labels = {"一致"}
        for row in range(table.rowCount()):
            row_text = " ".join(
                table.item(row, col).text() for col in range(table.columnCount()) if table.item(row, col)
            ).casefold()
            status = table.item(row, table.columnCount() - 1).text() if table.item(row, table.columnCount() - 1) else ""
            hidden = bool(query and query not in row_text)
            if issue_only and status.replace("✓", "").strip() in normal_labels:
                hidden = True
            table.setRowHidden(row, hidden)

    def _field_category(self, field_name: str) -> str:
        if field_name in {"quantity", "package_count", "unit"}:
            return "數量"
        if field_name in {"gross_weight", "net_weight"}:
            return "重量"
        if field_name in {"amount", "currency"}:
            return "金額"
        if field_name in {"container_no", "seal_no"}:
            return "櫃封"
        if field_name in {"port", "vessel_voyage", "origin"}:
            return "航運"
        if field_name in {"hs_code"}:
            return "稅則"
        return "基本資料"

    def _format_case_debug(self, case: CaseWorkflow) -> str:
        lines = [
            f"case id: {case.case_id}",
            f"status: {self._case_status_label(self._case_status_key(case))}",
            f"workflow grouping keys: {case.match_keys or '-'}",
            f"missing fields/documents: {case.missing_documents or '-'}",
            "",
        ]
        for segment in case.documents:
            parsed = segment.parsed
            fields = []
            if parsed:
                for field in parsed.fields:
                    label = FIELD_LABELS.get(field.canonical.value, field.canonical.value)
                    fields.append(f"  - {label}: {field.value} (confidence={field.confidence:.2f}, source={field.source_label})")
            ocr_text = segment.text.strip().replace("\r\n", "\n")[:1600]
            lines.extend(
                [
                    f"document: {segment.source_name}",
                    f"page range: {segment.page_start}-{segment.page_end}",
                    f"parser type: {segment.parser_result.parser_name if segment.parser_result else '-'}",
                    f"document type: {self._document_label(parsed.document_type) if parsed else self._document_label(segment.detected_type)}",
                    f"confidence: {segment.confidence:.2f}",
                    "extracted fields:",
                    *(fields or ["  - none"]),
                    f"missing fields: {parsed.warnings if parsed and parsed.warnings else '-'}",
                    f"workflow grouping keys: {case.match_keys or '-'}",
                    "OCR text:",
                    ocr_text or "-",
                    f"parser debug: {segment.debug or '-'}",
                    "",
                ]
            )
        return "\n".join(lines)

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
        self.settings.version = resolve_local_version()
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
        self.settings.version = resolve_local_version()
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
        self.settings.version = resolve_local_version()
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
        self.settings.version = resolve_local_version()
        self.status_channel.setText(self.settings.update.channel.title())
        self.status_version.setText(self.settings.version)
        self.status_update.setText(text)
        ui_label_value = f"{self.status_channel.text()} {self.status_version.text()}"
        version_debug_log(
            f"ui_display_version={self.settings.version} ui_channel={self.settings.update.channel} "
            f"ui_version_label_value={ui_label_value} ui_update_status={text} ui_state={state}"
        )
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
            #WorkflowUpload, #WorkflowStatusBar {
                background: #151B23;
                border: 1px solid #293543;
                border-radius: 8px;
            }
            #AuditSplitter::handle {
                background: #1B2530;
                width: 8px;
            }
            #WorkflowSidebar, #AuditWorkspace, #AuditSummaryPanel {
                background: transparent;
            }
            #AuditSummaryCard {
                background: #151B23;
                border: 1px solid #314052;
                border-left: 4px solid #26758C;
                border-radius: 8px;
                padding: 12px 14px;
                color: #E7EDF3;
                font-size: 13px;
                line-height: 1.35;
            }
            #DocumentStatusBar {
                background: #10161D;
                border: 1px solid #293543;
                border-radius: 8px;
            }
            QListWidget#WorkflowNav {
                background: #10161D;
                border: 1px solid #293543;
                border-radius: 8px;
                color: #D7E0EA;
                padding: 6px;
            }
            QListWidget#WorkflowNav::item {
                min-height: 38px;
                padding: 8px 10px;
                border-radius: 6px;
            }
            QListWidget#WorkflowNav::item:hover {
                background: #1B2530;
            }
            QListWidget#WorkflowNav::item:selected {
                background: #1F4B63;
                color: #FFFFFF;
            }
            #DocumentStatusPill {
                border-radius: 6px;
                padding: 7px 8px;
                font-weight: 800;
                min-width: 42px;
            }
            #DocumentStatusPill[state="ok"] {
                color: #74D79A;
                background: #132019;
                border: 1px solid #2E6B46;
            }
            #DocumentStatusPill[state="warning"] {
                color: #F3C969;
                background: #302814;
                border: 1px solid #6F5A22;
            }
            #DocumentStatusPill[state="missing"] {
                color: #FFB4B4;
                background: #3A2020;
                border: 1px solid #7D3434;
            }
            #WorkflowStep {
                color: #94A3B5;
                background: #10161D;
                border: 1px solid #2B3745;
                border-radius: 6px;
                padding: 5px 9px;
                font-size: 12px;
                font-weight: 700;
            }
            #WorkflowStep[state="done"] {
                color: #74D79A;
                border-color: #2E6B46;
                background: #132019;
            }
            #WorkflowStep[state="active"] {
                color: #FFFFFF;
                border-color: #26758C;
                background: #1F4B63;
            }
            #WorkflowStep[state="error"] {
                color: #FFFFFF;
                border-color: #8F3A3A;
                background: #5A2A2A;
            }
            #WorkflowArrow {
                color: #617080;
                font-weight: 700;
            }
            QTableWidget#CaseTable, QTableWidget#CompareTable, QTreeWidget#ResultBox {
                background: #10161D;
                border: 1px solid #293543;
                border-radius: 8px;
                color: #E7EDF3;
                gridline-color: #26313D;
                selection-background-color: #1F4B63;
                selection-color: #FFFFFF;
            }
            QHeaderView::section {
                background: #17202A;
                color: #C8D3DF;
                border: 0;
                border-right: 1px solid #293543;
                border-bottom: 1px solid #293543;
                padding: 7px 8px;
                font-weight: 700;
            }
            QTableWidget::item, QTreeWidget::item {
                padding: 6px 8px;
            }
            QProgressBar {
                background: #10161D;
                border: 1px solid #314052;
                border-radius: 5px;
                height: 16px;
                color: #D7E0EA;
                text-align: center;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background: #26758C;
                border-radius: 4px;
            }
            QTextEdit {
                background: #10161D;
                border: 1px solid #293543;
                border-radius: 8px;
                color: #E7EDF3;
                padding: 12px;
                selection-background-color: #256D83;
            }
            QTextEdit#AuditReportView {
                background: #111821;
                color: #E7EDF3;
                border: 1px solid #344456;
                border-radius: 8px;
                padding: 24px 28px;
                font-size: 15px;
                line-height: 1.45;
            }
            QTextEdit#RiskSummaryCard {
                background: #151B23;
                color: #F3C969;
                border: 1px solid #3F4D5D;
                border-left: 4px solid #C07A2B;
                border-radius: 8px;
                padding: 14px;
                font-size: 13px;
                line-height: 1.35;
            }
            QLineEdit {
                background: #10161D;
                border: 1px solid #314052;
                border-radius: 7px;
                color: #E7EDF3;
                padding: 8px 10px;
                min-width: 220px;
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
