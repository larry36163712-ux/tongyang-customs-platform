from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re

from v2.core.models import CanonicalField, CheckStatus, DocumentType
from v2.workflow.matcher import WorkflowMatcher
from v2.workflow.models import CaseWorkflow, DocumentSegment


FIELD_LABELS = {
    CanonicalField.VESSEL: "船名",
    CanonicalField.VOYAGE: "航次",
    CanonicalField.VESSEL_VOYAGE: "船名航次",
    CanonicalField.BL_NO: "提單號",
    CanonicalField.BOOKING_NO: "Booking No",
    CanonicalField.SHIPPING_ORDER_NO: "S/O No",
    CanonicalField.DECLARATION_NO: "報單號碼",
    CanonicalField.INVOICE_NO: "INV NO",
    CanonicalField.CONTAINER_NO: "櫃號",
    CanonicalField.SEAL_NO: "封條",
    CanonicalField.POL: "裝貨港",
    CanonicalField.POD: "卸貨港",
    CanonicalField.PORT: "港口",
    CanonicalField.ETA: "ETA",
    CanonicalField.ETD: "ETD",
    CanonicalField.CARRIER: "船公司",
    CanonicalField.FORWARDER: "Forwarder",
    CanonicalField.NOTIFY: "Notify",
    CanonicalField.CUSTOMER: "Consignee / 買方",
    CanonicalField.SUPPLIER: "Shipper / 賣方",
    CanonicalField.DESCRIPTION: "品名",
    CanonicalField.ITEM_NO: "型號 / 項次",
    CanonicalField.QUANTITY: "數量",
    CanonicalField.UNIT: "單位",
    CanonicalField.PACKAGE_COUNT: "件數",
    CanonicalField.NET_WEIGHT: "淨重",
    CanonicalField.GROSS_WEIGHT: "毛重",
    CanonicalField.AMOUNT: "金額",
    CanonicalField.CBM: "CBM",
    CanonicalField.HS_CODE: "稅則",
    CanonicalField.FOB: "FOB",
    CanonicalField.CIF: "CIF",
    CanonicalField.FREIGHT: "運費",
    CanonicalField.INSURANCE: "保費",
    CanonicalField.CURRENCY: "幣別",
    CanonicalField.EXCHANGE_RATE: "匯率",
    CanonicalField.DUTY_AMOUNT: "稅額",
    CanonicalField.CUSTOMS_VALUE: "完稅價格",
    CanonicalField.TRADE_PROMOTION_FEE: "推貿費",
    CanonicalField.BUSINESS_TAX: "營業稅",
    CanonicalField.IMPORT_REGULATION: "輸入規定",
    CanonicalField.MP1: "MP1",
    CanonicalField.BSMI: "BSMI",
    CanonicalField.COMMODITY_INSPECTION: "商檢",
    CanonicalField.STATISTICAL_METHOD: "統計方式",
    CanonicalField.INCOTERM: "Incoterm",
    CanonicalField.ORIGIN: "產地",
    CanonicalField.CLOSING_DATE: "結關日",
}

DOCUMENT_LABELS = {
    DocumentType.DS2_DECLARATION: "DS2 報單",
    DocumentType.EXPORT_DECLARATION: "出口報單",
    DocumentType.INVOICE: "INV",
    DocumentType.PACKING_LIST: "PL",
    DocumentType.BILL_OF_LADING: "B/L",
    DocumentType.ARRIVAL_NOTICE: "到貨通知",
    DocumentType.DELIVERY_ORDER: "D/O",
    DocumentType.MANIFEST: "艙單",
    DocumentType.SHIPPING_ORDER: "SO",
    DocumentType.BOOKING: "Booking",
    DocumentType.BOOKING_CONFIRMATION: "Booking",
    DocumentType.TAX_SHEET: "稅單",
    DocumentType.CLEARANCE_LIST: "清表",
    DocumentType.DATA_CLEARANCE: "資料清表",
    DocumentType.MATERIAL_CLEARANCE: "用料清表",
    DocumentType.DRAWBACK_CLEARANCE: "核退標準",
    DocumentType.UNKNOWN: "尚未成功辨識",
}


