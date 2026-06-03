from __future__ import annotations

from v2.core.models import DocumentType
from v2.core.parser_engine import SemanticParserEngine
from v2.core.document_understanding import SemanticDocumentClassifier
from v2.workflow.models import DocumentSegment, IntakeFile


class SmartDocumentSplitter:
    def __init__(self, classifier: SemanticParserEngine | None = None) -> None:
        self.classifier = classifier or SemanticParserEngine()
        self.semantic_classifier = SemanticDocumentClassifier()
        self._classification_cache: dict[tuple[str, str], list] = {}

    def split(self, intake: IntakeFile) -> list[DocumentSegment]:
        if intake.suffix != ".pdf" or len(intake.pages) <= 1:
            candidates = self._classify_text(intake.text, intake.path.name)
            candidate = self._best_candidate(candidates)
            detected = candidate.document_type if candidate.document_type != DocumentType.UNKNOWN else self.classifier.classify_document(intake.text)
            return [
                DocumentSegment(
                    source_path=intake.path,
                    source_name=intake.path.name,
                    page_start=1,
                    page_end=max(1, len(intake.pages)),
                    text=intake.text,
                    detected_type=detected,
                    confidence=max(candidate.confidence, self._confidence(detected, intake.text)),
                    document_confidence=candidate.confidence,
                    candidates=candidates,
                    manual_confirm_reason=self._manual_reason(candidate, intake),
                    debug={
                        "split_reason": "single-document",
                        "understanding_reasons": candidate.reasons,
                        **self._intake_debug(intake),
                    },
                )
            ]

        segments: list[DocumentSegment] = []
        current_type: DocumentType | None = None
        current_pages: list[tuple[int, str]] = []
        for page in intake.pages:
            candidate = self._best_candidate(self._classify_text(page.text, intake.path.name))
            page_type = candidate.document_type if candidate.document_type != DocumentType.UNKNOWN else self.classifier.classify_document(page.text)
            if current_type is not None and page_type != current_type and current_pages:
                segments.append(self._build_segment(intake, current_type, current_pages))
                current_pages = []
            current_type = page_type
            current_pages.append((page.number, page.text))
        if current_type is not None and current_pages:
            segments.append(self._build_segment(intake, current_type, current_pages))
        return segments

    def _build_segment(
        self,
        intake: IntakeFile,
        document_type: DocumentType,
        pages: list[tuple[int, str]],
    ) -> DocumentSegment:
        text = "\n\n".join(page_text for _, page_text in pages)
        candidates = self._classify_text(text, intake.path.name)
        candidate = self._best_candidate(candidates)
        return DocumentSegment(
            source_path=intake.path,
            source_name=f"{intake.path.name} p{pages[0][0]}-{pages[-1][0]}",
            page_start=pages[0][0],
            page_end=pages[-1][0],
            text=text,
            detected_type=document_type,
            confidence=max(candidate.confidence, self._confidence(document_type, text)),
            document_confidence=candidate.confidence,
            candidates=candidates,
            manual_confirm_reason=self._manual_reason(candidate, intake),
            debug={
                "split_reason": "page-type-change",
                "page_count": len(pages),
                "understanding_reasons": candidate.reasons,
                **self._intake_debug(intake),
            },
        )

    def _confidence(self, document_type: DocumentType, text: str) -> float:
        if not text.strip():
            return 0.0
        if document_type == DocumentType.UNKNOWN:
            return 0.3
        return 0.75

    def _classify_text(self, text: str, filename: str):
        key = (filename, text)
        if key not in self._classification_cache:
            self._classification_cache[key] = self.semantic_classifier.classify(text, filename)
        return self._classification_cache[key]

    def _best_candidate(self, candidates):
        if candidates:
            return candidates[0]
        return self.semantic_classifier.best("", "")

    def _manual_reason(self, candidate, intake: IntakeFile | None = None) -> str:
        if intake and intake.debug.get("ocr_status") == "manual_review":
            return str(
                intake.debug.get("ocr_message")
                or "此文件可能為掃描檔，OCR 未取得足夠文字，請人工確認文件內容。"
            )
        if getattr(candidate, "score_breakdown", {}).get("classification_timeout") is not None:
            return "文件分類耗時過長，已改用人工確認模式。"
        if not candidate.needs_manual_confirm:
            return ""
        if candidate.document_type == DocumentType.DS2_DECLARATION:
            return "偵測到報單語意欄位，但 OCR 或欄位解析不完整，需人工確認是否為正式 DS2 報單。"
        if candidate.document_type == DocumentType.ARRIVAL_NOTICE:
            return "偵測到到貨通知特徵，但船公司或費用欄位不完整，需人工確認。"
        if candidate.document_type == DocumentType.DELIVERY_ORDER:
            return "偵測到 D/O 或提貨資訊，但放貨與領貨欄位不完整，需人工確認。"
        if candidate.document_type == DocumentType.UNKNOWN:
            return "AI 無法完全辨識此文件，請人工確認文件用途。"
        return "AI 辨識信心不足，需人工確認文件類型。"

    def _intake_debug(self, intake: IntakeFile) -> dict[str, object]:
        return {
            key: value
            for key, value in intake.debug.items()
            if key in {"ocr_status", "ocr_message", "stage"}
        }
