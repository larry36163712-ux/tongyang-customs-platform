from __future__ import annotations

from dataclasses import dataclass, field

from v2.parsers.base import DocumentParser, ParserContext, ParserResult
from v2.parsers.booking import BookingParser
from v2.parsers.semantic import SemanticDocumentParser


@dataclass
class ParserRegistry:
    parsers: list[DocumentParser] = field(default_factory=list)

    def register(self, parser: DocumentParser) -> None:
        self.parsers.append(parser)

    def parse(self, text: str, context: ParserContext) -> ParserResult:
        candidates = [parser for parser in self.parsers if parser.supports(text, context)]
        if not candidates:
            candidates = self.parsers
        if not candidates:
            raise RuntimeError("No document parsers registered.")

        results = [parser.parse(text, context) for parser in candidates]
        return max(results, key=lambda result: result.confidence)


def default_parser_registry() -> ParserRegistry:
    registry = ParserRegistry()
    registry.register(BookingParser())
    registry.register(SemanticDocumentParser())
    return registry
