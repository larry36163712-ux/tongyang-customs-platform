from __future__ import annotations

from v2.core.models import DocumentType
from v2.core.parser_engine import SemanticParserEngine
from v2.parsers.base import ParserContext, ParserResult


class SemanticDocumentParser:
    name = "semantic-core"

    def __init__(self) -> None:
        self.engine = SemanticParserEngine()

    def supports(self, text: str, context: ParserContext) -> bool:
        return bool(text.strip())

    def parse(self, text: str, context: ParserContext) -> ParserResult:
        document = self.engine.parse_document(text, source_name=context.source_name)
        confidence = 0.35
        if document.document_type != DocumentType.UNKNOWN:
            confidence += 0.3
        if document.fields:
            confidence += min(0.3, len(document.fields) * 0.03)
        document.raw_metadata.update(
            {
                "parser": self.name,
                "page_start": context.page_start,
                "page_end": context.page_end,
                "mime_type": context.mime_type,
            }
        )
        return ParserResult(
            document=document,
            confidence=min(confidence, 0.95),
            parser_name=self.name,
            debug={
                "field_count": len(document.fields),
                "document_type": document.document_type.value,
                "source": context.source_name,
            },
        )
