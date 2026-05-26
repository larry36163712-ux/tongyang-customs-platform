from __future__ import annotations

from dataclasses import dataclass
import shutil
from pathlib import Path

from v2.core.runtime_log import log_runtime


@dataclass(frozen=True)
class OcrResult:
    text: str
    engine: str
    confidence: float
    available: bool
    message: str = ""


class OcrEngine:
    """OCR boundary used by intake for scanned PDFs and image files.

    It uses pytesseract/Pillow for image OCR and PyMuPDF to render scanned PDF
    pages. When a dependency or the Tesseract runtime is unavailable, the engine
    reports a structured missing-OCR state so the workflow can stop with a clear
    operational error instead of silently producing an empty audit.
    """

    def is_available(self) -> tuple[bool, str]:
        try:
            import pytesseract
            from PIL import Image  # noqa: F401
        except Exception as exc:
            message = f"OCR Python dependency unavailable: {exc}"
            log_runtime(message)
            return False, message
        configured = getattr(pytesseract.pytesseract, "tesseract_cmd", "")
        detected = configured if configured and Path(configured).exists() else shutil.which("tesseract")
        if not detected:
            for candidate in (
                Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
                Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
            ):
                if candidate.exists():
                    pytesseract.pytesseract.tesseract_cmd = str(candidate)
                    detected = str(candidate)
                    break
        if not detected:
            message = "未安裝 OCR runtime：Tesseract"
            log_runtime(message)
            return False, message
        log_runtime(f"OCR startup ok engine=pytesseract tesseract={detected}")
        return True, f"pytesseract ready: {detected}"

    def extract_image_text(self, path: Path) -> OcrResult:
        try:
            from PIL import Image
            import pytesseract
        except Exception as exc:
            message = f"OCR dependency unavailable: {exc}"
            log_runtime(message)
            return OcrResult("", "pytesseract", 0.0, False, message)
        available, message = self.is_available()
        if not available:
            return OcrResult("", "pytesseract", 0.0, False, message)

        try:
            log_runtime(f"OCR image start path={path}")
            text = pytesseract.image_to_string(Image.open(path), lang="eng+chi_tra")
        except Exception as exc:
            message = f"OCR failed: {exc}"
            log_runtime(f"{message} path={path}")
            return OcrResult("", "pytesseract", 0.0, False, message)
        log_runtime(f"OCR image completed path={path} chars={len(text.strip())}")
        return OcrResult(text.strip(), "pytesseract", 0.72 if text.strip() else 0.0, True)

    def extract_pdf_page_text(self, pdf_path: Path, page_index: int) -> OcrResult:
        try:
            import fitz
            from PIL import Image
            import pytesseract
        except Exception as exc:
            message = f"PDF OCR dependency unavailable: {exc}"
            log_runtime(message)
            return OcrResult("", "pytesseract+fitz", 0.0, False, message)
        available, message = self.is_available()
        if not available:
            return OcrResult("", "pytesseract+fitz", 0.0, False, message)

        try:
            log_runtime(f"OCR PDF page start path={pdf_path} page_index={page_index}")
            with fitz.open(str(pdf_path)) as document:
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                text = pytesseract.image_to_string(image, lang="eng+chi_tra")
        except Exception as exc:
            message = f"PDF OCR failed: {exc}"
            log_runtime(f"{message} path={pdf_path} page_index={page_index}")
            return OcrResult("", "pytesseract+fitz", 0.0, False, message)
        log_runtime(f"OCR PDF page completed path={pdf_path} page_index={page_index} chars={len(text.strip())}")
        return OcrResult(text.strip(), "pytesseract+fitz", 0.72 if text.strip() else 0.0, True)