@dataclass(frozen=True)
class OrganizerField:
    label: str
    value: str
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    note: str = ""


@dataclass
class CustomsCaseOrganizerResult:
    case_id: str
    grouping_confidence: str
    shipment_summary: list[OrganizerField] = field(default_factory=list)
    cargo_summary: list[OrganizerField] = field(default_factory=list)
    customs_summary: list[OrganizerField] = field(default_factory=list)
    audit_summary: list[str] = field(default_factory=list)
    missing_documents: list[str] = field(default_factory=list)
    potential_errors: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def human_text(self, detail: bool = False) -> str:
        lines = [
            "一、案件摘要",
            f"案件編號：{self.case_id}",
            f"分票判斷：{_grouping_label(self.grouping_confidence)}",
            "",
            "二、文件完整度",
        ]
        lines.extend(f"- {item}" for item in (self.missing_documents or ["必要文件未發現明確缺口。"]))
        lines.extend(self._section("三、船務資料", self.shipment_summary, detail))
        lines.extend(self._section("四、貨物資料", self.cargo_summary, detail))
        lines.extend(self._section("五、金額 / 報關資料", self.customs_summary, detail))
        lines.extend(["", "六、核對摘要"])
        lines.extend(f"- {item}" for item in (self.audit_summary or ["尚無足夠欄位可完成交叉核對，請先確認文件解析結果。"]))
        lines.extend(["", "七、缺少文件"])
        lines.extend(f"- {item}" for item in (self.missing_documents or ["未發現必要文件完全缺失。"]))
        lines.extend(["", "八、風險提醒"])
        lines.extend(f"- {item}" for item in (self.risk_notes or ["目前未發現重大風險，仍請依正式報單逐項覆核。"]))
        lines.extend(["", "九、可能錯誤"])
        lines.extend(f"- {item}" for item in (self.potential_errors or ["未發現明確不一致；低信心欄位請依原始文件覆核。"]))
        lines.extend(["", "十、建議下一步"])
        lines.extend(f"- {item}" for item in (self.next_actions or ["完成必要文件覆核後，再進入正式進口 / 出口核對流程。"]))
        return "\n".join(lines)

    def _section(self, title: str, fields: list[OrganizerField], detail: bool) -> list[str]:
        lines = ["", title]
        if not fields:
            lines.append("- 尚未取得可整理資料。")
            return lines
        for item in fields:
            sources = f"（來源：{', '.join(item.sources[:3])}）" if detail and item.sources else ""
            note = f"；{item.note}" if item.note else ""
            lines.append(f"- {item.label}：{item.value}{sources}{note}")
        return lines


class CustomsDocumentClassifier:
    def effective_type(self, segment: DocumentSegment) -> DocumentType:
        parsed = segment.parsed
        if parsed and parsed.document_type != DocumentType.UNKNOWN:
            return parsed.document_type
        if segment.detected_type != DocumentType.UNKNOWN:
            return segment.detected_type
        if segment.candidates:
            return segment.candidates[0].document_type
        return DocumentType.UNKNOWN

    def label(self, document_type: DocumentType | str) -> str:
        if isinstance(document_type, str):
            for enum_value in DocumentType:
                if document_type in {enum_value.name, enum_value.value}:
                    return DOCUMENT_LABELS.get(enum_value, enum_value.value)
            return _field_key_to_label(document_type)
        return DOCUMENT_LABELS.get(document_type, document_type.value)


