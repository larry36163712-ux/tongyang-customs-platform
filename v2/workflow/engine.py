from __future__ import annotations

from pathlib import Path
import traceback
from typing import Callable

from engine.workflow import ConfidenceEngine, WorkflowStateMachine
from v2.audit import AIAuditSummaryEngine, CustomsAuditEngine
from v2.core.settings import app_base_dir
from v2.parsers import ParserContext, ParserRegistry, default_parser_registry
from v2.rules import RuleEngine
from v2.workflow.cache import WorkflowCache
from v2.workflow.intake import FileIntakeEngine
from v2.workflow.matcher import WorkflowMatcher
from v2.workflow.models import WorkflowResult
from v2.workflow.splitter import SmartDocumentSplitter


ProgressCallback = Callable[[str, int, str], None]


class WorkflowPipelineError(RuntimeError):
    def __init__(self, stage: str, message: str, traceback_text: str = "") -> None:
        super().__init__(message)
        self.stage = stage
        self.traceback_text = traceback_text


class DocumentWorkflowEngine:
    def __init__(
        self,
        parser_registry: ParserRegistry | None = None,
        cache_root: Path | None = None,
        rules_path: Path | None = None,
    ) -> None:
        base = app_base_dir()
        self.cache = WorkflowCache(cache_root or base / "parser_cache" / "workflow")
        self.intake = FileIntakeEngine(self.cache)
        self.splitter = SmartDocumentSplitter()
        self.parsers = parser_registry or default_parser_registry()
        self.matcher = WorkflowMatcher()
        self.audit = CustomsAuditEngine()
        self.rules = RuleEngine(rules_path or base / "config" / "rules")
        self.audit_summary = AIAuditSummaryEngine()
        self.confidence = ConfidenceEngine()
        self.state_machine = WorkflowStateMachine()

    def process_paths(
        self,
        paths: list[str],
        direction: str = "import",
        progress: ProgressCallback | None = None,
    ) -> WorkflowResult:
        def emit(stage: str, percent: int, message: str) -> None:
            if progress:
                progress(stage, percent, message)

        def fail(stage: str, exc: Exception) -> WorkflowPipelineError:
            return WorkflowPipelineError(stage, f"{type(exc).__name__}: {exc}", traceback.format_exc())

        try:
            emit("Upload", 5, f"received {len(paths)} file(s)")
            if not paths:
                raise ValueError("no files were provided to workflow pipeline")
            intake_files = self.intake.load_paths(paths)
            if not intake_files:
                raise ValueError("no supported files were loaded; supported: pdf, txt, csv, tsv, xlsx, images")
            emit("OCR", 25, f"loaded text/OCR for {len(intake_files)} file(s)")
        except Exception as exc:
            raise fail("OCR", exc) from exc

        segments = []
        try:
            for intake_file in intake_files:
                file_segments = self.splitter.split(intake_file)
                segments.extend(file_segments)
            emit("Document Split", 45, f"split into {len(segments)} document segment(s)")
        except Exception as exc:
            raise fail("Document Split", exc) from exc

        try:
            parsed_count = 0
            for segment in segments:
                context = ParserContext(
                    source_path=segment.source_path,
                    source_name=segment.source_name,
                    page_start=segment.page_start,
                    page_end=segment.page_end,
                    mime_type=segment.source_path.suffix,
                    metadata={"detected_type": segment.detected_type.value},
                )
                segment.parser_result = self.parsers.parse(segment.text, context)
                segment.detected_type = segment.parser_result.document.document_type
                segment.confidence = max(segment.confidence, segment.parser_result.confidence)
                segment.debug.update(segment.parser_result.debug)
                parsed_count += 1
            emit("Type Detection", 60, f"parsed {parsed_count} segment(s)")
        except Exception as exc:
            raise fail("parser", exc) from exc

        try:
            cases = self.matcher.group_cases(segments, direction=direction)
            emit("Workflow Match", 76, f"grouped into {len(cases)} workflow case(s)")
        except Exception as exc:
            raise fail("workflow grouping", exc) from exc

        try:
            for case in cases:
                self.audit.audit_case(case)
                self.rules.apply(case)
                confidence = self.confidence.assess_case(case)
                case.workflow_state = self.state_machine.resolve(case, confidence.is_low_confidence).value
                self.audit_summary.summarize_case(case)
            emit("Audit", 92, f"audited {len(cases)} workflow case(s)")
        except Exception as exc:
            raise fail("audit", exc) from exc

        emit("Completed", 100, "workflow pipeline completed")

        return WorkflowResult(
            direction=direction,
            intake_files=intake_files,
            segments=segments,
            cases=cases,
            debug={
                "intake_count": len(intake_files),
                "segment_count": len(segments),
                "case_count": len(cases),
                "parser_count": len(self.parsers.parsers),
                "rule_count": len(self.rules.rules),
                "workflow_state_machine": "engine.workflow.workflow_state_machine",
            },
        )
