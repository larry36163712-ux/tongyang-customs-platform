from __future__ import annotations

from dataclasses import dataclass

from v2.workflow.models import CaseWorkflow


@dataclass(frozen=True)
class DocumentRelationship:
    case_id: str
    document_name: str
    document_type: str
    match_keys: dict[str, str]
    page_range: str


class RelationshipEngine:
    """Extracts document-to-case relationships for audit workflow reasoning."""

    def relationships_for_case(self, case: CaseWorkflow) -> list[DocumentRelationship]:
        relationships: list[DocumentRelationship] = []
        for segment in case.documents:
            document_type = segment.parsed.document_type.value if segment.parsed else segment.detected_type.value
            relationships.append(
                DocumentRelationship(
                    case_id=case.case_id,
                    document_name=segment.source_name,
                    document_type=document_type,
                    match_keys=dict(case.match_keys),
                    page_range=f"{segment.page_start}-{segment.page_end}",
                )
            )
        return relationships

