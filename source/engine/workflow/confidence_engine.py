from __future__ import annotations

from dataclasses import dataclass, field

from v2.workflow.models import CaseWorkflow


@dataclass(frozen=True)
class ConfidenceAssessment:
    average_confidence: float
    minimum_confidence: float
    low_confidence_documents: list[str] = field(default_factory=list)

    @property
    def is_low_confidence(self) -> bool:
        return bool(self.low_confidence_documents)


class ConfidenceEngine:
    def __init__(self, threshold: float = 0.65) -> None:
        self.threshold = threshold

    def assess_case(self, case: CaseWorkflow) -> ConfidenceAssessment:
        confidences = [segment.confidence for segment in case.documents]
        if not confidences:
            return ConfidenceAssessment(0.0, 0.0, [])
        low = [
            segment.source_name
            for segment in case.documents
            if segment.confidence < self.threshold
        ]
        return ConfidenceAssessment(
            average_confidence=sum(confidences) / len(confidences),
            minimum_confidence=min(confidences),
            low_confidence_documents=low,
        )