class CustomsSynonymDictionary:
    PACKAGE_UNITS = {
        "BLE": "BALES",
        "BALE": "BALES",
        "BALES": "BALES",
        "PCS": "PCS",
        "PCE": "PCS",
        "PC": "PCS",
        "CTN": "CTNS",
        "CTNS": "CTNS",
        "CARTON": "CTNS",
        "CARTONS": "CTNS",
    }
    FIELD_SYNONYMS = {
        "G.W.": "Gross Weight",
        "GW": "Gross Weight",
        "N.W.": "Net Weight",
        "NW": "Net Weight",
        "HSN CODE": "CCC CODE",
        "HS CODE": "CCC CODE",
        "BL NO": "Bill of Lading No",
        "B/L NO": "Bill of Lading No",
        "ETA": "Estimated Time of Arrival",
    }

    def normalize(self, field: CanonicalField, value: str) -> tuple[str, str]:
        text = " ".join(str(value).strip().split())
        if not text:
            return "", ""
        if field in {CanonicalField.PACKAGE_COUNT, CanonicalField.QUANTITY}:
            return self._package(text)
        if field == CanonicalField.UNIT:
            unit = text.upper().replace(".", "")
            normalized = self.PACKAGE_UNITS.get(unit, unit)
            note = f"{unit} 視為 {normalized}" if unit and unit != normalized else ""
            return normalized, note
        if field in {CanonicalField.GROSS_WEIGHT, CanonicalField.NET_WEIGHT}:
            return self._weight(text)
        if field in {
            CanonicalField.FOB,
            CanonicalField.CIF,
            CanonicalField.AMOUNT,
            CanonicalField.FREIGHT,
            CanonicalField.INSURANCE,
            CanonicalField.DUTY_AMOUNT,
            CanonicalField.CUSTOMS_VALUE,
            CanonicalField.TRADE_PROMOTION_FEE,
            CanonicalField.BUSINESS_TAX,
        }:
            return self._money(text)
        if field in {CanonicalField.HS_CODE, CanonicalField.IMPORT_REGULATION, CanonicalField.MP1, CanonicalField.BSMI}:
            return re.sub(r"\s+", "", text.upper()), ""
        return text, ""

    def equivalent(self, field: CanonicalField, left: str, right: str) -> tuple[bool, str]:
        left_norm, left_note = self.normalize(field, left)
        right_norm, right_note = self.normalize(field, right)
        if left_norm and left_norm == right_norm:
            notes = [note for note in (left_note, right_note) if note]
            return True, "；".join(dict.fromkeys(notes))
        return False, ""

    def _package(self, value: str) -> tuple[str, str]:
        match = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*([A-Z./]+)?", value.upper())
        if not match:
            return value.upper(), ""
        qty = match.group(1).replace(",", "")
        unit = (match.group(2) or "").replace(".", "")
        normalized = self.PACKAGE_UNITS.get(unit, unit)
        note = f"{unit} 視為 {normalized}" if unit and unit != normalized else ""
        return f"{_format_number(qty)} {normalized}".strip(), note

    def _weight(self, value: str) -> tuple[str, str]:
        match = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*([A-Z]+)?", value.upper())
        if not match:
            return value.upper(), ""
        number = _decimal(match.group(1))
        unit = match.group(2) or "KG"
        if number is None:
            return value.upper(), ""
        if unit in {"MT", "MTS", "TON", "TONS"}:
            kg = number * Decimal("1000")
            return f"{_format_decimal(kg)} KG", f"{_format_decimal(number)} {unit} 換算為 {_format_decimal(kg)} KG"
        if unit in {"KG", "KGS", "KGM"}:
            return f"{_format_decimal(number)} KG", f"{unit} 視為 KG" if unit != "KG" else ""
        return f"{_format_decimal(number)} {unit}", ""

    def _money(self, value: str) -> tuple[str, str]:
        currency = ""
        currency_match = re.search(r"\b(USD|TWD|NTD|EUR|JPY|CNY|RMB|GBP|HKD)\b", value.upper())
        if currency_match:
            currency = "CNY" if currency_match.group(1) == "RMB" else currency_match.group(1)
        amount = _decimal(value)
        if amount is None:
            return value.upper(), ""
        return f"{currency} {_format_decimal(amount)}".strip(), "已標準化幣別與千分位"


