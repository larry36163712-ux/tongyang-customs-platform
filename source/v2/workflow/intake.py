from __future__ import annotations

import csv
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader

from v2.core.runtime_log import log_exception, log_runtime
from v2.ocr import OcrEngine
from v2.workflow.cache import WorkflowCache
from v2.workflow.models import IntakeFile, IntakePage


SUPPORTED_SUFFIXES = {".pdf", ".txt", ".csv", ".tsv", ".xlsx", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


class FileIntakeEngine:
    def __init__(self, cache: WorkflowCache, ocr: OcrEngine | None = None) -> None:
        self.cache = cache
        self.ocr = ocr or OcrEngine()

    def load_paths(self, paths: list[str]) -> list[IntakeFile]:
        files: list[IntakeFile] = []
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            try:
                files.append(self.load_file(path))
            except Exception as exc:
                log_exception(f"file intake failed but kept for manual review path={path}", exc)
                files.append(self._manual_review_intake(path, f"{type(exc).__name__}: {exc}", "file_intake"))
        return files

    def load_file(self, path: Path) -> IntakeFile:
        suffix = path.suffix.lower()
        log_runtime(f"file intake start path={path} suffix={suffix}")
        key = self.cache.key_for_file(path)
        cached = self.cache.read_text(key)
        if cached is not None:
            log_runtime(f"file intake cache hit path={path} key={key} chars={len(cached)}")
            pages = [IntakePage(1, cached)]
            debug: dict[str, object] = {"cache": "hit", "key": key}
            if "狀態：需人工確認" in cached:
                debug["ocr_status"] = "manual_review"
                debug["ocr_message"] = "此文件需人工確認，請重新上傳或清除快取後再試。"
            return IntakeFile(path, suffix, pages, cached, debug)

        try:
            if suffix == ".pdf":
                pages = self._load_pdf(path)
            elif suffix == ".csv":
                pages = [IntakePage(1, self._load_delimited(path, ","))]
            elif suffix == ".tsv":
                pages = [IntakePage(1, self._load_delimited(path, "\t"))]
            elif suffix == ".xlsx":
                pages = [IntakePage(1, self._load_xlsx(path))]
            elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
                result = self.ocr.extract_image_text(path)
                if not result.available or not result.text.strip():
                    message = result.message or "此影像文件未取得可辨識文字。"
                    pages = [self._manual_review_page(path, message, ocr_used=True)]
                    text = "\n\n".join(page.text for page in pages)
                    log_runtime(f"image OCR manual review path={path} message={message}")
                    return IntakeFile(
                        path,
                        suffix,
                        pages,
                        text,
                        {"cache": "miss", "key": key, "ocr_status": "manual_review", "ocr_message": pages[0].ocr_message},
                    )
                pages = [IntakePage(1, result.text, True, result.message)]
            else:
                pages = [IntakePage(1, self._load_text(path))]
        except Exception as exc:
            log_exception(f"file intake failed path={path}", exc)
            raise

        text = "\n\n".join(page.text for page in pages)
        debug = {"path": str(path), "suffix": suffix, "page_count": len(pages)}
        if self._has_manual_review_page(pages):
            debug["ocr_status"] = "manual_review"
            debug["ocr_message"] = "; ".join(page.ocr_message for page in pages if page.ocr_message)
        else:
            self.cache.write_text(key, text)
            self.cache.write_debug(key, debug)
        log_runtime(f"file intake completed path={path} pages={len(pages)} chars={len(text)}")
        return IntakeFile(path, suffix, pages, text, {"cache": "miss", "key": key, **debug})

    def _load_pdf(self, path: Path) -> list[IntakePage]:
        log_runtime(f"PDF load start path={path}")
        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            log_exception(f"PDF reader failed path={path}", exc)
            return [self._manual_review_page(path, "PDF 讀取失敗，請確認檔案是否可開啟。")]
        pages: list[IntakePage] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                log_exception(f"PDF text extraction failed path={path} page={index}", exc)
                text = ""
            ocr_used = False
            ocr_message = ""
            if not text.strip():
                log_runtime(f"PDF page requires OCR path={path} page={index}")
                result = self.ocr.extract_pdf_page_text(path, index - 1)
                if not result.available or not result.text.strip():
                    ocr_message = result.message or "此頁為掃描 PDF，尚未取得可辨識文字。"
                    pages.append(self._manual_review_page(path, ocr_message, page_number=index, ocr_used=True))
                    log_runtime(f"PDF OCR manual review path={path} page={index} message={ocr_message}")
                    continue
                text = result.text
                ocr_used = True
                ocr_message = result.message
            pages.append(IntakePage(index, text, ocr_used, ocr_message))
        if not pages:
            pages.append(self._manual_review_page(path, "PDF 沒有可讀頁面，請人工確認文件內容。"))
        log_runtime(f"PDF load completed path={path} pages={len(pages)}")
        return pages

    def _manual_review_page(
        self,
        path: Path,
        message: str,
        page_number: int = 1,
        ocr_used: bool = False,
    ) -> IntakePage:
        user_message = self._user_safe_ocr_message(message)
        text = (
            f"文件：{path.name}\n"
            "狀態：需人工確認\n"
            f"原因：{user_message}\n"
            "系統已保留此文件並納入案件流程，請人工確認文件類型與內容。"
        )
        return IntakePage(page_number, text, ocr_used, user_message)

    def _manual_review_intake(self, path: Path, message: str, stage: str) -> IntakeFile:
        page = self._manual_review_page(path, message)
        return IntakeFile(
            path,
            path.suffix.lower(),
            [page],
            page.text,
            {"cache": "bypass", "stage": stage, "ocr_status": "manual_review", "ocr_message": page.ocr_message},
        )

    def _has_manual_review_page(self, pages: list[IntakePage]) -> bool:
        return any("狀態：需人工確認" in page.text for page in pages)

    def _user_safe_ocr_message(self, message: str) -> str:
        lowered = message.casefold()
        if "tesseract" in lowered or "ocr 辨識元件" in message:
            return "此文件可能為掃描 PDF，系統目前缺少 OCR 辨識元件，請安裝 Tesseract 或改用可搜尋 PDF。"
        if "timeout" in lowered or "逾時" in message:
            return "OCR 辨識逾時，請改用較清楚的掃描檔或可搜尋 PDF。"
        if "pdf" in lowered or "讀取失敗" in message:
            return "PDF 讀取未完成，請確認檔案是否可開啟，或改用可搜尋 PDF。"
        return "OCR 尚未取得足夠文字，請人工確認或提供較清楚的文件。"

    def _load_text(self, path: Path) -> str:
        for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(errors="ignore")

    def _load_delimited(self, path: Path, delimiter: str) -> str:
        text = self._load_text(path)
        rows = csv.reader(text.splitlines(), delimiter=delimiter)
        return "\n".join(" | ".join(cell.strip() for cell in row) for row in rows)

    def _load_xlsx(self, path: Path) -> str:
        log_runtime(f"XLSX load start path={path}")
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(path) as archive:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                for item in root.findall(".//x:si", ns):
                    shared.append("".join(node.text or "" for node in item.findall(".//x:t", ns)))
            sheet_names = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet"))
            lines: list[str] = []
            for sheet_name in sheet_names:
                root = ElementTree.fromstring(archive.read(sheet_name))
                for row in root.findall(".//x:row", ns):
                    cells: list[str] = []
                    for cell in row.findall("x:c", ns):
                        value_node = cell.find("x:v", ns)
                        if value_node is None:
                            cells.append("")
                            continue
                        value = value_node.text or ""
                        if cell.attrib.get("t") == "s" and value.isdigit():
                            index = int(value)
                            value = shared[index] if index < len(shared) else value
                        cells.append(value)
                    if any(cells):
                        lines.append(" | ".join(cells))
            text = "\n".join(lines)
            log_runtime(f"XLSX load completed path={path} lines={len(lines)} chars={len(text)}")
            return text
