from __future__ import annotations

from dataclasses import dataclass, field

from v2.parsers.base import DocumentParser, ParserContext, ParserResult
from v2.parsers.booking import BookingParser
from v2.parsers.semantic import SemanticDocumentParser
from v2.core.runtime_log import log_exception, log_runtime


@dataclass
class ParserRegistry:
    parsers: list[DocumentParser] = field(default_factory=list)

    def register(self, parser: DocumentParser) -> None:
        self.parsers.append(parser)

    def parse(self, text: str, context: ParserContext) -> ParserResult:
        candidates: list[DocumentParser] = []
        for parser in self.parsers:
            try:
                if parser.supports(text, context):
                    candidates.append(parser)
            except Exception as exc:
                log_exception(f"parser supports crash parser={parser.name} source={context.source_name}", exc)
                raise RuntimeError(f"parser supports crash: {parser.name}: {exc}") from exc
        if not candidates:
            candidates = self.parsers
        if not candidates:
            raise RuntimeError("No document parsers registered.")

        results: list[ParserResult] = []
        for parser in candidates:
            try:
                log_runtime(f"parser candidate start parser={parser.name} source={context.source_name}")
                result = parser.parse(text, context)
                log_runtime(
                    f"parser candidate completed parser={parser.name} source={context.source_name} "
                    f"confidence={result.confidence} type={result.document.document_type.value}"
                )
                results.append(result)
            except Exception as exc:
                log_exception(f"parser candidate crash parser={parser.name} source={context.source_name}", exc)
                raise RuntimeError(f"parser crash: {parser.name}: {exc}") from exc
        return max(results, key=lambda result: result.confidence)


def default_parser_registry() -> ParserRegistry:
    registry = ParserRegistry()
    registry.register(BookingParser())
    registry.register(SemanticDocumentParser())
    return registry