class VesselVoyageMatcher:
    def partial_pending(self, declaration_value: str, document_values: dict[str, str]) -> tuple[bool, str]:
        declaration = self.split(declaration_value)
        if not declaration["vessel"]:
            return False, ""
        for source, value in document_values.items():
            supporting = self.split(value)
            if declaration["vessel"] != supporting["vessel"]:
                continue
            if declaration["voyage"] and not supporting["voyage"]:
                return True, f"⚠ 航次待確認：船名一致，報單航次 {declaration['voyage']}，佐證文件未取得航次。"
            if supporting["voyage"] and not declaration["voyage"]:
                return True, f"⚠ 航次待確認：船名一致，佐證文件航次 {supporting['voyage']}，報單未取得航次。"
        return False, ""

    def split(self, value: str) -> dict[str, str]:
        tokens = re.findall(r"[A-Z0-9]+", value.upper())
        if not tokens:
            return {"vessel": "", "voyage": ""}
        voyage = ""
        vessel_tokens: list[str] = []
        for token in tokens:
            if re.search(r"\d", token) and not voyage:
                voyage = token
            else:
                vessel_tokens.append(token)
        return {"vessel": " ".join(vessel_tokens), "voyage": voyage}


class SemanticFieldMapper:
    def __init__(self) -> None:
        self.dictionary = CustomsSynonymDictionary()

    def values_by_field(self, case: CaseWorkflow) -> dict[CanonicalField, list[OrganizerField]]:
        values: dict[CanonicalField, list[OrganizerField]] = {}
        for segment in case.documents:
            parsed = segment.parsed
            if not parsed:
                continue
            source = segment.source_name
            for field in parsed.fields:
                value, note = self.dictionary.normalize(field.canonical, str(field.value))
                if not value:
                    continue
                values.setdefault(field.canonical, []).append(
                    OrganizerField(
                        FIELD_LABELS.get(field.canonical, field.canonical.value),
                        value,
                        [source],
                        field.confidence,
                        note,
                    )
                )
        return values

    def best_field(self, values: dict[CanonicalField, list[OrganizerField]], field: CanonicalField) -> OrganizerField | None:
        candidates = values.get(field, [])
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item.confidence, reverse=True)[0]


class ShipmentGroupingEngine:
    """Facade for current grouping decisions, with organizer-level confidence notes."""

    def __init__(self) -> None:
        self.matcher = WorkflowMatcher()

    def group(self, segments: list[DocumentSegment], direction: str = "import") -> list[CaseWorkflow]:
        return self.matcher.group_cases(segments, direction=direction)

    def grouping_notes(self, case: CaseWorkflow) -> list[str]:
        if case.grouping_confidence in {"exact_match", "high_confidence"}:
            return []
        if case.grouping_confidence in {"low_confidence", "pending_review"}:
            return ["分票關聯信心不足，請人工確認 BL No / Invoice No / Booking No / Container No 是否屬於同一票。"]
        return ["分票關聯為部分一致，建議覆核同票文件是否完整。"]


