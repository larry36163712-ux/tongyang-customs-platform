from __future__ import annotations

from v2.core.models import DocumentType
from v2.core.parser_engine import SemanticParserEngine
from v2.core.document_understanding import SemanticDocumentClassifier
from v2.workflow.models import DocumentSegment, IntakeFile


class SmartDocumentSplitter:
    def __init__(self, classifier: SemanticParserEngine | None = None) -> None:
        self.classifier = classifier or SemanticParserEngine()
        self.semantic_classifier = SemanticDocumentClassifier()

    def split(self, intake: IntakeFile) -> list[DocumentSegment]:
        if intake.suffix != ".pdf" or len(intake.pages) <= 1:
            candidate = self.semantic_classifier.best(intake.text, intake.path.name)
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
                    candidates=self.semantic_classifier.classify(intake.text, intake.path.name),
                    manual_confirm_reason=self._manual_reason(candidate),
                    debug={"split_reason": "single-document", "understanding_reasons": candidate.reasons},
                )
            ]

        segments: list[DocumentSegment] = []
        current_type: DocumentType | None = None
        current_pages: list[tuple[int, str]] = []
        for page in intake.pages:
            candidate = self.semantic_classifier.best(page.text, intake.path.name)
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
        candidate = self.semantic_classifier.best(text, intake.path.name)
        candidates = self.semantic_classifier.classify(text, intake.path.name)
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
            manual_confirm_reason=self._manual_reason(candidate),
            debug={"split_reason": "page-type-change", "page_count": len(pages), "understanding_reasons": candidate.reasons},
        )

    def _confidence(self, document_type: DocumentType, text: str) -> float:
        if not text.strip():
            return 0.0
        if document_type == DocumentType.UNKNOWN:
            return 0.3
        return 0.75

    def _manual_reason(self, candidate) -> str:
        if not candidate.needs_manual_confirm:
            return ""
        if candidate.document_type == DocumentType.DS2_DECLARATION:
            return "偵測到報單語意欄位，但 OCR 或欄位解析不完整，需人工確認是否為正式 DS2 報單。"
        if candidate.document_type == DocumentType.ARRIVAL_NOTICE:
            return "偵測到到貨通知特徵，但船公司或費用欄位不完整，需人工確認。"
        if candidate.document_type == DocumentType.UNKNOWN:
            return "AI 無法完全辨識此文件，請人工確認文件用途。"
        return "AI 辨識信心不足，需人工確認文件類型。"
