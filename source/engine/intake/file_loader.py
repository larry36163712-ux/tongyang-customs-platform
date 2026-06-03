from __future__ import annotations

from pathlib import Path

from v2.workflow.cache import WorkflowCache
from v2.workflow.intake import FileIntakeEngine
from v2.workflow.models import IntakeFile


class IntakeFileLoader:
    """Loads real file content through the active OCR/intake implementation."""

    def __init__(self, cache: WorkflowCache) -> None:
        self.loader = FileIntakeEngine(cache)

    def load(self, path: Path) -> IntakeFile:
        return self.loader.load_file(path)
