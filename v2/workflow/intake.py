from __future__ import annotations

import csv
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader

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
            files.append(self.load_file(path))
        return files

    def load_file(self, path: Path) -> IntakeFile:
        suffix = path.suffix.lower()
        key = self.cache.key_for_file(path)
        cached = self.cache.read_text(key)
        if cached is not None:
            pages = [IntakePage(1, cached)]
            return IntakeFile(path, suffix, pages, cached, {"cache": "hit", "key": key})

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
            pages = [IntakePage(1, result.text, True, result.message)]
        else:
            pages = [IntakePage(1, self._load_text(path))]

        text = "\n\n".join(page.text for page in pages)
        self.cache.write_text(key, text)
        self.cache.write_debug(key, {"path": str(path), "suffix": suffix, "page_count": len(pages)})
        return IntakeFile(path, suffix, pages, text, {"cache": "miss", "key": key})

    def _load_pdf(self, path: Path) -> list[IntakePage]:
        reader = PdfReader(str(path))
        pages: list[IntakePage] = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            ocr_used = False
            ocr_message = ""
            if not text.strip():
                result = self.ocr.extract_pdf_page_text(path, index - 1)
                text = result.text
                ocr_used = result.available
                ocr_message = result.message
            pages.append(IntakePage(index, text, ocr_used, ocr_message))
        return pages

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
            return "\n".join(lines)
