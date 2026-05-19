from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DocumentType(str, Enum):
    INVOICE = "INV"
    PACKING_LIST = "PKG"
    BILL_OF_LADING = "B/L"
    DATA_CLEARANCE = "資料清表"
    MATERIAL_CLEARANCE = "用料清表"
    DRAWBACK_CLEARANCE = "核退清表"


class CanonicalField(str, Enum):
    QUANTITY = "quantity"
    PACKAGE_COUNT = "package_count"
    UNIT = "unit"
    ITEM_NO = "item_no"
    DESCRIPTION = "description"
    GROSS_WEIGHT = "gross_weight"
    NET_WEIGHT = "net_weight"
    AMOUNT = "amount"
    CURRENCY = "currency"
    ORIGIN = "origin"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"


class CheckStatus(str, Enum):
    MATCH = "一致"
    MISMATCH = "不一致"
    MISSING = "缺少欄位"


@dataclass(frozen=True)
class SemanticAlias:
    canonical: CanonicalField
    aliases: tuple[str, ...]


@dataclass
class ParsedField:
    canonical: CanonicalField
    source_label: str
    value: str
    confidence: float
    evidence: str = ""


@dataclass
class ParsedDocument:
    document_type: DocumentType
    customer: str
    supplier: str
    template_id: str
    fields: list[ParsedField] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TemplateProfile:
    template_id: str
    customer: str
    supplier: str
    country: str
    document_type: DocumentType
    signature_terms: tuple[str, ...]
    sample_count: int = 0
    failure_count: int = 0


@dataclass
class BacktestMetric:
    label: str
    value: str
    trend: str


@dataclass
class CheckResult:
    field: CanonicalField
    status: CheckStatus
    invoice_value: str = ""
    packing_value: str = ""
    message: str = ""


@dataclass
class DocumentCheckReport:
    status: CheckStatus
    summary: str
    invoice: ParsedDocument
    packing: ParsedDocument
    results: list[CheckResult] = field(default_factory=list)
