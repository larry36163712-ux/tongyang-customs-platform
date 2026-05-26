from __future__ import annotations

from pathlib import Path
import traceback
from typing import Callable

from engine.intake import IntakePipeline
from engine.workflow import ConfidenceEngine, WorkflowStateMachine
from v2.audit import AIAuditSummaryEngine, CustomsAuditEngine
from v2.core.runtime_log import log_exception, log_runtime
from v2.core.settings import app_base_dir, resource_path
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
        log_runtime(f"workflow engine startup base={base} cache_root={cache_root} rules_path={rules_path}")
        try:
            self.cache = WorkflowCache(cache_root or base / "parser_cache" / "workflow")
            log_runtime(f"workflow cache ready path={self.cache.root}")
            self.intake = FileIntakeEngine(self.cache)
            ocr_available, ocr_message = self.intake.ocr.is_available()
            log_runtime(f"OCR runtime check available={ocr_available} message={ocr_message}")
            log_runtime("OCR/file intake engine initialized")
            self.splitter = SmartDocumentSplitter()
            log_runtime("document splitter initialized")
            self.parsers = parser_registry or default_parser_registry()
            log_runtime(f"parser registry initialized parsers={[parser.name for parser in self.parsers.parsers]}")
            self.matcher = WorkflowMatcher()
            log_runtime("workflow matcher initialized")
            self.audit = CustomsAuditEngine()
            log_runtime("audit engine initialized")
            self.rules = RuleEngine(rules_path or resource_path("config", "rules"))
            log_runtime(f"rule engine initialized rules_path={self.rules.rules_path} rule_count={len(self.rules.rules)}")
            self.audit_summary = AIAuditSummaryEngine()
            self.confidence = ConfidenceEngine()
            self.state_machine = WorkflowStateMachine()
            self.folder_intake = IntakePipeline(self.cache)
            log_runtime("workflow engine startup completed")
        except Exception as exc:
            log_exception("workflow engine startup", exc)
            raise

    def process_folder(
        self,
        folder: str,
        direction: str = "import",
        progress: ProgressCallback | None = None,
    ) -> WorkflowResult:
        def emit(stage: str, percent: int, message: str) -> None:
            log_runtime(f"workflow progress stage={stage} percent={percent} message={message}")
            if progress:
                progress(stage, percent, message)

        def fail(stage: str, exc: Exception) -> WorkflowPipelineError:
            return WorkflowPipelineError(stage, f"{type(exc).__name__}: {exc}", traceback.format_exc())

        try:
            log_runtime(f"process_folder start folder={folder} direction={direction}")
            emit("Upload", 2, f"started: scanning intake folder {folder}")
            intake_result = self.folder_intake.run(folder)
            if not intake_result.scanned_files:
                raise ValueError("no supported files found in intake folder")
            if not intake_result.paths:
                error_text = "\n\n".join(intake_result.errors) if intake_result.errors else "no classifiable files"
                raise ValueError(f"no files could be loaded from intake folder: {error_text}")
            emit(
                "Upload",
                8,
                f"completed: scanned {len(intake_result.scanned_files)} file(s), "
                f"classified {len(intake_result.documents)} document(s), "
                f"grouped {len(intake_result.shipments)} shipment(s)",
            )
        except Exception as exc:
            log_exception("process_folder upload", exc)
            raise fail("Upload", exc) from exc

        def downstream_progress(stage: str, percent: int, message: str) -> None:
            if stage == "Upload":
                return
            emit(stage, percent, message)

        result = self.process_paths(intake_result.paths, direction=direction, progress=downstream_progress)
        result.debug["auto_intake"] = {
            "folder": str(intake_result.folder),
            "scanned_files": [str(path) for path in intake_result.scanned_files],
            "errors": intake_result.errors,
            "documents": [
                {
                    "source_name": document.source_name,
                    "document_type": document.document_type,
                    "confidence": document.confidence,
                    "keys": document.keys,
                    "reasons": document.reasons,
                    "warnings": document.warnings,
                }
                for document in intake_result.documents
            ],
            "shipments": [
                {
                    "shipment_id": shipment.shipment_id,
                    "paths": shipment.paths,
                    "grouping_keys": shipment.grouping_keys,
                    "grouping_confidence": shipment.grouping_confidence,
                    "grouping_reasons": shipment.grouping_reasons,
                }
                for shipment in intake_result.shipments
            ],
        }
        return result

    def process_paths(
        self,
        paths: list[str],
        direction: str = "import",
        progress: ProgressCallback | None = None,
    ) -> WorkflowResult:
        def emit(stage: str, percent: int, message: str) -> None:
            log_runtime(f"workflow progress stage={stage} percent={percent} message={message}")
            if progress:
                progress(stage, percent, message)

        def fail(stage: str, exc: Exception) -> WorkflowPipelineError:
            return WorkflowPipelineError(stage, f"{type(exc).__name__}: {exc}", traceback.format_exc())

        try:
            log_runtime(f"process_paths start count={len(paths)} direction={direction} paths={paths}")
            emit("Upload", 3, f"started: received {len(paths)} file(s)")
            if not paths:
                raise ValueError("no files were provided to workflow pipeline")
            emit("OCR", 8, "started: file intake and OCR")
            intake_files = self.intake.load_paths(paths)
            if not intake_files:
                raise ValueError("no supported files were loaded; supported: pdf, txt, csv, tsv, xlsx, images")
            emit("OCR", 35, f"completed: loaded text/OCR for {len(intake_files)} file(s)")
        except Exception as exc:
            log_exception("workflow OCR/file intake", exc)
            raise fail("OCR", exc) from exc

        segments = []
        try:
            emit("Document Split", 38, "started: document split")
            for intake_file in intake_files:
                file_segments = self.splitter.split(intake_file)
                segments.extend(file_segments)
            emit("Document Split", 48, f"completed: split into {len(segments)} document segment(s)")
        except Exception as exc:
            log_exception("workflow document split", exc)
            raise fail("Document Split", exc) from exc

        try:
            emit("parser", 50, "started: parser and type detection")
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
                try:
                    log_runtime(f"parser start source={segment.source_name} detected={segment.detected_type.value}")
                    segment.parser_result = self.parsers.parse(segment.text, context)
                    log_runtime(
                        f"parser completed source={segment.source_name} parser={segment.parser_result.parser_name} "
                        f"type={segment.parser_result.document.document_type.value} fields={len(segment.parser_result.document.fields)}"
                    )
                except Exception as parser_exc:
                    log_exception(f"parser crash source={segment.source_name}", parser_exc)
                    raise RuntimeError(f"parser crash for {segment.source_name}: {parser_exc}") from parser_exc
                segment.detected_type = segment.parser_result.document.document_type
                segment.confidence = max(segment.confidence, segment.parser_result.confidence)
                segment.debug.update(segment.parser_result.debug)
                parsed_count += 1
            emit("parser", 65, f"completed: parsed {parsed_count} segment(s)")
        except Exception as exc:
            log_exception("workflow parser", exc)
            raise fail("parser", exc) from exc

        try:
            emit("workflow grouping", 68, "started: workflow grouping")
            cases = self.matcher.group_cases(segments, direction=direction)
            log_runtime(f"workflow grouping completed case_count={len(cases)}")
            emit("workflow grouping", 78, f"completed: grouped into {len(cases)} workflow case(s)")
        except Exception as exc:
            log_exception("workflow grouping", exc)
            raise fail("workflow grouping", exc) from exc

        try:
            emit("audit", 82, "started: audit engine")
            for case in cases:
                log_runtime(f"audit case start case_id={case.case_id} document_count={len(case.documents)}")
                self.audit.audit_case(case)
                self.rules.apply(case)
                confidence = self.confidence.assess_case(case)
                case.workflow_state = self.state_machine.resolve(case, confidence.is_low_confidence).value
                self.audit_summary.summarize_case(case)
                log_runtime(f"audit case completed case_id={case.case_id} status={case.status.value} state={case.workflow_state}")
            emit("audit", 94, f"completed: audited {len(cases)} workflow case(s)")
        except Exception as exc:
            log_exception("workflow audit", exc)
            raise fail("audit", exc) from exc

        emit("Completed", 100, "completed: workflow pipeline completed")
        log_runtime("process_paths completed")

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
