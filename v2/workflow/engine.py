from __future__ import annotations

from pathlib import Path

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

    def process_paths(self, paths: list[str], direction: str = "import") -> WorkflowResult:
        intake_files = self.intake.load_paths(paths)
        segments = []
        for intake_file in intake_files:
            for segment in self.splitter.split(intake_file):
                context = ParserContext(
                    source_path=segment.source_path,
                    source_name=segment.source_name,
                    page_start=segment.page_start,
                    page_end=segment.page_end,
                    mime_type=intake_file.suffix,
                    metadata={"detected_type": segment.detected_type.value},
                )
                segment.parser_result = self.parsers.parse(segment.text, context)
                segment.detected_type = segment.parser_result.document.document_type
                segment.confidence = max(segment.confidence, segment.parser_result.confidence)
                segment.debug.update(segment.parser_result.debug)
                segments.append(segment)

        cases = self.matcher.group_cases(segments, direction=direction)
        for case in cases:
            self.audit.audit_case(case)
            self.rules.apply(case)
            self.audit_summary.summarize_case(case)
            confidence = self.confidence.assess_case(case)
            case.workflow_state = self.state_machine.resolve(case, confidence.is_low_confidence).value

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
