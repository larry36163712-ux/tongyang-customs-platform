from __future__ import annotations

from v2.core.models import DocumentType
from v2.core.parser_engine import SemanticParserEngine
from v2.workflow.models import DocumentSegment, IntakeFile


class SmartDocumentSplitter:
    def __init__(self, classifier: SemanticParserEngine | None = None) -> None:
        self.classifier = classifier or SemanticParserEngine()

    def split(self, intake: IntakeFile) -> list[DocumentSegment]:
        if intake.suffix != ".pdf" or len(intake.pages) <= 1:
            detected = self.classifier.classify_document(intake.text)
            return [
                DocumentSegment(
                    source_path=intake.path,
                    source_name=intake.path.name,
                    page_start=1,
                    page_end=max(1, len(intake.pages)),
                    text=intake.text,
                    detected_type=detected,
                    confidence=self._confidence(detected, intake.text),
                    debug={"split_reason": "single-document"},
                )
            ]

        segments: list[DocumentSegment] = []
        current_type: DocumentType | None = None
        current_pages: list[tuple[int, str]] = []
        for page in intake.pages:
            page_type = self.classifier.classify_document(page.text)
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
        return DocumentSegment(
            source_path=intake.path,
            source_name=f"{intake.path.name} p{pages[0][0]}-{pages[-1][0]}",
            page_start=pages[0][0],
            page_end=pages[-1][0],
            text=text,
            detected_type=document_type,
            confidence=self._confidence(document_type, text),
            debug={"split_reason": "page-type-change", "page_count": len(pages)},
        )

    def _confidence(self, document_type: DocumentType, text: str) -> float:
        if not text.strip():
            return 0.0
        if document_type == DocumentType.UNKNOWN:
            return 0.3
        return 0.75
