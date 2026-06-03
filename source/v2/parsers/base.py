from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from v2.core.models import ParsedDocument


@dataclass(frozen=True)
class ParserContext:
    source_path: Path | None = None
    source_name: str = ""
    page_start: int = 1
    page_end: int = 1
    mime_type: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class ParserResult:
    document: ParsedDocument
    confidence: float
    parser_name: str
    debug: dict[str, object] = field(default_factory=dict)


class DocumentParser(Protocol):
    name: str

    def supports(self, text: str, context: ParserContext) -> bool:
        ...

    def parse(self, text: str, context: ParserContext) -> ParserResult:
        ...
