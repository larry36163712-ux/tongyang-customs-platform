from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
import queue
import sys
import threading
import time
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
from v2.core.runtime_log import log_exception, log_runtime
from v2.core.settings import V2Settings, load_settings, logs_dir, read_build_info, resolve_local_version, save_settings, version_debug_log
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
    DocumentType.UNKNOWN: "尚未成功辨識",
}

STATUS_LABELS = {
    CheckStatus.MATCH: "一致",
    CheckStatus.MISMATCH: "不一致",
    CheckStatus.MISSING: "缺少欄位",
    CheckStatus.HIGH_RISK: "高風險",
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
    "declaration_no": "報單號碼",
    "invoice_no": "INV NO",
    "bl_no": "BL NO",
    "booking_no": "Booking NO",
    "incoterm": "Incoterm",
    "cif": "CIF",
    "fob": "FOB",
    "freight": "運費",
    "insurance": "保費",
    "exchange_rate": "匯率",
    "statistical_method": "統計方式",
    "duty_amount": "稅額",
    "closing_date": "結關日",
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


class WorkflowDropPanel(QFrame):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("WorkflowUpload")

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            self.setProperty("dragActive", True)
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
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


class UpdateCheckWorker(QObject):
    finished = Signal(object)

    def __init__(self, version: str, settings: object) -> None:
        super().__init__()
        self.version = version
        self.settings = settings

    @Slot()
    def run(self) -> None:
        try:
            result = V2Updater(self.version, self.settings).check()
        except Exception as exc:
            log_exception("update check failed", exc)
            result = UpdateCheck("error", f"更新檢查失敗，請稍後再試。詳細資訊已寫入 logs/updater.log。")
        self.finished.emit(result)


class WorkflowRunWorker(QObject):
    progress = Signal(str, int, str)
    finished = Signal(object)
    STAGE_TIMEOUT_SECONDS = {
        "Upload": 20,
        "OCR": 90,
        "Document Split": 45,
        "parser": 75,
        "workflow grouping": 45,
        "audit": 60,
    }
    TOTAL_TIMEOUT_SECONDS = 240

    def __init__(self, paths: list[str], direction: str, intake_mode: str = "files") -> None:
        super().__init__()
        self.paths = paths
        self.direction = direction
        self.intake_mode = intake_mode

    @Slot()
    def run(self) -> None:
        log_runtime(
            f"workflow worker run start mode={self.intake_mode} direction={self.direction} "
            f"path_count={len(self.paths)} thread={threading.current_thread().name}"
        )
        events: queue.Queue[tuple[str, object]] = queue.Queue()

        def run_pipeline() -> None:
            try:
                log_runtime("workflow backend thread start")
                engine = DocumentWorkflowEngine()
                if self.intake_mode == "folder":
                    if not self.paths:
                        raise ValueError("no folder was provided to workflow pipeline")
                    pipeline_result = engine.process_folder(
                        self.paths[0],
                        direction=self.direction,
                        progress=lambda stage, percent, message: events.put(("progress", (stage, percent, message))),
                    )
                else:
                    pipeline_result = engine.process_paths(
                        self.paths,
                        direction=self.direction,
                        progress=lambda stage, percent, message: events.put(("progress", (stage, percent, message))),
                    )
                events.put(("finished", pipeline_result))
                log_runtime("workflow backend thread finished successfully")
            except Exception as exc:
                traceback_text = getattr(exc, "traceback_text", "") or traceback.format_exc()
                stage = getattr(exc, "stage", "workflow pipeline")
                message = str(exc)
                log_exception(f"workflow backend failed stage={stage}", exc)
                events.put(("finished", WorkflowFailure(stage=stage, message=message, traceback_text=traceback_text)))

        queued_label = "folder" if self.intake_mode == "folder" else "file(s)"
        self.progress.emit("Upload", 3, f"started: queued {len(self.paths)} {queued_label}")
        worker_thread = threading.Thread(target=run_pipeline, name="workflow-pipeline", daemon=True)
        worker_thread.start()

        result: object | None = None
        started_at = time.monotonic()
        last_progress_at = started_at
        current_stage = "Upload"
        while result is None:
            now = time.monotonic()
            if now - started_at > self.TOTAL_TIMEOUT_SECONDS:
                dump = self._thread_dump(worker_thread)
                log_runtime(f"workflow total timeout thread_alive={worker_thread.is_alive()}\n{dump}")
                result = WorkflowFailure(
                    stage="workflow pipeline",
                    message=f"timeout after {self.TOTAL_TIMEOUT_SECONDS} seconds",
                    traceback_text="Workflow watchdog stopped waiting for the backend pipeline.\n\n" + dump,
                )
                self.progress.emit("workflow pipeline", 100, "timeout: workflow pipeline exceeded total timeout")
                break
            stage_timeout = self.STAGE_TIMEOUT_SECONDS.get(current_stage, 60)
            if now - last_progress_at > stage_timeout:
                dump = self._thread_dump(worker_thread)
                log_runtime(
                    f"workflow stage timeout stage={current_stage} thread_alive={worker_thread.is_alive()} "
                    f"elapsed_without_progress={now - last_progress_at:.1f}\n{dump}"
                )
                result = WorkflowFailure(
                    stage=current_stage,
                    message=f"timeout after {stage_timeout} seconds without progress",
                    traceback_text=(
                        f"Workflow watchdog timeout. Stage={current_stage}; "
                        f"elapsed_without_progress={now - last_progress_at:.1f}s\n\n{dump}"
                    ),
                )
                self.progress.emit(current_stage, 100, f"timeout: {current_stage} stopped reporting progress")
                break
            try:
                kind, payload = events.get(timeout=0.25)
            except queue.Empty:
                if not worker_thread.is_alive():
                    log_runtime(f"workflow backend exited without result stage={current_stage}")
                    result = WorkflowFailure(
                        stage=current_stage,
                        message="backend worker exited without returning a result",
                        traceback_text="No result was received from workflow backend thread.",
                    )
                    break
                continue
            if kind == "progress":
                stage, percent, message = payload  # type: ignore[misc]
                current_stage = str(stage)
                last_progress_at = time.monotonic()
                self.progress.emit(str(stage), int(percent), str(message))
            elif kind == "finished":
                result = payload
        self.finished.emit(result)
        log_runtime(f"workflow worker run finished result_type={type(result).__name__}")

    def _thread_dump(self, worker_thread: threading.Thread) -> str:
        frames = sys._current_frames()
        frame = frames.get(worker_thread.ident or -1)
        if frame is None:
            return f"No Python frame for worker thread ident={worker_thread.ident}"
        stack = "".join(traceback.format_stack(frame))
        return f"Worker thread {worker_thread.name} ident={worker_thread.ident} stack:\n{stack}"


class CustomsErpWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("通洋報關平台")
        self.resize(1320, 860)
        self.setMinimumSize(1180, 760)

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
        self.status_build = QLabel()
        self.status_update = QLabel()
        self.status_check_update_button = QPushButton("檢查更新")
        self.updater_debug_info = QLabel()
        self.workflow_case_list: QListWidget | None = None
        self.workflow_tree: QTreeWidget | None = None
        self.workflow_table: QTableWidget | None = None
        self.workflow_diff: QTextEdit | None = None
        self.workflow_debug: QTextEdit | None = None
        self.workflow_views: dict[str, dict[str, object]] = {}
        self.toast: ToastNotification | None = None
        self.workflow_thread: QThread | None = None
        self.workflow_worker: WorkflowRunWorker | None = None
        self.update_check_thread: QThread | None = None
        self.update_check_worker: UpdateCheckWorker | None = None
        self.update_thread: QThread | None = None
        self.update_worker: UpdateApplyWorker | None = None

        self._build_menu()
        self._build_shell()
        self._apply_theme()
        self._set_update_status("尚未檢查更新", "neutral")
        self._apply_developer_mode_visibility()
        self._refresh_updater_debug_info(local_only=True)

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
        self.updater_debug_action = QAction("Updater Debug", self)
        self.updater_debug_action.triggered.connect(self._open_updater_debug_dialog)
        self.updater_reset_action = QAction("Reset Updater State", self)
        self.updater_reset_action.triggered.connect(lambda: self._reset_updater_state(show_message=True))
        self.menuBar().addAction(settings_action)
        self.menuBar().addAction(check_update_action)
        self.menuBar().addAction(self.updater_debug_action)
        self.menuBar().addAction(self.updater_reset_action)

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
        header_row.addWidget(title)
        header_row.addStretch(1)
        header_row.addWidget(QLabel("案件類型"))
        header_row.addWidget(mode)
        layout.addLayout(header_row)

        upload_panel = WorkflowDropPanel()
        upload_panel.setMaximumHeight(140)
        upload_panel.files_dropped.connect(lambda paths: self._run_workflow(paths, mode.currentText(), view_name))
        upload_layout = QVBoxLayout(upload_panel)
        upload_layout.setContentsMargins(14, 10, 14, 10)
        upload_layout.setSpacing(8)
        upload_top = QHBoxLayout()
        upload_list = DocumentDropList()
        upload_list.setMaximumHeight(58)
        upload_list.addItem("拖曳 PDF / JPG / PNG / XLSX / CSV / TXT 或整個資料夾到這裡")
        upload_list.files_dropped.connect(lambda paths: self._run_workflow(paths, mode.currentText(), view_name))
        upload_button = QPushButton("選擇文件")
        upload_button.clicked.connect(lambda: self._choose_workflow_documents(mode.currentText(), view_name))
        folder_button = QPushButton("選擇資料夾")
        folder_button.clicked.connect(lambda: self._choose_workflow_folder(mode.currentText(), view_name))
        upload_top.addWidget(upload_list, 1)
        upload_top.addWidget(upload_button)
        upload_top.addWidget(folder_button)
        upload_layout.addLayout(upload_top)

        progress_row = QHBoxLayout()
        upload_progress = QProgressBar()
        upload_progress.setRange(0, 100)
        upload_progress.setValue(0)
        upload_progress.setFormat("Upload %p%")
        ocr_progress = QProgressBar()
        ocr_progress.setRange(0, 100)
        ocr_progress.setValue(0)
        ocr_progress.setFormat("OCR %p%")
        workflow_progress = QProgressBar()
        workflow_progress.setRange(0, 100)
        workflow_progress.setValue(0)
        workflow_progress.setFormat("AI Audit %p%")
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
        for index, step in enumerate(["文件分析中", "OCR 辨識中", "AI 核對中", "已完成"]):
            if index:
                arrow = QLabel("·")
                arrow.setObjectName("WorkflowArrow")
                status_layout.addWidget(arrow)
            label = QLabel(step)
            label.setObjectName("WorkflowStep")
            label.setProperty("state", "pending")
            status_steps.append(label)
            status_layout.addWidget(label)
        status_layout.addStretch(1)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setObjectName("AuditSplitter")
        body.setChildrenCollapsible(False)

        document_status_bar = QFrame()
        document_status_bar.setObjectName("DocumentStatusBar")
        document_status_layout = QHBoxLayout(document_status_bar)
        document_status_layout.setContentsMargins(10, 10, 10, 10)
        document_status_layout.setSpacing(6)
        document_status_layout.addStretch(1)

        document_cards = QListWidget()
        document_cards.setObjectName("DocumentCards")
        document_cards.setSpacing(8)
        document_cards.itemClicked.connect(lambda item, view=view_name: self._on_document_card_clicked(item, view))

        compare_table = QTableWidget()
        compare_table.setColumnCount(2)
        compare_table.setHorizontalHeaderLabels(["欄位名稱", "結果"])
        compare_table.setObjectName("CompareTable")
        compare_table.verticalHeader().setVisible(False)
        compare_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        compare_table.setSortingEnabled(True)
        compare_table.setMinimumHeight(260)

        compare_search = QLineEdit()
        compare_search.setPlaceholderText("搜尋欄位或文件")
        compare_search.setObjectName("CompareSearch")
        compare_only_issues = QCheckBox("只看待確認 / 異常")
        compare_only_issues.setChecked(False)
        compare_search.textChanged.connect(lambda _text, view=view_name: self._apply_compare_filters(view))
        compare_only_issues.toggled.connect(lambda _checked, view=view_name: self._apply_compare_filters(view))

        audit_report_view = QTextEdit()
        audit_report_view.setReadOnly(True)
        audit_report_view.setObjectName("AuditReportView")
        audit_report_view.setPlaceholderText("完成文件讀取後，這裡會產生正式報關核對報告")
        audit_report_view.setMaximumHeight(210)

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

        left_panel = QFrame()
        left_panel.setObjectName("AuditSidePanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        left_title = QLabel("報關案件文件區")
        left_title.setObjectName("PanelTitle")
        left_layout.addWidget(left_title)
        left_layout.addWidget(document_status_bar)
        left_layout.addWidget(document_cards, 1)

        audit_workspace = QFrame()
        audit_workspace.setObjectName("AuditWorkspace")
        center = QVBoxLayout(audit_workspace)
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(10)
        status_line = QHBoxLayout()
        status_label = QLabel("● 等待文件")
        status_label.setObjectName("AuditStatusBadge")
        status_line.addWidget(status_label)
        status_line.addStretch(1)
        status_line.addWidget(status_bar)
        center.addLayout(status_line)

        report_title = QLabel("案件摘要 / AI 建議")
        report_title.setObjectName("PanelTitle")
        center.addWidget(report_title)
        center.addWidget(audit_report_view)
        table_tools = QHBoxLayout()
        table_title = QLabel("海關核對差異表")
        table_title.setObjectName("PanelTitle")
        table_tools.addWidget(table_title)
        table_tools.addStretch(1)
        table_tools.addWidget(compare_search)
        table_tools.addWidget(compare_only_issues)
        center.addLayout(table_tools)
        center.addWidget(compare_table, 4)

        risk_panel = QFrame()
        risk_panel.setObjectName("AuditSummaryPanel")
        summary_layout = QVBoxLayout(risk_panel)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(8)
        right_title = QLabel("異常摘要 / 高風險提示")
        right_title.setObjectName("PanelTitle")
        summary_layout.addWidget(right_title)
        summary_layout.addWidget(audit_summary)
        summary_layout.addWidget(debug_toggle)
        summary_layout.addWidget(self.workflow_debug)
        center.addWidget(risk_panel, 1)
        self.workflow_debug.hide()
        debug_toggle.setVisible(self.settings.developer_mode)

        body.addWidget(left_panel)
        body.addWidget(audit_workspace)
        body.setStretchFactor(0, 35)
        body.setStretchFactor(1, 65)
        body.setSizes([460, 860])
        layout.addWidget(body, 1)
        self.workflow_views[view_name] = {
            "tree": None,
            "document_cards": document_cards,
            "table": compare_table,
            "audit_report": audit_report_view,
            "summary": audit_summary,
            "audit_status_label": status_label,
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
        self.status_build.setObjectName("StatusVersion")
        self.status_build.setText(self._format_build_badge())
        self.status_build.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_update.setObjectName("StatusMessage")
        self.status_check_update_button.setObjectName("SecondaryButton")
        self.status_check_update_button.clicked.connect(lambda: self._check_updates(interactive=True))
        self.updater_debug_info.setObjectName("UpdaterDebugInfo")
        self.updater_debug_info.setWordWrap(True)
        self.updater_debug_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addWidget(self.status_dot)
        layout.addWidget(self.status_channel)
        layout.addWidget(self.status_version)
        layout.addSpacing(10)
        layout.addWidget(self.status_build)
        layout.addSpacing(14)
        layout.addWidget(self.status_update)
        layout.addWidget(self.status_check_update_button)
        layout.addSpacing(18)
        layout.addWidget(self.updater_debug_info, 1)
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

    def _choose_workflow_folder(self, direction: str = "import", view_name: str = "case") -> None:
        folder = QFileDialog.getExistingDirectory(self, "選擇報關文件資料夾", "")
        if folder:
            self._run_workflow([folder], direction, view_name, intake_mode="folder")

    def _run_workflow(
        self,
        paths: list[str],
        direction: str = "import",
        view_name: str = "case",
        intake_mode: str = "files",
    ) -> None:
        if intake_mode == "files":
            folder_paths = [path for path in paths if Path(path).is_dir()]
            file_paths = [path for path in paths if not Path(path).is_dir()]
            if folder_paths and not file_paths and len(folder_paths) == 1:
                intake_mode = "folder"
            elif folder_paths:
                expanded: list[str] = []
                for folder in folder_paths:
                    expanded.extend(str(item) for item in Path(folder).rglob("*") if item.is_file())
                paths = file_paths + expanded
        if self.workflow_thread and self.workflow_thread.isRunning():
            self._show_toast("工作流處理中", "目前文件仍在處理。", action_visible=False, timeout_ms=3000)
            return
        view = self.workflow_views.get(view_name, {})
        case_list = view.get("case_list")
        tree = view.get("tree")
        document_cards = view.get("document_cards")
        table = view.get("table")
        audit_report = view.get("audit_report")
        summary = view.get("summary")
        debug = view.get("debug")
        upload = view.get("upload")
        if isinstance(upload, QListWidget):
            upload.clear()
            for path in paths:
                upload.addItem(path)
            upload.addItem(f"已加入 {len(paths)} 份文件")
            if intake_mode == "folder":
                upload.addItem("已加入 1 個資料夾，將自動掃描並建立核對流程")
        if isinstance(case_list, QTableWidget):
            case_list.setRowCount(1)
            for col, value in enumerate(["processing", "處理中", "-", "-", "-", str(len(paths)), "-", "-"]):
                case_list.setItem(0, col, QTableWidgetItem(value))
        if isinstance(tree, QTreeWidget):
            tree.clear()
        if isinstance(document_cards, QListWidget):
            document_cards.clear()
        if isinstance(table, QTableWidget):
            table.setRowCount(0)
        if isinstance(audit_report, QTextEdit):
            audit_report.setText("文件處理中...\n\n系統正在讀取文件、辨識種類、建立案件並進行報關核對。")
        if isinstance(summary, QTextEdit):
            summary.setText("文件核對中，完成後會列出需人工確認或高風險項目。")
        if isinstance(debug, QTextEdit):
            debug.clear()
        self._reset_workflow_progress(view_name)
        self._set_workflow_progress(view_name, "Upload", 3, "文件已加入核對流程")

        self.workflow_thread = QThread(self)
        self.workflow_thread.setProperty("workflow_view", view_name)
        self.workflow_worker = WorkflowRunWorker(paths, direction, intake_mode=intake_mode)
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
                summary.setText(f"⚠ {self._human_workflow_message(stage, message)}")
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
        runtime_log = logs_dir() / "runtime.log"
        if not self.settings.developer_mode:
            return (
                "AI Customs Audit Report\n\n"
                "核對結果：✗ 系統處理中斷\n\n"
                "說明：文件讀取或核對流程未完成，請先確認檔案是否可開啟、格式是否正確，再重新上傳。\n\n"
                f"需處理事項：{self._human_workflow_message(stage, message)}"
            )
        return (
            f"❌ {stage} failed\n\n"
            f"原因:\n{message}\n\n"
            "Pipeline 已停止，避免畫面永久停在 loading 狀態。\n\n"
            f"Runtime log:\n{runtime_log}\n\n"
            f"Exception log:\n{details}"
        )

    def _reset_workflow_progress(self, view_name: str) -> None:
        view = self.workflow_views.get(view_name, {})
        for key, text in (
            ("upload_progress", "Upload 0%"),
            ("ocr_progress", "OCR 0%"),
            ("workflow_progress", "AI Audit 0%"),
        ):
            progress = view.get(key)
            if isinstance(progress, QProgressBar):
                progress.setValue(0)
                progress.setFormat(text)
        steps = view.get("status_steps")
        if isinstance(steps, list):
            for label in steps:
                if isinstance(label, QLabel):
                    label.setProperty("state", "pending")
                    label.setToolTip("")
                    label.style().unpolish(label)
                    label.style().polish(label)

    def _set_workflow_progress(self, view_name: str, stage: str, percent: int, message: str) -> None:
        view = self.workflow_views.get(view_name, {})
        display_message = self._human_workflow_message(stage, message)
        upload_progress = view.get("upload_progress")
        ocr_progress = view.get("ocr_progress")
        workflow_progress = view.get("workflow_progress")
        percent = max(0, min(100, int(percent)))
        if isinstance(upload_progress, QProgressBar):
            upload_value = 100 if percent >= 8 else int(percent * 100 / 8)
            upload_progress.setValue(upload_value)
            upload_progress.setFormat(f"Upload {upload_value}%")
        if isinstance(ocr_progress, QProgressBar):
            if percent < 8:
                ocr_value = 0
            elif percent >= 35:
                ocr_value = 100
            else:
                ocr_value = int((percent - 8) * 100 / 27)
            ocr_progress.setValue(min(100, ocr_value))
            ocr_progress.setFormat(f"OCR {min(100, ocr_value)}%")
        if isinstance(workflow_progress, QProgressBar):
            workflow_value = 0 if percent < 35 else int((percent - 35) * 100 / 65)
            workflow_progress.setValue(min(100, workflow_value))
            workflow_progress.setFormat(f"AI Audit {min(100, workflow_value)}%")
        steps = view.get("status_steps")
        if isinstance(steps, list):
            stage_index = {
                "Upload": 0,
                "OCR": 1,
                "Document Split": 1,
                "parser": 1,
                "Type Detection": 1,
                "workflow grouping": 2,
                "Workflow Match": 2,
                "audit": 2,
                "Audit": 2,
                "Completed": 3,
                "workflow pipeline": 3,
            }
            active_index = stage_index.get(stage, -1)
            if stage == "Exception":
                active_index = len(steps) - 1
            for index, label in enumerate(steps):
                if not isinstance(label, QLabel):
                    continue
                state = "done" if index < active_index else "active" if index == active_index else "pending"
                if (stage == "Exception" or "failed" in message.lower() or "timeout" in message.lower()) and index == active_index:
                    state = "error"
                label.setProperty("state", state)
                label.setToolTip(display_message)
                label.style().unpolish(label)
                label.style().polish(label)

    def _human_workflow_message(self, stage: str, message: str) -> str:
        text = f"{stage} {message}".strip()
        replacements = {
            "parser": "文件辨識",
            "workflow grouping": "自動分組",
            "workflow pipeline": "案件核對流程",
            "pipeline": "處理流程",
            "audit": "自動核對",
            "Completed": "完成",
            "Upload": "上傳",
            "Document Split": "文件整理",
            "Type Detection": "文件辨識",
            "Workflow Match": "自動分組",
        }
        for raw, label in replacements.items():
            text = text.replace(raw, label)
        if "WARNING_" in text or "COMPARE_" in text:
            return "系統偵測到需人工確認的核對項目"
        return text

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
                    debug.setText("未建立案件。請確認文件內是否包含可辨識的 INV / B/L / Booking / DS2 資訊。")
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
        document_cards = view.get("document_cards")
        table = view.get("table")
        audit_report = view.get("audit_report")
        summary = view.get("summary")
        debug = view.get("debug")
        audit_status_label = view.get("audit_status_label")
        self.current_workflow_cases[view_name] = case
        self._render_document_status_bar(case, view_name)
        self._update_workflow_section_states(case, view_name)
        if isinstance(document_cards, QListWidget):
            self._populate_document_cards(document_cards, case)
        if isinstance(tree, QTreeWidget):
            tree.clear()
            vm = self._case_view_model(case)
            root = QTreeWidgetItem([f"案件：{vm.case_id}", vm.status, "", ""])
            tree.addTopLevelItem(root)
            for item in self._document_checklist_items(case):
                root.addChild(item)
            for item in self._manual_review_items(case):
                root.addChild(item)
            root.setExpanded(True)

        if isinstance(table, QTableWidget):
            self._populate_compare_table(table, case)
            self._apply_compare_filters(view_name)
        if isinstance(audit_report, QTextEdit):
            audit_report.setText(self._format_case_workspace_summary(case))
        if isinstance(summary, QTextEdit):
            summary.setText(self._format_risk_summary(case))
        if isinstance(audit_status_label, QLabel):
            audit_status_label.setText(self._audit_status_badge(case))
            audit_status_label.setProperty("state", self._case_status_key(case))
            audit_status_label.style().unpolish(audit_status_label)
            audit_status_label.style().polish(audit_status_label)
        elif isinstance(summary, QLabel):
            summary.setText(self._format_audit_summary_card(case))
        if isinstance(debug, QTextEdit):
            debug.setText(self._format_case_debug(case))

    def _render_workflow_result_without_case(self, result: WorkflowResult, view_name: str = "case") -> None:
        view = self.workflow_views.get(view_name, {})
        audit_report = view.get("audit_report")
        summary = view.get("summary")
        table = view.get("table")
        document_cards = view.get("document_cards")
        audit_status_label = view.get("audit_status_label")
        if isinstance(table, QTableWidget):
            table.setRowCount(0)
        if isinstance(document_cards, QListWidget):
            self._populate_intake_document_cards(document_cards, result)
        if isinstance(audit_status_label, QLabel):
            audit_status_label.setText("● 需補件或人工確認")
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
            "案件摘要",
            "核對狀態：⚠ 需人工確認",
            "風險等級：中風險",
            "",
            "原因：",
            "目前已完成文件讀取，但尚未建立可完整核對的案件。",
            "",
            "文件完整性：",
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
            "AI 建議：",
            "系統已完成文件讀取，但缺少足夠的單號或必要文件，因此尚不能產生船名航次、件數、重量、CIF、稅則等完整核對段落。",
        ])
        return "\n".join(lines)

    def _format_case_workspace_summary(self, case: CaseWorkflow) -> str:
        status_key = self._case_status_key(case)
        status = {
            "completed": "✓ 可進行報關核對",
            "missing_docs": "⚠ 需補件",
            "exception": "⚠ 需人工確認",
            "processing": "⚠ 需人工確認",
        }.get(status_key, "⚠ 需人工確認")
        risk = self._risk_level_label(case)
        reasons = self._risk_reason_lines(case)
        completeness = self._document_completeness_lines(case)
        lines = [
            f"案件：{case.match_keys.get('customer') or case.match_keys.get('invoice_no') or case.case_id}",
            f"核對狀態：{status}",
            f"風險等級：{risk}",
            "",
            "原因：",
            *(reasons or ["目前未發現阻擋核對的重大異常。"]),
            "",
            "文件完整性：",
            *completeness,
            "",
            "AI 建議：",
            self._ai_recommendation(case),
        ]
        return "\n".join(lines)

    def _risk_level_label(self, case: CaseWorkflow) -> str:
        if case.missing_documents:
            return "中風險"
        if case.audit_report and any(result.status in {CheckStatus.MISMATCH, CheckStatus.HIGH_RISK} for result in case.audit_report.results):
            return "高風險"
        if case.audit_report and any(result.status == CheckStatus.MISSING for result in case.audit_report.results):
            return "中風險"
        return "低風險"

    def _risk_reason_lines(self, case: CaseWorkflow) -> list[str]:
        lines: list[str] = []
        if case.missing_documents:
            lines.append(f"缺少 {'、'.join(self._human_document_name(name) for name in case.missing_documents)}，目前尚無法完成最終海關核對。")
        if case.manual_confirm_queue:
            lines.append("已收到部分疑似文件，但辨識信心不足，需人工確認文件類型。")
        if case.audit_report:
            mismatches = [
                FIELD_LABELS.get(result.field.value, result.field.value)
                for result in case.audit_report.results
                if result.status in {CheckStatus.MISMATCH, CheckStatus.HIGH_RISK}
            ]
            if mismatches:
                lines.append(f"{'、'.join(dict.fromkeys(mismatches))} 需人工確認。")
        return lines

    def _ai_recommendation(self, case: CaseWorkflow) -> str:
        if case.missing_documents:
            return "請先補齊缺少文件，再進行稅則、金額、重量與船名航次最終核對。"
        if case.audit_report and any(result.status in {CheckStatus.MISMATCH, CheckStatus.HIGH_RISK} for result in case.audit_report.results):
            return "請優先確認紅色差異欄位，必要時回查發票、裝箱單與報單原始資料。"
        return "目前主要欄位未見重大異常，可進入人工覆核與歸檔。"

    def _document_completeness_lines(self, case: CaseWorkflow) -> list[str]:
        labels = {
            DocumentType.INVOICE.value: "INV",
            DocumentType.PACKING_LIST.value: "PACKING",
            DocumentType.BILL_OF_LADING.value: "B/L",
            DocumentType.DS2_DECLARATION.value: "報單",
            DocumentType.EXPORT_DECLARATION.value: "報單",
        }
        present = {
            self._segment_effective_type(segment).value
            for segment in case.documents
        }
        required = [DocumentType.INVOICE.value, DocumentType.PACKING_LIST.value, DocumentType.BILL_OF_LADING.value]
        required.append(DocumentType.EXPORT_DECLARATION.value if case.direction == "export" else DocumentType.DS2_DECLARATION.value)
        candidate_present = set(case.fallback_document_candidates)
        lines = []
        for key in required:
            if key in present:
                lines.append(f"✓ {labels.get(key, key)}")
            elif key in candidate_present:
                lines.append(f"⚠ 疑似 {labels.get(key, key)}，待人工確認")
            else:
                lines.append(f"✗ {labels.get(key, key)}")
        return lines

    def _audit_status_badge(self, case: CaseWorkflow) -> str:
        if self._case_status_key(case) == "completed":
            return "● 已完成"
        if case.missing_documents:
            return "● 需補件"
        return "● AI 核對中"

    def _infer_missing_documents_from_segments(self, result: WorkflowResult) -> list[str]:
        found = {
            self._document_label(segment.parsed.document_type if segment.parsed else segment.detected_type)
            for segment in result.segments
        }
        candidate_found = {
            self._document_label(candidate.document_type)
            for segment in result.segments
            for candidate in segment.candidates
            if candidate.document_type != DocumentType.UNKNOWN and candidate.confidence >= 0.30
        }
        found |= candidate_found
        required = ["DS2 報單", "INV", "PKG", "B/L"] if result.direction != "export" else ["出口報單", "INV", "PKG", "BOOKING", "B/L"]
        return [name for name in required if name not in found and not (name == "PKG" and "PL / PKG" in found)]

    def _populate_document_cards(self, list_widget: QListWidget, case: CaseWorkflow) -> None:
        list_widget.clear()
        groups = self._document_groups(case)
        order = [
            ("invoice", "✓ 發票 INV"),
            ("packing", "✓ 包裝單 PACKING"),
            ("arrival_notice", "⚠ 到貨通知"),
            ("delivery_order", "⚠ D/O"),
            ("shipping_order", "⚠ SO"),
            ("booking", "⚠ Booking"),
            ("bl", "✓ B/L"),
            ("declaration", "⚠ 報單"),
            ("tax_sheet", "⚠ 稅單"),
            ("clearance_list", "⚠ 清表"),
            ("drawback_standard", "⚠ 核退標準"),
            ("unknown", "⚠ 尚未成功辨識"),
        ]
        for key, title in order:
            files = groups.get(key, [])
            text = self._document_card_text(key, title, files, case)
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, {"type": key, "files": files})
            item.setSizeHint(item.sizeHint().expandedTo(item.sizeHint()))
            list_widget.addItem(item)

    def _populate_intake_document_cards(self, list_widget: QListWidget, result: WorkflowResult) -> None:
        list_widget.clear()
        for segment in result.segments:
            parsed = segment.parsed
            doc_type = parsed.document_type if parsed else segment.detected_type
            label = "尚未成功辨識" if doc_type == DocumentType.UNKNOWN else self._document_label(doc_type)
            item = QListWidgetItem(f"⚠ {label}\n{segment.source_name}\n可能為掃描品質、格式或文件內容不足，請人工確認。")
            item.setData(Qt.ItemDataRole.UserRole, {"type": doc_type.value, "files": [segment.source_name]})
            list_widget.addItem(item)
        if not result.segments:
            list_widget.addItem(QListWidgetItem("⚠ 尚未成功辨識\n請確認檔案是否可開啟，或重新上傳較清楚的文件。"))

    def _document_groups(self, case: CaseWorkflow) -> dict[str, list[str]]:
        groups = {
            "invoice": [],
            "packing": [],
            "arrival_notice": [],
            "delivery_order": [],
            "shipping_order": [],
            "booking": [],
            "bl": [],
            "declaration": [],
            "tax_sheet": [],
            "clearance_list": [],
            "drawback_standard": [],
            "unknown": [],
        }
        for segment in case.documents:
            doc_type = self._segment_effective_type(segment)
            suffix = ""
            best = segment.candidates[0] if segment.candidates else None
            if best and best.needs_manual_confirm:
                reason = segment.manual_confirm_reason or "AI 辨識信心不足，需人工確認"
                suffix = f"\nAI 信心：{int(best.confidence * 100)}%\n狀態：需人工確認\n原因：{reason}"
            if doc_type == DocumentType.INVOICE:
                groups["invoice"].append(segment.source_name + suffix)
            elif doc_type == DocumentType.PACKING_LIST:
                groups["packing"].append(segment.source_name + suffix)
            elif doc_type in {DocumentType.DS2_DECLARATION, DocumentType.EXPORT_DECLARATION}:
                groups["declaration"].append(segment.source_name + suffix)
            elif doc_type == DocumentType.BILL_OF_LADING:
                groups["bl"].append(segment.source_name + suffix)
            elif doc_type == DocumentType.ARRIVAL_NOTICE:
                groups["arrival_notice"].append(segment.source_name + suffix)
            elif doc_type == DocumentType.SHIPPING_ORDER:
                groups["shipping_order"].append(segment.source_name + suffix)
            elif doc_type in {DocumentType.BOOKING, DocumentType.BOOKING_CONFIRMATION}:
                groups["booking"].append(segment.source_name + suffix)
            elif doc_type == DocumentType.TAX_SHEET:
                groups["tax_sheet"].append(segment.source_name + suffix)
            elif doc_type in {DocumentType.CLEARANCE_LIST, DocumentType.DATA_CLEARANCE, DocumentType.MATERIAL_CLEARANCE}:
                groups["clearance_list"].append(segment.source_name + suffix)
            elif doc_type == DocumentType.DRAWBACK_CLEARANCE:
                groups["drawback_standard"].append(segment.source_name + suffix)
            elif doc_type == DocumentType.UNKNOWN:
                groups["unknown"].append(segment.source_name)
        for document_key, names in case.fallback_document_candidates.items():
            key = self._source_to_evidence_key(document_key)
            if key in groups and not groups[key]:
                groups[key].extend(f"疑似文件：{name}" for name in names)
        return groups

    def _segment_effective_type(self, segment) -> DocumentType:
        parsed = segment.parsed
        if parsed and parsed.document_type != DocumentType.UNKNOWN:
            return parsed.document_type
        if segment.detected_type != DocumentType.UNKNOWN:
            return segment.detected_type
        if segment.candidates:
            best = segment.candidates[0]
            if best.confidence >= (0.30 if best.document_type in {DocumentType.DS2_DECLARATION, DocumentType.EXPORT_DECLARATION} else 0.42):
                return best.document_type
        return DocumentType.UNKNOWN

    def _document_card_text(self, key: str, title: str, files: list[str], case: CaseWorkflow) -> str:
        missing_titles = {
            "invoice": "✗ 發票 INV\n尚未提供",
            "packing": "✗ 包裝單 PACKING\n尚未提供",
            "declaration": "⚠ 報單\n尚未成功辨識\n可能為掃描品質或格式問題",
            "bl": "✗ B/L\n尚未提供",
            "arrival_notice": "",
            "delivery_order": "",
            "shipping_order": "",
            "booking": "",
            "tax_sheet": "",
            "clearance_list": "",
            "drawback_standard": "",
            "unknown": "",
        }
        if not files:
            return missing_titles.get(key, "")
        if key == "unknown":
            return "⚠ 尚未成功辨識\n" + "\n".join(files[:4]) + "\n可能為掃描品質、格式或文件內容不足，請人工確認。"
        status_title = title
        if key == "declaration":
            warning = any("需人工確認" in file or "疑似文件" in file for file in files)
            status_title = "⚠ 已收到疑似 DS2 報單" if warning else "✓ 報單"
        elif key == "bl":
            status_title = "✓ B/L"
        return status_title + "\n" + "\n".join(files[:5])

    def _on_document_card_clicked(self, item: QListWidgetItem, view_name: str = "case") -> None:
        view = self.workflow_views.get(view_name, {})
        audit_report = view.get("audit_report")
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(audit_report, QTextEdit) or not isinstance(data, dict):
            return
        files = data.get("files") or []
        doc_type = str(data.get("type", ""))
        title = self._human_document_name(doc_type)
        if doc_type == "unknown":
            title = "尚未成功辨識"
        lines = [
            f"文件：{title}",
            "",
            "文件內容：",
            *([f"- {name}" for name in files] if files else ["- 尚未提供"]),
            "",
            "AI 解析結果：",
            "請查看下方差異核對表與右側高風險提示；若此文件尚未成功辨識，建議重新提供較清晰掃描或原始 PDF。",
            "",
            "差異核對：",
            "此文件已納入本案欄位比對。請優先查看紅色與黃色欄位。",
        ]
        audit_report.setText("\n".join(lines))

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
        if case.missing_documents:
            for missing in case.missing_documents:
                lines.append(f"✗ 缺少 {self._human_document_name(missing)}")
        for item in case.manual_confirm_queue:
            lines.append(f"⚠ {self._humanize_warning(item)}")
        if case.audit_report:
            for result in case.audit_report.results:
                if result.status == CheckStatus.MISMATCH:
                    lines.append(f"✗ {FIELD_LABELS.get(result.field.value, result.field.value)} 不一致")
                elif result.status == CheckStatus.MISSING:
                    lines.append(f"✗ {FIELD_LABELS.get(result.field.value, result.field.value)} 資料不足")
                elif result.status == CheckStatus.HIGH_RISK:
                    lines.append(f"⚠ {FIELD_LABELS.get(result.field.value, result.field.value)} 高風險")
            lines.extend(f"⚠ {self._humanize_warning(warning)}" for warning in case.audit_report.high_risk_warnings)
        lines.extend(f"⚠ {self._humanize_warning(finding)}" for finding in case.rule_findings)
        if not lines:
            lines.append("✓ 目前未發現需要立即處理的高風險項目。")
        return "\n".join(dict.fromkeys(lines))

    def _human_document_name(self, value: str) -> str:
        text = str(value)
        mapping = {
            "DS2_DECLARATION": "DS2 報單",
            "EXPORT_DECLARATION": "出口報單",
            "BILL_OF_LADING": "B/L",
            "PACKING_LIST": "PACKING",
            "INVOICE": "INV",
            "ARRIVAL_NOTICE": "到貨通知",
            "SHIPPING_ORDER": "SO",
            "BOOKING_CONFIRMATION": "Booking",
            "BOOKING": "Booking",
            "TAX_SHEET": "稅單",
            "CLEARANCE_LIST": "清表",
            "DATA_CLEARANCE": "資料清表",
            "MATERIAL_CLEARANCE": "用料清表",
            "DRAWBACK_CLEARANCE": "核退標準",
            "arrival_notice": "到貨通知",
            "delivery_order": "D/O",
            "shipping_order": "SO",
            "tax_sheet": "稅單",
            "clearance_list": "清表",
            "material_clearance": "用料清表",
            "drawback_standard": "核退標準",
            "declaration": "報單",
        }
        for raw, label in mapping.items():
            text = text.replace(raw, label)
        return text.replace("_", " ")

    def _humanize_warning(self, value: str) -> str:
        text = self._human_document_name(value)
        replacements = {
            "WARNING_GLOBAL_DECLARATION_IS_CORE": "報單為核心文件，請確認報單資料是否為正式版本",
            "COMPARE_COMMON_FIELDS": "共通欄位需人工確認",
            "declaration core": "報單核心資料",
            "workflow grouping": "案件分組",
            "parser": "文件讀取",
            "semantic": "內容比對",
            "pipeline": "處理流程",
        }
        for raw, label in replacements.items():
            text = text.replace(raw, label)
        if "WARNING_" in text or "COMPARE_" in text:
            return "文件需人工確認"
        if "traceback" in text.casefold():
            return "處理細節已寫入 logs/runtime.log"
        return text

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
            self._segment_effective_type(segment).value: segment
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
                candidates = case.fallback_document_candidates.get(document_key, [])
                if candidates:
                    items.append((f"{label} ⚠", "warning", f"AI低信心待確認: {', '.join(candidates)}"))
                else:
                    items.append((f"{label} ✗", "missing", "缺少此文件"))
            elif segment.document_confidence < 0.78 or segment.manual_confirm_reason:
                items.append((f"{label} ⚠", "warning", f"AI低信心待確認: {segment.source_name}"))
            else:
                items.append((f"{label} ✓", "ok", f"已確認文件: {segment.source_name}"))
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
            self._segment_effective_type(segment).value: segment
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
                status = "✓ 已確認文件" if segment.document_confidence >= 0.78 and not segment.manual_confirm_reason else "⚠ AI低信心待確認"
                display = f"{'✓' if status.startswith('✓') else '⚠'} {document_label} 已讀取"
                item = QTreeWidgetItem([display, status, segment.source_name, f"{segment.page_start}-{segment.page_end}"])
                item.setToolTip(1, "文件已納入本案核對")
                if segment.document_confidence < 0.55:
                    item.setBackground(1, QBrush(QColor("#FFF3CD")))
            else:
                candidates = case.fallback_document_candidates.get(document_key, [])
                if candidates:
                    item = QTreeWidgetItem([f"⚠ 疑似 {document_label}", "AI低信心待確認", "、".join(candidates), "-"])
                    item.setToolTip(1, "已收到疑似文件，但辨識信心不足")
                    item.setBackground(1, QBrush(QColor("#FFF3CD")))
                    items.append(item)
                    continue
                item = QTreeWidgetItem([f"✗ 缺少 {document_label}", "待補", "-", "-"])
                item.setToolTip(1, "缺少此文件，需補件後才能完整核對")
                item.setBackground(1, QBrush(QColor("#F8D7DA")))
            items.append(item)
        extra_segments = [
            segment for segment in case.documents
            if self._segment_effective_type(segment).value not in required_keys
        ]
        for segment in extra_segments:
            document_type = self._segment_effective_type(segment)
            items.append(QTreeWidgetItem([f"✓ {self._document_label(document_type)} 已讀取", "已收到", segment.source_name, f"{segment.page_start}-{segment.page_end}"]))
        return items

    def _manual_review_items(self, case: CaseWorkflow) -> list[QTreeWidgetItem]:
        items: list[QTreeWidgetItem] = []
        high_risk_fields: list[str] = []
        if case.audit_report:
            for result in case.audit_report.results:
                if result.status in {CheckStatus.MISMATCH, CheckStatus.HIGH_RISK}:
                    high_risk_fields.append(FIELD_LABELS.get(result.field.value, result.field.value))
        for label in dict.fromkeys(high_risk_fields):
            item = QTreeWidgetItem([f"⚠ {label}待人工確認", "需確認", "-", "-"])
            item.setBackground(1, QBrush(QColor("#FFF3CD")))
            items.append(item)
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
        columns = self._evidence_columns(case, results)
        headers = ["欄位名稱", *[label for _key, label in columns], "結果"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        if not results:
            fallback_rows: list[list[str]] = []
            if case.missing_documents:
                for missing in case.missing_documents:
                    fallback_rows.append([self._human_document_name(missing), *["未提供" for _ in columns], "✗ 待補件"])
            for document_type, names in case.fallback_document_candidates.items():
                values = ["-" for _ in columns]
                for index, (key, _label) in enumerate(columns):
                    if key == document_type:
                        values[index] = "；".join(names[:3])
                fallback_rows.append([self._human_document_name(document_type), *values, "⚠ 已收到疑似文件，待人工確認"])
            if case.rule_findings:
                fallback_rows.extend(["人工確認", *["-" for _ in columns], self._humanize_warning(finding)] for finding in case.rule_findings)
            if not fallback_rows:
                fallback_rows.append(["欄位核對", *["-" for _ in columns], "⚠ 文件不足，待補件"])
            table.setRowCount(len(fallback_rows))
            for row, cells in enumerate(fallback_rows):
                for col, value in enumerate(cells):
                    item = QTableWidgetItem(value)
                    self._style_table_item(item, "warning" if col == table.columnCount() - 1 else "neutral")
                    if col == table.columnCount() - 1:
                        item.setBackground(QBrush(QColor("#FFF3CD")))
                    table.setItem(row, col, item)
            table.setSortingEnabled(True)
            table.resizeColumnsToContents()
            return
        table.setRowCount(len(results))
        color_by_status = {
            CheckStatus.MATCH: "#D9F2E3",
            CheckStatus.MISSING: "#FFF3CD",
            CheckStatus.MISMATCH: "#F8D7DA",
            CheckStatus.HIGH_RISK: "#F8D7DA",
        }
        label_by_status = {
            CheckStatus.MATCH: "✓ 一致",
            CheckStatus.MISSING: "⚠ 無法確認",
            CheckStatus.MISMATCH: "✗ 不一致",
            CheckStatus.HIGH_RISK: "⚠ 高風險",
        }
        for row, result in enumerate(results):
            by_type = self._document_values_for_field(case, result.field)
            cells = [FIELD_LABELS.get(result.field.value, result.field.value)]
            cells.extend(by_type.get(key, "-") for key, _label in columns)
            cells.append(self._audit_result_label(result, label_by_status.get(result.status, result.status.value)))
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                item.setToolTip(result.message)
                self._style_table_item(item, self._status_style_key(result.status))
                table.setItem(row, col, item)
            status_item = table.item(row, table.columnCount() - 1)
            status_item.setToolTip(result.status.value)
            status_item.setBackground(QBrush(QColor(color_by_status.get(result.status, "#1B2530"))))
            if result.status in {CheckStatus.MISMATCH, CheckStatus.HIGH_RISK}:
                for col in range(table.columnCount()):
                    cell = table.item(row, col)
                    if cell:
                        cell.setBackground(QBrush(QColor("#F8D7DA")))
            elif result.status == CheckStatus.MISSING:
                for col in range(table.columnCount()):
                    cell = table.item(row, col)
                    if cell:
                        cell.setBackground(QBrush(QColor("#FFF3CD")))
        table.setSortingEnabled(True)
        table.resizeColumnsToContents()

    def _document_values_for_field(self, case: CaseWorkflow, field) -> dict[str, str]:
        values: dict[str, str] = {}
        for segment in case.documents:
            parsed = segment.parsed
            if not parsed:
                continue
            value = self._parsed_field_value(parsed, field)
            if not value:
                continue
            key = self._evidence_key(self._segment_effective_type(segment))
            if key:
                values[key] = value
        if values:
            return values
        report = case.audit_report
        if report:
            for result in report.results:
                if result.field != field:
                    continue
                for source, value in result.document_values.items():
                    key = self._source_to_evidence_key(source)
                    if key:
                        values[key] = value
                break
        return values

    def _evidence_columns(self, case: CaseWorkflow, results) -> list[tuple[str, str]]:
        order = [
            DocumentType.INVOICE,
            DocumentType.PACKING_LIST,
            DocumentType.SHIPPING_ORDER,
            DocumentType.BOOKING,
            DocumentType.BILL_OF_LADING,
            DocumentType.ARRIVAL_NOTICE,
            DocumentType.DS2_DECLARATION,
            DocumentType.EXPORT_DECLARATION,
            DocumentType.TAX_SHEET,
            DocumentType.CLEARANCE_LIST,
            DocumentType.MATERIAL_CLEARANCE,
            DocumentType.DRAWBACK_CLEARANCE,
        ]
        keys: list[str] = []
        labels: dict[str, str] = {}
        for document_type in order:
            key = self._evidence_key(document_type)
            if key:
                labels[key] = self._document_label(document_type)
        labels["declaration"] = "出口報單" if case.direction == "export" else "DS2 報單"
        for segment in case.documents:
            key = self._evidence_key(self._segment_effective_type(segment))
            if key and key not in keys:
                keys.append(key)
        for document_type in case.fallback_document_candidates:
            key = self._source_to_evidence_key(document_type)
            if key and key not in keys:
                keys.append(key)
        if results:
            for result in results:
                for source in result.document_values:
                    key = self._source_to_evidence_key(source)
                    if key and key not in keys:
                        keys.append(key)
        if case.direction != "export":
            for document_type in (DocumentType.INVOICE, DocumentType.PACKING_LIST, DocumentType.ARRIVAL_NOTICE, DocumentType.DS2_DECLARATION):
                key = self._evidence_key(document_type)
                if key and key not in keys and (key == "declaration" or key in case.fallback_document_candidates):
                    keys.append(key)
        ordered_keys = [self._evidence_key(document_type) for document_type in order]
        keys.sort(key=lambda key: ordered_keys.index(key) if key in ordered_keys else 999)
        return [(key, labels.get(key, self._human_document_name(key))) for key in keys if key]

    def _evidence_key(self, document_type: DocumentType) -> str:
        mapping = {
            DocumentType.INVOICE: "invoice",
            DocumentType.PACKING_LIST: "packing",
            DocumentType.BILL_OF_LADING: "bl",
            DocumentType.ARRIVAL_NOTICE: "arrival_notice",
            DocumentType.SHIPPING_ORDER: "shipping_order",
            DocumentType.BOOKING: "booking",
            DocumentType.BOOKING_CONFIRMATION: "booking",
            DocumentType.DS2_DECLARATION: "declaration",
            DocumentType.EXPORT_DECLARATION: "declaration",
            DocumentType.TAX_SHEET: "tax_sheet",
            DocumentType.CLEARANCE_LIST: "clearance_list",
            DocumentType.DATA_CLEARANCE: "clearance_list",
            DocumentType.MATERIAL_CLEARANCE: "material_clearance",
            DocumentType.DRAWBACK_CLEARANCE: "drawback_standard",
        }
        return mapping.get(document_type, "")

    def _source_to_evidence_key(self, source: str) -> str:
        text = str(source).casefold()
        if "invoice" in text or "inv" in text or "發票" in text:
            return "invoice"
        if "pack" in text or "pkg" in text or "packing" in text or "裝箱" in text or "包裝" in text:
            return "packing"
        if "arrival" in text or "到貨" in text or "抵港" in text:
            return "arrival_notice"
        if "d/o" in text or "delivery order" in text or "提貨" in text:
            return "delivery_order"
        if "s/o" in text or "shipping order" in text:
            return "shipping_order"
        if "booking" in text or "訂艙" in text:
            return "booking"
        if "b/l" in text or "bl" in text or "lading" in text or "提單" in text:
            return "bl"
        if "ds2" in text or "declaration" in text or "報單" in text:
            return "declaration"
        if "稅單" in text or "tax" in text or "duty" in text:
            return "tax_sheet"
        if "核退" in text:
            return "drawback_standard"
        if "用料" in text:
            return "material_clearance"
        if "清表" in text:
            return "clearance_list"
        return ""

    def _status_style_key(self, status: CheckStatus) -> str:
        if status == CheckStatus.MATCH:
            return "ok"
        if status in {CheckStatus.MISMATCH, CheckStatus.HIGH_RISK}:
            return "error"
        return "warning"

    def _style_table_item(self, item: QTableWidgetItem, state: str) -> None:
        foreground = {
            "ok": "#14532D",
            "warning": "#5B4A20",
            "error": "#7F1D1D",
            "neutral": "#1F2937",
        }.get(state, "#1F2937")
        item.setForeground(QBrush(QColor(foreground)))

    def _parsed_field_value(self, document: ParsedDocument, field) -> str:
        for parsed_field in document.fields:
            if parsed_field.canonical == field:
                return str(parsed_field.value).strip()
        return ""

    def _audit_result_label(self, result, fallback: str) -> str:
        field_label = FIELD_LABELS.get(result.field.value, result.field.value)
        if result.status == CheckStatus.MATCH:
            return "✓ 一致"
        if result.status == CheckStatus.MISSING:
            return f"✗ 缺少{field_label}資料"
        if result.status == CheckStatus.MISMATCH:
            return f"✗ {field_label}不一致"
        if result.status == CheckStatus.HIGH_RISK:
            return f"⚠ {field_label}待人工確認"
        return fallback

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
        parser_debug.setPlaceholderText("文件讀取明細")
        parser_debug.setVisible(self.settings.developer_mode)
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
        self._check_updates(interactive=False)

    def _check_updates(self, interactive: bool) -> UpdateCheck | None:
        if self.update_check_thread and self.update_check_thread.isRunning():
            if interactive:
                self._show_toast("更新狀態", "正在背景檢查更新。", action_visible=False, timeout_ms=2500)
            return None
        self.settings.version = resolve_local_version()
        self._set_update_status("背景檢查更新中...", "neutral")
        self.update_check_thread = QThread(self)
        self.update_check_thread.setProperty("interactive", interactive)
        self.update_check_worker = UpdateCheckWorker(self.settings.version, self.settings.update)
        self.update_check_worker.moveToThread(self.update_check_thread)
        self.update_check_thread.started.connect(self.update_check_worker.run)
        self.update_check_worker.finished.connect(self._on_update_check_finished)
        self.update_check_worker.finished.connect(self.update_check_thread.quit)
        self.update_check_worker.finished.connect(self.update_check_worker.deleteLater)
        self.update_check_thread.finished.connect(self.update_check_thread.deleteLater)
        self.update_check_thread.finished.connect(self._clear_update_check_worker)
        self.update_check_thread.start()
        return None

    @Slot(object)
    def _on_update_check_finished(self, result: UpdateCheck) -> None:
        interactive = bool(self.update_check_thread.property("interactive")) if self.update_check_thread else False
        self.latest_update = result
        self._sync_update_status(result)
        self._refresh_updater_debug_info()
        if result.should_show_popup:
            self._show_update_toast(result)
        elif interactive:
            self._show_toast("更新狀態", result.message, action_visible=False, timeout_ms=4200)

    @Slot()
    def _clear_update_check_worker(self) -> None:
        self.update_check_thread = None
        self.update_check_worker = None

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
            "downloading": "下載新版",
            "verifying": "驗證檔案",
            "replacing": "安裝新版",
            "restarting": "重新啟動",
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
        self._refresh_updater_debug_info()
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
            self._set_update_status(f"已是最新版，最後檢查 {datetime.now().strftime('%H:%M')}", "current")
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
        self._apply_developer_mode_visibility()

    def _apply_developer_mode_visibility(self) -> None:
        developer_mode = bool(getattr(self.settings, "developer_mode", False))
        self.status_build.setVisible(developer_mode)
        self.updater_debug_info.setVisible(developer_mode)
        for action_name in ("updater_debug_action", "updater_reset_action"):
            action = getattr(self, action_name, None)
            if isinstance(action, QAction):
                action.setVisible(developer_mode)
        for view in self.workflow_views.values():
            debug = view.get("debug")
            toggle = view.get("debug_toggle")
            if isinstance(toggle, QPushButton):
                toggle.setVisible(developer_mode)
                if not developer_mode:
                    toggle.setChecked(False)
            if isinstance(debug, QTextEdit) and not developer_mode:
                debug.hide()

    def _refresh_updater_debug_info(self, local_only: bool = False) -> None:
        self.status_build.setText(self._format_build_badge())
        if not self.settings.developer_mode:
            self.updater_debug_info.clear()
            self._apply_developer_mode_visibility()
            return
        try:
            updater = V2Updater(resolve_local_version(), self.settings.update)
            if local_only:
                state = {
                    "executable_path": str(__import__("pathlib").Path(sys.executable).resolve()),
                    "local_version": resolve_local_version(),
                    "local_sha": "-",
                    "remote_version": "-",
                    "remote_sha": "-",
                    "pending_sha": "-",
                    "update_state": "not_checked",
                    "finalize_state": "-",
                    "shortcut_state": [],
                }
            else:
                state = updater.debug_state()
        except Exception as exc:
            self.updater_debug_info.setText(f"Updater debug failed: {type(exc).__name__}: {exc}")
            return

        shortcuts = state.get("shortcut_state") if isinstance(state, dict) else []
        shortcut_target = "-"
        if isinstance(shortcuts, list) and shortcuts:
            first = shortcuts[0]
            if isinstance(first, dict):
                shortcut_target = str(first.get("target_path", "-"))
        current_sha = str(state.get("local_sha", "-"))
        remote_sha = str(state.get("remote_sha", "-"))
        pending_sha = str(state.get("pending_sha", "-"))
        text = (
            f"EXE: {state.get('executable_path', '-')}\n"
            f"Current Version: {state.get('local_version', '-')} | Current SHA: {self._short_sha(current_sha)} | "
            f"Remote Version: {state.get('remote_version', '-')} | Remote SHA: {self._short_sha(remote_sha)}\n"
            f"Pending: {state.get('pending_exists', '-')} {self._short_sha(pending_sha)} | "
            f"State: {state.get('update_state', '-')} | Finalized: {state.get('finalize_state', '-')} | "
            f"Shortcut: {shortcut_target}"
        )
        self.updater_debug_info.setText(text)
        self.updater_debug_info.setToolTip(text)

    def _short_sha(self, value: str) -> str:
        value = str(value or "-")
        if len(value) >= 12 and all(char in "0123456789abcdefABCDEF" for char in value[:12]):
            return value[:12]
        return value

    def _format_build_badge(self) -> str:
        build = read_build_info()
        build_time = build.build_time
        if build_time:
            build_time = build_time.replace("T", " ").replace("+00:00", "Z")
            build_time = build_time[:16]
        else:
            build_time = "-"
        sha = self._short_sha(build.sha256)
        release = build.release_id or "-"
        return f"Build: {build_time} | SHA: {sha} | Release: {release}"

    def _write_update_progress(self, message: str) -> None:
        path = logs_dir() / "updater.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[UI] {message}\n")

    def _open_updater_debug_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Updater Debug")
        dialog.resize(760, 620)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Updater Debug Panel")
        title.setObjectName("SectionTitle")
        details = QTextEdit()
        details.setReadOnly(True)
        details.setObjectName("AuditReportView")
        reset = QPushButton("Reset Updater State")
        refresh = QPushButton("重新整理")
        close = QPushButton("關閉")
        close.setObjectName("SecondaryButton")

        def render() -> None:
            updater = V2Updater(resolve_local_version(), self.settings.update)
            state = updater.debug_state()
            shortcuts = state.get("shortcut_state", [])
            shortcut_lines = []
            if isinstance(shortcuts, list) and shortcuts:
                for item in shortcuts:
                    if isinstance(item, dict):
                        shortcut_lines.append(
                            f"- {item.get('shortcut_path', '-')}\n"
                            f"  target: {item.get('target_path', '-')}\n"
                            f"  previous: {item.get('previous_target_path', '-')}\n"
                            f"  action: {item.get('action', '-')}"
                        )
            else:
                shortcut_lines.append("- 找不到 TongYang/通洋/Customs/報關 桌面捷徑")
            lines = [
                "Updater Debug Panel",
                "",
                f"目前執行 EXE path: {state.get('executable_path', '-')}",
                f"Frozen EXE: {state.get('frozen', '-')}",
                "",
                f"local version: {state.get('local_version', '-')}",
                f"local SHA: {state.get('local_sha', '-')}",
                f"remote version: {state.get('remote_version', state.get('remote_error', '-'))}",
                f"remote SHA: {state.get('remote_sha', '-')}",
                f"pending version: {state.get('pending_version', '-')}",
                f"pending SHA: {state.get('pending_sha', '-')}",
                "",
                f"update state: {state.get('update_state', '-')}",
                f"finalize state: {state.get('finalize_state', '-')}",
                f"cache state: {state.get('cache_state', '-')}",
                "",
                "Desktop shortcut targets:",
                *shortcut_lines,
                "",
                f"compare result: {state.get('compare_result', '-')}",
                f"normalized local: {state.get('normalized_local', '-')}",
                f"normalized remote: {state.get('normalized_remote', '-')}",
                f"SHA match: {state.get('sha_match', '-')}",
                f"SHA changed: {state.get('sha_changed', '-')}",
                "",
                f"local manifest: {state.get('local_manifest_path', '-')}",
                f"pending manifest: {state.get('pending_manifest_path', '-')}",
                f"download URL: {state.get('download_url', '-')}",
                "",
                "logs/updater.log 會記錄完整判斷流程。",
            ]
            details.setText("\n".join(str(line) for line in lines))

        def reset_and_render() -> None:
            state = self._reset_updater_state(show_message=False)
            render()
            removed = state.get("reset_removed", []) if isinstance(state, dict) else []
            QMessageBox.information(
                dialog,
                "Reset Updater State",
                "Updater state reset completed.\n"
                f"Current EXE: {state.get('executable_path', '-') if isinstance(state, dict) else '-'}\n"
                f"State: {state.get('update_state', '-') if isinstance(state, dict) else '-'}\n"
                f"Removed: {len(removed) if isinstance(removed, list) else 0}",
            )

        refresh.clicked.connect(render)
        reset.clicked.connect(reset_and_render)
        close.clicked.connect(dialog.accept)
        button_row = QHBoxLayout()
        button_row.addWidget(refresh)
        button_row.addWidget(reset)
        button_row.addStretch(1)
        button_row.addWidget(close)
        layout.addWidget(title)
        layout.addWidget(details, 1)
        layout.addLayout(button_row)
        render()
        dialog.exec()

    def _reset_updater_state(self, show_message: bool = True) -> dict[str, object]:
        updater = V2Updater(resolve_local_version(), self.settings.update)
        try:
            state = updater.reset_state()
            self._refresh_updater_debug_info()
            update_state = str(state.get("update_state", "-"))
            if state.get("sha_match") or update_state in {"current", "current_sha_match", "local_newer"}:
                self.latest_update = None
                self._set_update_status("?桀?撌脫??啁?", "current")
                self.toast.show_message("Updater Reset", "?湔???撌脣?蝵桐?嚗??桀?撌脫??啁?", action_visible=False)
            elif update_state == "available":
                remote_version = str(state.get("remote_version", "-"))
                self._set_update_status(f"?潛?啁? {remote_version}", "available")
                self._check_updates(interactive=False)
            else:
                self._set_update_status(f"Updater reset: {update_state}", "current")
            if show_message:
                removed = state.get("reset_removed", [])
                QMessageBox.information(
                    self,
                    "Reset Updater State",
                    "Updater state reset completed.\n"
                    f"Current EXE: {state.get('executable_path', '-')}\n"
                    f"Current Version: {state.get('local_version', '-')}\n"
                    f"Current SHA: {state.get('local_sha', '-')}\n"
                    f"Remote Version: {state.get('remote_version', state.get('remote_error', '-'))}\n"
                    f"Remote SHA: {state.get('remote_sha', '-')}\n"
                    f"State: {update_state}\n"
                    f"Removed: {len(removed) if isinstance(removed, list) else 0}",
                )
            return state
        except Exception as exc:
            self._write_update_progress(f"reset updater state failed: {type(exc).__name__}: {exc}")
            QMessageBox.critical(self, "Reset Updater State", f"Reset failed: {type(exc).__name__}: {exc}")
            self._refresh_updater_debug_info(local_only=True)
            return {"update_state": "reset_error", "error": f"{type(exc).__name__}: {exc}"}

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
        developer_mode = QCheckBox("開發人員模式")
        developer_mode.setChecked(self.settings.developer_mode)
        developer_mode.setToolTip("開啟後才顯示 parser、updater SHA、EXE path、debug log 等內部資訊。")
        channel = QComboBox()
        channel.addItems(["dev", "stable"])
        channel.setCurrentText(self.settings.update.channel if self.settings.update.channel in {"dev", "stable"} else "stable")

        layout.addWidget(enabled)
        layout.addWidget(startup)
        layout.addWidget(developer_mode)
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
        self.settings.developer_mode = developer_mode.isChecked()
        save_settings(self.settings)
        self._set_update_status("設定已儲存", "neutral")
        self._apply_developer_mode_visibility()
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
            QTableWidget::item:selected, QTreeWidget::item:selected {
                background: #256D83;
                color: #FFFFFF;
            }
            QTableWidget::item:disabled, QTreeWidget::item:disabled {
                background: #18212B;
                color: #7E8B99;
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
            /* Production ERP workspace overrides */
            QMainWindow, QWidget {
                background: #F4F6F8;
                color: #1F2A37;
            }
            QMenuBar {
                background: #FFFFFF;
                color: #1F2A37;
                border-bottom: 1px solid #D8DEE6;
            }
            QMenuBar::item:selected {
                background: #E8EEF5;
                color: #14213D;
            }
            #Sidebar {
                background: #172235;
                border-right: 1px solid #0F172A;
            }
            #Brand {
                color: #FFFFFF;
            }
            #Subtitle, #SidebarNote {
                color: #CBD5E1;
            }
            #PageTitle {
                color: #14213D;
                font-size: 25px;
            }
            #PanelTitle {
                color: #1F2A37;
                font-size: 15px;
                font-weight: 700;
            }
            #WorkflowUpload, #AuditSidePanel, #AuditWorkspace, #AuditSummaryPanel {
                background: #FFFFFF;
                border: 1px solid #D8DEE6;
                border-radius: 8px;
                padding: 12px;
            }
            #WorkflowUpload {
                max-height: 140px;
            }
            #WorkflowUpload[dragActive="true"] {
                border: 2px solid #2563EB;
                background: #EFF6FF;
            }
            #ResultBox, #CompareTable {
                background: #FFFFFF;
                border: 1px solid #D8DEE6;
                border-radius: 6px;
                color: #1F2A37;
                gridline-color: #E5EAF0;
                font-size: 15px;
            }
            #DocumentCards {
                background: #FFFFFF;
                border: 0;
                color: #1F2A37;
                outline: 0;
                font-size: 15px;
            }
            #DocumentCards::item {
                background: #F8FAFC;
                border: 1px solid #D8DEE6;
                border-radius: 8px;
                padding: 12px;
                margin: 0 0 8px 0;
                min-height: 72px;
            }
            #DocumentCards::item:selected {
                background: #E8F1F8;
                border: 1px solid #2E6F8F;
            }
            QHeaderView::section {
                background: #EEF2F6;
                color: #1F2A37;
                border: 0;
                border-right: 1px solid #D8DEE6;
                padding: 8px;
                font-weight: 700;
                font-size: 14px;
            }
            QTextEdit#AuditReportView {
                background: #FFFFFF;
                color: #1F2A37;
                border: 1px solid #D8DEE6;
                border-radius: 8px;
                font-size: 16px;
                line-height: 1.5;
            }
            QTextEdit#RiskSummaryCard {
                background: #FFFBEB;
                color: #5C3B00;
                border: 1px solid #F3D28B;
                border-left: 4px solid #D99822;
                border-radius: 8px;
                font-size: 15px;
                line-height: 1.45;
            }
            QLineEdit, QComboBox {
                background: #FFFFFF;
                color: #1F2A37;
                border: 1px solid #CBD5E1;
            }
            QCheckBox {
                color: #1F2A37;
            }
            #GlobalStatusBar {
                background: #FFFFFF;
                border-top: 1px solid #D8DEE6;
            }
            #StatusChannel, #StatusVersion {
                color: #14213D;
            }
            #StatusMessage {
                color: #475569;
            }
            #AuditStatusBadge {
                color: #14213D;
                font-size: 16px;
                font-weight: 700;
                padding: 6px 10px;
                background: #EEF2F6;
                border-radius: 8px;
            }
            QDialog {
                background: #FFFFFF;
            }
            """
        )
