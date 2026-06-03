from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from v2.core.models import DocumentCheckReport, DocumentType, ParsedDocument
from v2.core.document_understanding import DocumentCandidate
from v2.parsers.base import ParserResult


class CaseStatus(str, Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    EXCEPTION = "exception"
    MISSING_DOCUMENTS = "missing_documents"


@dataclass(frozen=True)
class IntakePage:
    number: int
    text: str
    ocr_used: bool = False
    ocr_message: str = ""


@dataclass
class IntakeFile:
    path: Path
    suffix: str
    pages: list[IntakePage]
    text: str
    debug: dict[str, object] = field(default_factory=dict)


@dataclass
class DocumentSegment:
    source_path: Path
    source_name: str
    page_start: int
    page_end: int
    text: str
    detected_type: DocumentType
    confidence: float
    document_confidence: float = 0.0
    candidates: list[DocumentCandidate] = field(default_factory=list)
    manual_confirm_reason: str = ""
    parser_result: ParserResult | None = None
    debug: dict[str, object] = field(default_factory=dict)

    @property
    def parsed(self) -> ParsedDocument | None:
        return self.parser_result.document if self.parser_result else None


@dataclass
class CaseWorkflow:
    case_id: str
    status: CaseStatus
    direction: str = "import"
    documents: list[DocumentSegment] = field(default_factory=list)
    match_keys: dict[str, str] = field(default_factory=dict)
    audit_report: DocumentCheckReport | None = None
    audit_summary: Any | None = None
    rule_findings: list[str] = field(default_factory=list)
    missing_documents: list[str] = field(default_factory=list)
    manual_confirm_queue: list[str] = field(default_factory=list)
    fallback_document_candidates: dict[str, list[str]] = field(default_factory=dict)
    workflow_state: str = "PENDING_MATCH"
    grouping_confidence: str = "pending_review"
    grouping_score: float = 0.0
    grouping_reasons: list[str] = field(default_factory=list)
    unresolved_fields: list[str] = field(default_factory=list)
    case_organizer: Any | None = None


@dataclass
class WorkflowResult:
    direction: str
    intake_files: list[IntakeFile]
    segments: list[DocumentSegment]
    cases: list[CaseWorkflow]
    debug: dict[str, object] = field(default_factory=dict)
