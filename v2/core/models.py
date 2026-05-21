from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DocumentType(str, Enum):
    DS2_DECLARATION = "DS2報單"
    INVOICE = "INV"
    PACKING_LIST = "PKG"
    BILL_OF_LADING = "B/L"
    ARRIVAL_NOTICE = "到貨通知"
    CLEARANCE_LIST = "清表"
    DATA_CLEARANCE = "資料清表"
    MATERIAL_CLEARANCE = "用料清表"
    DRAWBACK_CLEARANCE = "核退清表"
    BOOKING = "BOOKING"
    SHIPPING_ORDER = "S/O"
    BOOKING_CONFIRMATION = "BOOKING_CONFIRMATION"
    EXPORT_DECLARATION = "出口報單"
    PACKING_DETAIL = "裝箱明細"
    UNKNOWN = "未分類"


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
    HS_CODE = "hs_code"
    PORT = "port"
    CONTAINER_NO = "container_no"
    SEAL_NO = "seal_no"
    VESSEL_VOYAGE = "vessel_voyage"
    VESSEL = "vessel"
    VOYAGE = "voyage"
    BOOKING_NO = "booking_no"
    SHIPPING_ORDER_NO = "shipping_order_no"
    POL = "pol"
    POD = "pod"
    ETD = "etd"
    ETA = "eta"
    CBM = "cbm"
    CARRIER = "carrier"
    FORWARDER = "forwarder"
    NOTIFY = "notify"
    ORIGIN = "origin"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"


class CheckStatus(str, Enum):
    MATCH = "一致"
    MISMATCH = "不一致"
    MISSING = "缺少欄位"
    HIGH_RISK = "高風險 warning"


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
    source_name: str = ""
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
    declaration_value: str = ""
    document_values: dict[str, str] = field(default_factory=dict)
    message: str = ""
    risk_level: str = "normal"


@dataclass
class DocumentCheckReport:
    status: CheckStatus
    summary: str
    declaration: ParsedDocument | None
    documents: list[ParsedDocument] = field(default_factory=list)
    results: list[CheckResult] = field(default_factory=list)
    high_risk_warnings: list[str] = field(default_factory=list)
