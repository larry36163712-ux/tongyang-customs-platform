from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OcrResult:
    text: str
    engine: str
    confidence: float
    available: bool
    message: str = ""


class OcrEngine:
    """OCR boundary used by intake for scanned PDFs and image files.

    It uses pytesseract/Pillow when installed. When unavailable, the engine
    reports a structured missing-OCR state so workflow/debug can surface it.
    """

    def extract_image_text(self, path: Path) -> OcrResult:
        try:
            from PIL import Image
            import pytesseract
        except Exception as exc:
            return OcrResult("", "pytesseract", 0.0, False, f"OCR dependency unavailable: {exc}")

        try:
            text = pytesseract.image_to_string(Image.open(path), lang="eng+chi_tra")
        except Exception as exc:
            return OcrResult("", "pytesseract", 0.0, False, f"OCR failed: {exc}")
        return OcrResult(text.strip(), "pytesseract", 0.72 if text.strip() else 0.0, True)

    def extract_pdf_page_text(self, _pdf_path: Path, _page_index: int) -> OcrResult:
        return OcrResult("", "pytesseract", 0.0, False, "PDF page OCR renderer is not installed.")