class CustomsSummaryBuilder:
    def __init__(self) -> None:
        self.mapper = SemanticFieldMapper()

    def build_shipment_summary(self, case: CaseWorkflow) -> list[OrganizerField]:
        values = self.mapper.values_by_field(case)
        fields = [
            CanonicalField.VESSEL_VOYAGE,
            CanonicalField.VESSEL,
            CanonicalField.VOYAGE,
            CanonicalField.BL_NO,
            CanonicalField.BOOKING_NO,
            CanonicalField.SHIPPING_ORDER_NO,
            CanonicalField.CONTAINER_NO,
            CanonicalField.SEAL_NO,
            CanonicalField.POL,
            CanonicalField.POD,
            CanonicalField.PORT,
            CanonicalField.ETA,
            CanonicalField.CUSTOMER,
            CanonicalField.SUPPLIER,
            CanonicalField.NOTIFY,
        ]
        return self._fields(values, fields, case.match_keys)

    def build_cargo_summary(self, case: CaseWorkflow) -> list[OrganizerField]:
        values = self.mapper.values_by_field(case)
        return self._fields(
            values,
            [
                CanonicalField.DESCRIPTION,
                CanonicalField.ITEM_NO,
                CanonicalField.QUANTITY,
                CanonicalField.UNIT,
                CanonicalField.PACKAGE_COUNT,
                CanonicalField.NET_WEIGHT,
                CanonicalField.GROSS_WEIGHT,
                CanonicalField.CBM,
                CanonicalField.HS_CODE,
            ],
            case.match_keys,
        )

    def build_customs_summary(self, case: CaseWorkflow) -> list[OrganizerField]:
        values = self.mapper.values_by_field(case)
        return self._fields(
            values,
            [
                CanonicalField.FOB,
                CanonicalField.CIF,
                CanonicalField.CUSTOMS_VALUE,
                CanonicalField.FREIGHT,
                CanonicalField.INSURANCE,
                CanonicalField.CURRENCY,
                CanonicalField.EXCHANGE_RATE,
                CanonicalField.DUTY_AMOUNT,
                CanonicalField.TRADE_PROMOTION_FEE,
                CanonicalField.BUSINESS_TAX,
                CanonicalField.STATISTICAL_METHOD,
                CanonicalField.IMPORT_REGULATION,
                CanonicalField.MP1,
                CanonicalField.BSMI,
                CanonicalField.COMMODITY_INSPECTION,
                CanonicalField.INCOTERM,
                CanonicalField.ORIGIN,
            ],
            case.match_keys,
        )

    def _fields(
        self,
        values: dict[CanonicalField, list[OrganizerField]],
        fields: list[CanonicalField],
        match_keys: dict[str, str],
    ) -> list[OrganizerField]:
        result: list[OrganizerField] = []
        match_key_fields = {
            CanonicalField.BL_NO: "bl_no",
            CanonicalField.BOOKING_NO: "booking_no",
            CanonicalField.SHIPPING_ORDER_NO: "shipping_order_no",
            CanonicalField.CONTAINER_NO: "container_no",
            CanonicalField.VESSEL_VOYAGE: "vessel_voyage",
            CanonicalField.CUSTOMER: "consignee",
            CanonicalField.SUPPLIER: "shipper",
        }
        for field in fields:
            item = self.mapper.best_field(values, field)
            if item:
                result.append(item)
                continue
            key = match_key_fields.get(field)
            if key and match_keys.get(key):
                result.append(OrganizerField(FIELD_LABELS.get(field, field.value), match_keys[key], ["案件關聯資料"], 0.65))
        return result


class AuditSummaryEngine:
    def __init__(self) -> None:
        self.dictionary = CustomsSynonymDictionary()
        self.vessel_voyage = VesselVoyageMatcher()

    def build(self, case: CaseWorkflow) -> list[str]:
        if not case.audit_report:
            return []
        lines: list[str] = []
        for result in case.audit_report.results:
            label = FIELD_LABELS.get(result.field, result.field.value)
            if result.status == CheckStatus.MATCH:
                note = self._equivalence_note(result)
                lines.append(f"✓ {label} 一致{f'（{note}）' if note else ''}")
            elif result.status == CheckStatus.MISMATCH:
                if result.field == CanonicalField.VESSEL_VOYAGE:
                    is_partial, message = self.vessel_voyage.partial_pending(result.declaration_value, result.document_values)
                    if is_partial:
                        lines.append(message)
                        continue
                lines.append(f"✗ {label} 不一致：{self._value_summary(result)}")
            elif result.status == CheckStatus.MISSING:
                lines.append(f"⚠ {label} 缺資料：{self._missing_summary(result)}")
            elif result.status == CheckStatus.HIGH_RISK:
                lines.append(f"✗ {label} 高風險：{self._value_summary(result)}")
        return _dedupe(lines)

    def _equivalence_note(self, result) -> str:
        for value in result.document_values.values():
            same, note = self.dictionary.equivalent(result.field, result.declaration_value, value)
            if same and note:
                return note
        return ""

    def _value_summary(self, result) -> str:
        parts = []
        if result.declaration_value:
            parts.append(f"報單 {result.declaration_value}")
        parts.extend(f"佐證文件 {value}" for value in result.document_values.values())
        return "；".join(parts) if parts else "請人工確認原始文件"

    def _missing_summary(self, result) -> str:
        if result.declaration_value and not result.document_values:
            return f"報單有值 {result.declaration_value}，佐證文件未取得對應欄位"
        if result.document_values and not result.declaration_value:
            values = "；".join(result.document_values.values())
            return f"佐證文件有值（{values}），報單未取得對應欄位"
        return "報單與佐證文件都未取得可核對欄位"


