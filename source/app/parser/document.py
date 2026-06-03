from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UploadedDocument:
    doc_type: str
    original_path: Path
    stored_path: Path

    @property
    def display_name(self) -> str:
        return self.original_path.name


@dataclass(frozen=True)
class ParsedDocument:
    doc_type: str
    source_name: str
    fields: dict[str, str]
    text: str = ""
    error: str = ""
