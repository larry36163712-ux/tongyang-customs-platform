from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import traceback

from engine.intake.document_classifier import DocumentClassifier
from engine.intake.file_loader import IntakeFileLoader
from engine.intake.folder_scanner import FolderScanner
from engine.intake.shipment_grouper import ShipmentGrouper
from engine.intake.shipment_model import ClassifiedDocument, Shipment
from v2.workflow.cache import WorkflowCache


@dataclass
class IntakePipelineResult:
    folder: Path
    scanned_files: list[Path]
    documents: list[ClassifiedDocument]
    shipments: list[Shipment]
    errors: list[str]

    @property
    def paths(self) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for shipment in self.shipments:
            for path in shipment.paths:
                if path not in seen:
                    seen.add(path)
                    paths.append(path)
        return paths


class IntakePipeline:
    def __init__(
        self,
        cache: WorkflowCache,
        scanner: FolderScanner | None = None,
        classifier: DocumentClassifier | None = None,
        grouper: ShipmentGrouper | None = None,
    ) -> None:
        self.scanner = scanner or FolderScanner()
        self.loader = IntakeFileLoader(cache)
        self.classifier = classifier or DocumentClassifier()
        self.grouper = grouper or ShipmentGrouper()

    def run(self, folder: str | Path, recursive: bool = True) -> IntakePipelineResult:
        root = Path(folder)
        scanned_files = self.scanner.scan(root, recursive=recursive)
        documents: list[ClassifiedDocument] = []
        errors: list[str] = []

        for path in scanned_files:
            try:
                intake_file = self.loader.load(path)
                documents.append(self.classifier.classify(intake_file))
            except Exception as exc:
                errors.append(f"{path.name}: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")

        shipments = self.grouper.group(documents)
        return IntakePipelineResult(root, scanned_files, documents, shipments, errors)