class RiskAnalysisEngine:
    OPTIONAL_FIELDS = {
        CanonicalField.DECLARATION_NO,
        CanonicalField.INVOICE_NO,
        CanonicalField.BOOKING_NO,
        CanonicalField.INCOTERM,
        CanonicalField.FREIGHT,
        CanonicalField.INSURANCE,
        CanonicalField.EXCHANGE_RATE,
        CanonicalField.CLOSING_DATE,
    }

    def __init__(self) -> None:
        self.classifier = CustomsDocumentClassifier()
        self.vessel_voyage = VesselVoyageMatcher()

    def missing_documents(self, case: CaseWorkflow) -> list[str]:
        present_values = self._present_document_values(case)
        items: list[str] = []
        for raw_name in case.missing_documents:
            document_type = self._document_type_from_value(raw_name)
            if document_type == DocumentType.BILL_OF_LADING and self._has_arrival_notice_shipping_evidence(case):
                items.append("⚠ 未取得正式 B/L，目前以到貨通知作為船務佐證。")
                continue
            if document_type and document_type.value in present_values:
                continue
            items.append(f"✗ 缺少 {self.classifier.label(raw_name)}")

        missing_values = set(case.missing_documents)
        for document_type, names in case.fallback_document_candidates.items():
            normalized_type = self._document_type_from_value(document_type)
            normalized_value = normalized_type.value if normalized_type else str(document_type)
            if normalized_value not in missing_values or normalized_value in present_values:
                continue
            items.append(f"⚠ 已收到疑似 {self.classifier.label(document_type)}，需人工確認：{', '.join(names[:3])}")
        return _dedupe(items)

    def potential_errors(self, case: CaseWorkflow) -> list[str]:
        errors: list[str] = []
        if case.grouping_confidence in {"low_confidence", "pending_review"}:
            errors.append("分票關聯信心不足，可能有不同 shipment 混在同一批文件。")
        for segment in case.documents:
            if segment.manual_confirm_reason:
                errors.append("文件辨識需人工確認。")
            if segment.document_confidence and segment.document_confidence < 0.78:
                label = self.classifier.label(self.classifier.effective_type(segment))
                errors.append(f"疑似 {label}，辨識信心 {int(segment.document_confidence * 100)}%。")
        if case.audit_report:
            for result in case.audit_report.results:
                if result.status == CheckStatus.MISMATCH:
                    if self._is_vessel_voyage_partial(result):
                        continue
                    label = FIELD_LABELS.get(result.field, result.field.value)
                    errors.append(f"{label} 不一致，請比對報單與佐證文件。")
                elif result.status == CheckStatus.MISSING and result.field not in self.OPTIONAL_FIELDS:
                    label = FIELD_LABELS.get(result.field, result.field.value)
                    errors.append(f"{label} 缺少可核對資料。")
        return _dedupe(errors)[:14]

    def risk_notes(self, case: CaseWorkflow) -> list[str]:
        notes = []
        notes.extend(self.missing_documents(case))
        notes.extend(self._manual_review_notes(case))
        if case.audit_report:
            for result in case.audit_report.results:
                if result.status == CheckStatus.MISMATCH:
                    if result.field == CanonicalField.VESSEL_VOYAGE:
                        is_partial, message = self.vessel_voyage.partial_pending(result.declaration_value, result.document_values)
                        if is_partial:
                            notes.append(message)
                            continue
                    label = FIELD_LABELS.get(result.field, result.field.value)
                    notes.append(f"{label}與佐證文件不一致，需優先覆核。")
                elif result.status == CheckStatus.HIGH_RISK:
                    label = FIELD_LABELS.get(result.field, result.field.value)
                    notes.append(f"{label}屬高風險欄位，需人工確認。")
        return _dedupe(notes)[:12]

    def next_actions(self, case: CaseWorkflow) -> list[str]:
        actions: list[str] = []
        if case.missing_documents:
            actions.append("先補齊或確認必要文件，避免用非正式文件完成最終申報。")
        if case.grouping_confidence in {"low_confidence", "pending_review"}:
            actions.append("人工確認 BL No / Invoice No / Booking No / Container No 是否屬於同一票。")
        if case.audit_report and any(result.status != CheckStatus.MATCH for result in case.audit_report.results):
            actions.append("逐項覆核差異欄位，必要時更正報單或來源文件。")
        actions.append("確認 CIF / FOB / 運保費 / 稅則 / 統計方式 / 輸入規定是否符合實務申報。")
        return _dedupe(actions)

    def _manual_review_notes(self, case: CaseWorkflow) -> list[str]:
        missing_values = set(case.missing_documents)
        present_values = self._present_document_values(case)
        notes: list[str] = []
        for note in case.manual_confirm_queue:
            should_skip = False
            document_label = self._manual_review_document_label(note)
            for document_type in DocumentType:
                if document_type.value in note and document_type.value not in missing_values and document_type.value in present_values:
                    should_skip = True
                    break
            if not should_skip:
                if document_label:
                    notes.append(f"{document_label} 文件需人工確認：已有低信心候選文件，請確認文件類型與內容。")
                else:
                    notes.append(_humanize_internal_text(note))
        return notes

    def _manual_review_document_label(self, note: str) -> str:
        for document_type in DocumentType:
            if document_type.value in note or document_type.name in note:
                return self.classifier.label(document_type)
        return ""

    def _present_document_values(self, case: CaseWorkflow) -> set[str]:
        values: set[str] = set()
        for segment in case.documents:
            document_type = self.classifier.effective_type(segment)
            if document_type != DocumentType.UNKNOWN:
                values.add(document_type.value)
        return values

    def _document_type_from_value(self, value: DocumentType | str) -> DocumentType | None:
        if isinstance(value, DocumentType):
            return value
        for document_type in DocumentType:
            if value in {document_type.name, document_type.value}:
                return document_type
        return None

    def _has_arrival_notice_shipping_evidence(self, case: CaseWorkflow) -> bool:
        for segment in case.documents:
            if self.classifier.effective_type(segment) != DocumentType.ARRIVAL_NOTICE:
                continue
            fields = {field.canonical for field in (segment.parsed.fields if segment.parsed else [])}
            has_bl = CanonicalField.BL_NO in fields or bool(case.match_keys.get("bl_no"))
            has_schedule = CanonicalField.VESSEL_VOYAGE in fields or CanonicalField.VESSEL in fields or CanonicalField.ETA in fields
            if has_bl and has_schedule:
                return True
        return False

    def _is_vessel_voyage_partial(self, result) -> bool:
        if result.field != CanonicalField.VESSEL_VOYAGE:
            return False
        is_partial, _message = self.vessel_voyage.partial_pending(result.declaration_value, result.document_values)
        return is_partial


