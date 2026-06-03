from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from v2.core.models import ParsedDocument
from v2.core.parser_engine import SemanticParserEngine


SUPPORTED_SUFFIXES = {".pdf", ".txt", ".csv", ".tsv"}


@dataclass(frozen=True)
class LoadedDocument:
    path: Path
    text: str
    parsed: ParsedDocument


class DocumentLoader:
    def __init__(self, parser: SemanticParserEngine | None = None) -> None:
        self.parser = parser or SemanticParserEngine()

    def load_paths(self, paths: list[str]) -> list[LoadedDocument]:
        loaded: list[LoadedDocument] = []
        for raw_path in paths:
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            text = self.extract_text(path)
            parsed = self.parser.parse_document(text, source_name=path.name)
            loaded.append(LoadedDocument(path=path, text=text, parsed=parsed))
        return loaded

    def extract_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._extract_pdf(path)
        for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(errors="ignore")

    def _extract_pdf(self, path: Path) -> str:
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n".join(pages)

