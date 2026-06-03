from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ClassifiedDocument:
    path: Path
    source_name: str
    suffix: str
    document_type: str
    confidence: float
    text: str
    keys: dict[str, str] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Shipment:
    shipment_id: str
    invoice: ClassifiedDocument | None = None
    packing: ClassifiedDocument | None = None
    declaration: ClassifiedDocument | None = None
    bl: ClassifiedDocument | None = None
    so: ClassifiedDocument | None = None
    material_list: ClassifiedDocument | None = None
    drawback_standard: ClassifiedDocument | None = None
    tax_sheet: ClassifiedDocument | None = None
    images: list[ClassifiedDocument] = field(default_factory=list)
    other_documents: list[ClassifiedDocument] = field(default_factory=list)
    audit_result: object | None = None
    grouping_keys: dict[str, str] = field(default_factory=dict)
    grouping_confidence: str = "pending_review"
    grouping_reasons: list[str] = field(default_factory=list)

    @property
    def documents(self) -> list[ClassifiedDocument]:
        ordered = [
            self.invoice,
            self.packing,
            self.declaration,
            self.bl,
            self.so,
            self.material_list,
            self.drawback_standard,
            self.tax_sheet,
        ]
        return [doc for doc in ordered if doc is not None] + self.images + self.other_documents

    @property
    def paths(self) -> list[str]:
        return [str(document.path) for document in self.documents]