class TaiwanCustomsLogicEngine:
    REQUIRED_PRACTICE_FIELDS = {
        CanonicalField.TRADE_PROMOTION_FEE: "推貿費",
        CanonicalField.BUSINESS_TAX: "營業稅",
        CanonicalField.IMPORT_REGULATION: "輸入規定",
        CanonicalField.MP1: "MP1",
        CanonicalField.BSMI: "BSMI",
        CanonicalField.COMMODITY_INSPECTION: "商檢",
    }

    def notes(self, case: CaseWorkflow, customs_summary: list[OrganizerField], cargo_summary: list[OrganizerField]) -> list[str]:
        labels = {item.label for item in customs_summary + cargo_summary}
        notes: list[str] = []
        if "CIF" in labels and "FOB" in labels:
            notes.append("CIF / FOB 已取得，請驗算運費與保費是否合理。")
        elif "CIF" in labels or "FOB" in labels:
            notes.append("僅取得部分交易價格欄位，需確認運費、保費及完稅價格。")
        if "稅則" in labels and "品名" in labels:
            notes.append("稅則與品名已取得，需依公司實務規則覆核稅則合理性。")
        elif "稅則" not in labels:
            notes.append("稅則尚未取得，無法完成最終申報風險判斷。")

        missing_practice = [label for _field, label in self.REQUIRED_PRACTICE_FIELDS.items() if label not in labels]
        if missing_practice:
            notes.append(f"未取得 {'、'.join(missing_practice)} 欄位；若本品項適用相關規定，需人工確認。")
        if any(document_type in case.missing_documents for document_type in {DocumentType.DS2_DECLARATION.value, DocumentType.EXPORT_DECLARATION.value}):
            notes.append("正式報單尚未完整確認，不能作為最終申報結論。")
        return notes


