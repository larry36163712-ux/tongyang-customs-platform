from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from v2.core.runtime_log import log_runtime


@dataclass(frozen=True)
class OcrResult:
    text: str
    engine: str
    confidence: float
    available: bool
    message: str = ""


class OcrEngine:
    """Production OCR boundary with explicit dependency and runtime reporting."""

    IMAGE_TIMEOUT_SECONDS = 90
    PDF_PAGE_TIMEOUT_SECONDS = 120

    def is_available(self) -> tuple[bool, str]:
        try:
            import pytesseract
            from PIL import Image  # noqa: F401
        except Exception as exc:
            message = self._dependency_message(exc)
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
            message = self._missing_tesseract_message()
            log_runtime(message)
            return False, message
        log_runtime(f"OCR startup ok engine=pytesseract tesseract={detected}")
        return True, f"pytesseract ready: {detected}"

    def extract_image_text(self, path: Path) -> OcrResult:
        try:
            from PIL import Image
            import pytesseract
        except Exception as exc:
            message = self._dependency_message(exc)
            log_runtime(message)
            return OcrResult("", "pytesseract", 0.0, False, message)

        available, message = self.is_available()
        if not available:
            return OcrResult("", "pytesseract", 0.0, False, message)

        try:
            log_runtime(f"OCR image start path={path}")
            image = self._prepare_image(Image.open(path))
            text = pytesseract.image_to_string(image, lang="eng+chi_tra", timeout=self.IMAGE_TIMEOUT_SECONDS)
        except Exception as exc:
            message = self._ocr_failure_message(exc)
            log_runtime(f"{message} path={path} detail={type(exc).__name__}: {exc}")
            return OcrResult("", "pytesseract", 0.0, False, message)
        log_runtime(f"OCR image completed path={path} chars={len(text.strip())}")
        return OcrResult(text.strip(), "pytesseract", 0.72 if text.strip() else 0.0, True)

    def extract_pdf_page_text(self, pdf_path: Path, page_index: int) -> OcrResult:
        try:
            import fitz
            from PIL import Image
            import pytesseract
        except Exception as exc:
            message = self._dependency_message(exc, pdf=True)
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
                image = self._prepare_image(image)
                text = pytesseract.image_to_string(image, lang="eng+chi_tra", timeout=self.PDF_PAGE_TIMEOUT_SECONDS)
        except Exception as exc:
            message = self._ocr_failure_message(exc, pdf=True)
            log_runtime(f"{message} path={pdf_path} page_index={page_index} detail={type(exc).__name__}: {exc}")
            return OcrResult("", "pytesseract+fitz", 0.0, False, message)
        log_runtime(f"OCR PDF page completed path={pdf_path} page_index={page_index} chars={len(text.strip())}")
        return OcrResult(text.strip(), "pytesseract+fitz", 0.72 if text.strip() else 0.0, True)

    def _prepare_image(self, image):
        try:
            import cv2
            import numpy as np
            from PIL import Image

            array = np.array(image.convert("RGB"))
            gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
            gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
            thresholded = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                11,
            )
            return Image.fromarray(thresholded)
        except Exception as exc:
            log_runtime(f"OCR image preprocessing skipped: {type(exc).__name__}: {exc}")
            return image

    def _missing_tesseract_message(self) -> str:
        return "尚未安裝 OCR 辨識元件，請安裝 Tesseract 或改用可搜尋 PDF。"

    def _dependency_message(self, exc: Exception, pdf: bool = False) -> str:
        package_hint = "PDF OCR 元件" if pdf else "OCR 元件"
        return f"{package_hint}尚未完整安裝，請重新安裝最新版程式或改用可搜尋 PDF。詳細資訊已寫入 logs/runtime.log。({type(exc).__name__}: {exc})"

    def _ocr_failure_message(self, exc: Exception, pdf: bool = False) -> str:
        text = str(exc).lower()
        if "tesseract" in text or "not installed" in text or "not found" in text:
            return self._missing_tesseract_message()
        if "timeout" in text:
            return "OCR 辨識逾時，請改用較清楚的掃描檔或可搜尋 PDF。"
        target = "PDF OCR" if pdf else "影像 OCR"
        return f"{target} 辨識失敗，請確認檔案是否清晰或改用可搜尋 PDF。詳細資訊已寫入 logs/runtime.log。"
