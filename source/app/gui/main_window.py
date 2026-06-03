from __future__ import annotations

import shutil
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.config.settings import load_settings
from app.export_checker.checker import ExportChecker
from app.history import save_check_history
from app.import_checker.checker import ImportChecker
from app.parser.document import UploadedDocument
from app.parser.pdf_parser import parse_uploaded_documents
from app.version import app_version


IMPORT_DOCS = ["INV", "PKG", "B/L", "倉單", "DS2報單"]
EXPORT_DOCS = ["INV", "PKG", "訂艙單 / SO", "DS2報單"]


class CustomsPlatformApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.app_version = app_version(self.settings.version)
        self.title(self.settings.app_name)
        self.geometry("1120x720")
        self.minsize(980, 640)

        self.mode = tk.StringVar(value="import")
        self.release_method = tk.StringVar(value=self.settings.release_methods[0])
        self.uploaded_docs: dict[str, list[UploadedDocument]] = {}

        self.invoice_amount = tk.StringVar(value="0")
        self.insurance_rate = tk.StringVar(value="0.001")
        self.cbm = tk.StringVar(value="0")
        self.declared_freight = tk.StringVar(value="0")
        self.declared_insurance = tk.StringVar(value="0")
        self.declared_cif = tk.StringVar(value="0")

        self.import_checker = ImportChecker()
        self.export_checker = ExportChecker()

        self._configure_style()
        self._build_layout()
        self._refresh_document_list(clear_uploads=True)
        if self.settings.update.get("check_on_startup", True):
            self.after(800, lambda: self._check_updates(apply_update=True, silent=True))

    def _configure_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f7f8fa")
        style.configure("Sidebar.TFrame", background="#eef1f4")
        style.configure("TLabel", background="#f7f8fa", font=("Microsoft JhengHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft JhengHei UI", 16, "bold"))
        style.configure("Status.TLabel", font=("Microsoft JhengHei UI", 10, "bold"))
        style.configure("TButton", font=("Microsoft JhengHei UI", 10))
        style.configure("TRadiobutton", background="#eef1f4", font=("Microsoft JhengHei UI", 10))
        style.configure("TCombobox", font=("Microsoft JhengHei UI", 10))

    def _build_layout(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self, style="Sidebar.TFrame", padding=16)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.columnconfigure(0, weight=1)

        content = ttk.Frame(self, padding=16)
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        self._build_sidebar(sidebar)
        self._build_result_area(content)

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text=f"{self.settings.app_name} V{self.app_version}", style="Title.TLabel", background="#eef1f4").grid(
            row=0, column=0, sticky="w", pady=(0, 18)
        )

        mode_frame = ttk.LabelFrame(parent, text="核對類型", padding=10)
        mode_frame.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        ttk.Radiobutton(
            mode_frame,
            text="進口核對",
            variable=self.mode,
            value="import",
            command=lambda: self._refresh_document_list(clear_uploads=True),
        ).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Radiobutton(
            mode_frame,
            text="出口核對",
            variable=self.mode,
            value="export",
            command=lambda: self._refresh_document_list(clear_uploads=True),
        ).grid(row=1, column=0, sticky="w", pady=2)

        upload_frame = ttk.LabelFrame(parent, text="文件上傳", padding=10)
        upload_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 12))
        upload_frame.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        self.doc_list = tk.Listbox(
            upload_frame,
            height=9,
            font=("Microsoft JhengHei UI", 10),
            activestyle="none",
            exportselection=False,
        )
        self.doc_list.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        upload_frame.rowconfigure(0, weight=1)

        ttk.Button(upload_frame, text="上傳選取文件", command=self._upload_selected_document).grid(
            row=1, column=0, sticky="ew", pady=3
        )
        ttk.Button(upload_frame, text="清除上傳清單", command=self._clear_uploads).grid(
            row=2, column=0, sticky="ew", pady=3
        )

        release_frame = ttk.LabelFrame(parent, text="放行方式預留", padding=10)
        release_frame.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        ttk.Combobox(
            release_frame,
            textvariable=self.release_method,
            values=self.settings.release_methods,
            state="readonly",
        ).grid(row=0, column=0, sticky="ew")

        freight_frame = ttk.LabelFrame(parent, text="運保費驗算", padding=10)
        freight_frame.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        labels = [
            ("CBM", self.cbm),
            ("發票金額", self.invoice_amount),
            ("保險費率", self.insurance_rate),
            ("報單運費", self.declared_freight),
            ("報單保費", self.declared_insurance),
            ("報單CIF", self.declared_cif),
        ]
        for row, (label, var) in enumerate(labels):
            ttk.Label(freight_frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(freight_frame, textvariable=var, width=16).grid(row=row, column=1, sticky="ew", pady=2)
        freight_frame.columnconfigure(1, weight=1)

        ttk.Button(parent, text="開始核對", command=self._run_check).grid(row=5, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(parent, text="檢查更新", command=lambda: self._check_updates(apply_update=True, silent=False)).grid(
            row=6, column=0, sticky="ew", pady=(6, 0)
        )

    def _build_result_area(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="核對結果區", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.summary_label = ttk.Label(header, text="尚未核對", style="Status.TLabel")
        self.summary_label.grid(row=0, column=1, sticky="e")

        body = ttk.Frame(parent)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        result_frame = ttk.LabelFrame(body, text="核對結果視窗", padding=8)
        result_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        result_frame.rowconfigure(0, weight=1)
        result_frame.columnconfigure(0, weight=1)

        self.result_text = tk.Text(
            result_frame,
            wrap="word",
            font=("Microsoft JhengHei UI", 10),
            bg="#ffffff",
            relief="flat",
            padx=10,
            pady=10,
        )
        self.result_text.grid(row=0, column=0, sticky="nsew")

        diff_frame = ttk.LabelFrame(body, text="差異顯示區", padding=8)
        diff_frame.grid(row=0, column=1, sticky="nsew")
        diff_frame.rowconfigure(0, weight=1)
        diff_frame.columnconfigure(0, weight=1)

        self.diff_text = tk.Text(
            diff_frame,
            wrap="word",
            font=("Microsoft JhengHei UI", 10),
            bg="#fffdf6",
            relief="flat",
            padx=10,
            pady=10,
        )
        self.diff_text.grid(row=0, column=0, sticky="nsew")

    def _current_doc_types(self) -> list[str]:
        return IMPORT_DOCS if self.mode.get() == "import" else EXPORT_DOCS

    def _refresh_document_list(self, clear_uploads: bool = False) -> None:
        if clear_uploads:
            self.uploaded_docs.clear()
        self.doc_list.delete(0, tk.END)
        for doc_type in self._current_doc_types():
            docs = self.uploaded_docs.get(doc_type, [])
            if docs:
                names = "、".join(doc.display_name for doc in docs[:2])
                more = f" 等 {len(docs)} 份" if len(docs) > 2 else f" {len(docs)} 份"
                self.doc_list.insert(tk.END, f"{doc_type}：{names}{more}")
            else:
                self.doc_list.insert(tk.END, f"{doc_type}：未上傳")
        self._set_text(self.result_text, "請先上傳文件，然後按「開始核對」。")
        self._set_text(self.diff_text, "差異將顯示於此。")
        self.summary_label.configure(text="尚未核對")

    def _upload_selected_document(self) -> None:
        selection = self.doc_list.curselection()
        if not selection:
            messagebox.showinfo("提示", "請先選取要上傳的文件類型。")
            return

        doc_type = self._current_doc_types()[selection[0]]
        file_paths = filedialog.askopenfilenames(
            title=f"上傳 {doc_type}",
            filetypes=[
                ("文件檔案", "*.pdf *.txt *.csv"),
                ("所有檔案", "*.*"),
            ],
        )
        if not file_paths:
            return

        docs = self.uploaded_docs.setdefault(doc_type, [])
        for file_path in file_paths:
            docs.append(self._copy_to_uploads(doc_type, Path(file_path)))
        self._refresh_document_list(clear_uploads=False)
        self.doc_list.selection_set(selection[0])

    def _copy_to_uploads(self, doc_type: str, source: Path) -> UploadedDocument:
        upload_root = Path(self.settings.uploads_dir)
        batch_dir = upload_root / datetime.now().strftime("%Y%m%d")
        batch_dir.mkdir(parents=True, exist_ok=True)

        safe_doc_name = doc_type.replace("/", "_").replace(" ", "")
        target = batch_dir / f"{datetime.now().strftime('%H%M%S%f')}_{safe_doc_name}_{source.name}"
        shutil.copy2(source, target)
        return UploadedDocument(doc_type=doc_type, original_path=source, stored_path=target)

    def _clear_uploads(self) -> None:
        self.uploaded_docs.clear()
        self._refresh_document_list(clear_uploads=False)

    def _run_check(self) -> None:
        checker = self.import_checker if self.mode.get() == "import" else self.export_checker
        parsed_documents = parse_uploaded_documents(self.uploaded_docs)
        freight_inputs = {
            "cbm": self.cbm.get(),
            "invoice_amount": self.invoice_amount.get(),
            "insurance_rate": self.insurance_rate.get(),
            "declared_freight": self.declared_freight.get(),
            "declared_insurance": self.declared_insurance.get(),
            "declared_cif": self.declared_cif.get(),
        }
        report = checker.check(
            self.uploaded_docs,
            parsed_documents=parsed_documents,
            freight_inputs=freight_inputs,
        )
        history_id = save_check_history(self.mode.get(), self.uploaded_docs, parsed_documents, report)

        result_lines = [f"{item.symbol} {item.field}：{item.message}" for item in report.items]
        diff_lines = [
            f"{item.symbol} {item.field}\n預期：{item.expected}\n實際：{item.actual}\n"
            for item in report.items
            if item.status in {"warning", "mismatch"}
        ]

        self._set_text(self.result_text, "\n".join(result_lines) if result_lines else "尚無核對項目。")
        self._set_text(self.diff_text, "\n".join(diff_lines) if diff_lines else "✓ 未發現差異。")
        self.summary_label.configure(text=f"{report.summary}　紀錄 #{history_id}")

    def _check_updates(self, apply_update: bool, silent: bool) -> None:
        if silent:
            return
        messagebox.showinfo("Updater", "Legacy updater has been retired. Use the production V2 updater.")

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state="disabled")


def run_app() -> None:
    app = CustomsPlatformApp()
    app.mainloop()
