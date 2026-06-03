"""Folder-based customs document intake.

This package is the production intake boundary for folder drops. It reads real
files, classifies them from extracted content, groups shipment files, and then
hands the resolved file paths back to the active v2 workflow pipeline.
"""

from engine.intake.document_classifier import DocumentClassifier
from engine.intake.folder_scanner import FolderScanner
from engine.intake.folder_watcher import FolderChange, FolderWatcher
from engine.intake.intake_pipeline import IntakePipeline, IntakePipelineResult
from engine.intake.shipment_model import ClassifiedDocument, Shipment

__all__ = [
    "ClassifiedDocument",
    "DocumentClassifier",
    "FolderChange",
    "FolderScanner",
    "FolderWatcher",
    "IntakePipeline",
    "IntakePipelineResult",
    "Shipment",
]