class OCRDocumentPipeline:
    """Organizer-facing boundary; actual OCR/file intake remains in the workflow engine."""

    def describe(self, case: CaseWorkflow) -> list[str]:
        notes: list[str] = []
        for segment in case.documents:
            status = segment.debug.get("ocr_status")
            if status == "manual_review":
                notes.append("OCR 辨識不足，需人工確認原始文件。")
        return notes


class CustomsCaseOrganizer:
    def __init__(self) -> None:
        self.grouping = ShipmentGroupingEngine()
        self.classifier = CustomsDocumentClassifier()
        self.summary_builder = CustomsSummaryBuilder()
        self.audit_summary = AuditSummaryEngine()
        self.risk = RiskAnalysisEngine()
        self.taiwan_logic = TaiwanCustomsLogicEngine()
        self.ocr_pipeline = OCRDocumentPipeline()

    def organize_case(self, case: CaseWorkflow) -> CustomsCaseOrganizerResult:
        shipment_summary = self.summary_builder.build_shipment_summary(case)
        cargo_summary = self.summary_builder.build_cargo_summary(case)
        customs_summary = self.summary_builder.build_customs_summary(case)
        missing = self.risk.missing_documents(case)
        audit = self.audit_summary.build(case)
        risk_notes = _dedupe(
            self.grouping.grouping_notes(case)
            + self.ocr_pipeline.describe(case)
            + self.taiwan_logic.notes(case, customs_summary, cargo_summary)
            + self.risk.risk_notes(case)
        )
        potential_errors = [item for item in self.risk.potential_errors(case) if item not in risk_notes]
        result = CustomsCaseOrganizerResult(
            case_id=case.case_id,
            grouping_confidence=case.grouping_confidence,
            shipment_summary=shipment_summary,
            cargo_summary=cargo_summary,
            customs_summary=customs_summary,
            audit_summary=audit,
            missing_documents=missing,
            potential_errors=potential_errors,
            risk_notes=risk_notes,
            next_actions=self.risk.next_actions(case),
        )
        case.case_organizer = result
        return result

    def organize(self, cases: list[CaseWorkflow]) -> list[CustomsCaseOrganizerResult]:
        return [self.organize_case(case) for case in cases]


def _grouping_label(value: str) -> str:
    return {
        "exact_match": "高信心，同票關鍵單號完全一致",
        "high_confidence": "高信心，同票文件關聯明確",
        "partial_match": "中信心，部分單號一致，建議人工覆核",
        "low_confidence": "低信心，需人工確認分票",
        "pending_review": "待人工確認分票",
    }.get(value, value)


def _field_key_to_label(value: str) -> str:
    for field in CanonicalField:
        if value in {field.name, field.value}:
            return FIELD_LABELS.get(field, field.value)
    return value.replace("_", " ")


def _humanize_internal_text(value: str) -> str:
    text = value
    for document_type, label in DOCUMENT_LABELS.items():
        text = text.replace(document_type.value, label).replace(document_type.name, label)
    for field, label in FIELD_LABELS.items():
        text = text.replace(field.value, label).replace(field.name, label)
    return text.replace("low confidence", "低信心").replace("pending review", "待人工確認")


def _decimal(value: str) -> Decimal | None:
    match = re.search(r"-?[0-9][0-9,]*(?:\.[0-9]+)?|-?[0-9]+(?:\.[0-9]+)?", value)
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _format_number(value: str) -> str:
    number = _decimal(value)
    return _format_decimal(number) if number is not None else value


def _format_decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _humanize_internal_text(value.strip()) if value else ""
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result
