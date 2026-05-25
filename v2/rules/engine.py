from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from v2.core.models import CanonicalField, CheckStatus, DocumentType, ParsedDocument
from v2.workflow.models import CaseWorkflow, DocumentSegment


RULE_FILES = (
    "global_rules.json",
    "company_rules.json",
    "customer_rules.json",
    "route_rules.json",
    "case_rules.json",
    "document_rules.json",
)


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    scope: str
    enabled: bool
    applies_when: dict[str, Any]
    priority: int
    description: str
    calculation: dict[str, Any]
    warning_level: str
    source: str


@dataclass(frozen=True)
class RuleFinding:
    rule_id: str
    scope: str
    warning_level: str
    message: str
    source: str
    matched_context: dict[str, Any]

    def human_text(self) -> str:
        return f"{self.warning_level.upper()} {self.rule_id}: {self.message}"


class RuleEngine:
    """Config-driven customs rule engine.

    The audit layer stays generic. Company, customer, route, case, and document
    rules are activated only through config/rules applies_when conditions.
    """

    def __init__(self, rules_path: Path) -> None:
        self.rules_path = rules_path
        self.rules = self._load_rules()
        self.rate_tables = self._load_rate_tables()

    def apply(self, case: CaseWorkflow) -> list[str]:
        findings = self.evaluate(case)
        case.rule_findings = [finding.human_text() for finding in findings]
        return case.rule_findings

    def evaluate(self, case: CaseWorkflow) -> list[RuleFinding]:
        base_context = self._case_context(case)
        findings: list[RuleFinding] = []

        for rule in sorted((rule for rule in self.rules if rule.enabled), key=lambda item: item.priority):
            if rule.scope == "document":
                for segment in case.documents:
                    document = segment.parsed
                    if not document:
                        continue
                    document_context = self._document_context(base_context, document, segment)
                    if self._applies(rule.applies_when, document_context):
                        finding = self._execute(rule, case, document_context, document=document)
                        if finding:
                            findings.append(finding)
                continue

            if self._applies(rule.applies_when, base_context):
                finding = self._execute(rule, case, base_context)
                if finding:
                    findings.append(finding)

        return findings

    def _load_rules(self) -> list[RuleDefinition]:
        files: list[Path]
        if self.rules_path.is_dir():
            files = [self.rules_path / name for name in RULE_FILES]
        elif self.rules_path.exists():
            files = [self.rules_path]
        else:
            return []

        loaded: list[RuleDefinition] = []
        for path in files:
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            rules = data.get("rules", []) if isinstance(data, dict) else []
            for item in rules:
                if not isinstance(item, dict):
                    continue
                rule_id = str(item.get("rule_id") or item.get("code") or "").strip()
                if not rule_id:
                    continue
                loaded.append(
                    RuleDefinition(
                        rule_id=rule_id,
                        scope=str(item.get("scope", "global")).strip().lower(),
                        enabled=bool(item.get("enabled", True)),
                        applies_when=dict(item.get("applies_when") or {}),
                        priority=int(item.get("priority", 100)),
                        description=str(item.get("description", "")).strip(),
                        calculation=dict(item.get("calculation") or {}),
                        warning_level=str(item.get("warning_level") or item.get("severity") or "warning").strip().lower(),
                        source=str(item.get("source", "")).strip(),
                    )
                )
        return loaded

    def _load_rate_tables(self) -> dict[str, dict[str, Any]]:
        if self.rules_path.is_dir():
            path = self.rules_path / "rate_tables.json"
        else:
            path = self.rules_path.parent / "rate_tables.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        tables = data.get("rate_tables", {}) if isinstance(data, dict) else {}
        return {str(key): value for key, value in tables.items() if isinstance(value, dict)}

    def _case_context(self, case: CaseWorkflow) -> dict[str, Any]:
        documents = [segment.parsed for segment in case.documents if segment.parsed]
        fields = self._first_fields(documents)
        context: dict[str, Any] = {
            "scope": "case",
            "case_id": case.case_id,
            "direction": case.direction,
            "case_status": case.status.value,
            "case_tags": case.match_keys.get("case_tags", []),
            "shipment_type": self._infer_shipment_type(case),
            "document_types": [self._document_code(document.document_type) for document in documents],
            "missing_documents": list(case.missing_documents),
            "company": fields.get(CanonicalField.FORWARDER.value) or case.match_keys.get("company", ""),
            "forwarder": fields.get(CanonicalField.FORWARDER.value) or case.match_keys.get("forwarder", ""),
            "customer": fields.get(CanonicalField.CUSTOMER.value) or case.match_keys.get("consignee", ""),
            "supplier": fields.get(CanonicalField.SUPPLIER.value) or case.match_keys.get("shipper", ""),
            "destination_country": self._infer_country(fields, case),
            "container_size": case.match_keys.get("container_size", ""),
            "release_method": case.match_keys.get("release_method", ""),
        }
        context.update({key: value for key, value in fields.items() if key not in context})
        context.update({key: value for key, value in case.match_keys.items() if key not in context})
        return context

    def _document_context(
        self,
        base_context: dict[str, Any],
        document: ParsedDocument,
        segment: DocumentSegment,
    ) -> dict[str, Any]:
        context = dict(base_context)
        context.update(
            {
                "scope": "document",
                "document_type": self._document_code(document.document_type),
                "document_type_label": document.document_type.value,
                "parser": document.raw_metadata.get("parser", ""),
                "parser_confidence": segment.confidence,
                "page_start": segment.page_start,
                "page_end": segment.page_end,
                "source_name": segment.source_name,
                "field_names": [field.canonical.value for field in document.fields],
            }
        )
        return context

    def _execute(
        self,
        rule: RuleDefinition,
        case: CaseWorkflow,
        context: dict[str, Any],
        document: ParsedDocument | None = None,
    ) -> RuleFinding | None:
        calculation_type = str(rule.calculation.get("type", "")).strip()

        if calculation_type == "parser_required_fields" and document:
            required = [str(field) for field in rule.calculation.get("fields", [])]
            present = {field.canonical.value for field in document.fields}
            missing = [field for field in required if field not in present]
            if not missing:
                return None
            return self._finding(rule, f"{rule.description} Missing parser fields: {', '.join(missing)}", context)

        if calculation_type in {"field_compare", "compare_declaration_with_documents"}:
            report = case.audit_report
            if not report:
                return None
            actionable = [
                result
                for result in report.results
                if result.status in {CheckStatus.MISMATCH, CheckStatus.MISSING, CheckStatus.HIGH_RISK}
            ]
            if not actionable and not report.high_risk_warnings:
                return None
            detail = "; ".join(result.message for result in actionable[:5])
            if report.high_risk_warnings:
                detail = "; ".join([detail, *report.high_risk_warnings[:3]]).strip("; ")
            return self._finding(rule, f"{rule.description} {detail}".strip(), context)

        if calculation_type in {"route_review_hint", "template_learning_hint", "case_override"}:
            return self._finding(rule, rule.description, context)

        if calculation_type == "freight_by_cbm":
            calculated = self._calculate_freight_by_cbm(rule, context)
            message = f"{rule.description} {calculated}" if calculated else f"{rule.description} Missing CBM or configured rate table."
            return self._finding(rule, message, context)

        if calculation_type == "fixed_freight_by_container_size":
            table = self.rate_tables.get(str(rule.calculation.get("rate_table_ref", "")), {})
            container_size = str(context.get("container_size", "")).upper()
            value = table.get(container_size)
            if value is not None:
                return self._finding(rule, f"{rule.description} Expected freight: {table.get('currency', '')} {value}", context)
            return self._finding(rule, f"{rule.description} Missing configured fixed freight for container_size={container_size or '-'}", context)

        if calculation_type == "insurance_formula":
            calculated = self._calculate_insurance(rule, context)
            message = f"{rule.description} {calculated}" if calculated else f"{rule.description} Missing amount, insurance_rate, or configured rate table."
            return self._finding(rule, message, context)

        return self._finding(rule, rule.description, context)

    def _finding(self, rule: RuleDefinition, message: str, context: dict[str, Any]) -> RuleFinding:
        matched = {key: context.get(key) for key in rule.applies_when}
        return RuleFinding(rule.rule_id, rule.scope, rule.warning_level, message, rule.source, matched)

    def _applies(self, conditions: dict[str, Any], context: dict[str, Any]) -> bool:
        for key, expected in conditions.items():
            if key not in context:
                return False
            actual = context.get(key)
            if not self._value_matches(actual, expected):
                return False
        return True

    def _value_matches(self, actual: Any, expected: Any) -> bool:
        if isinstance(expected, list):
            return any(self._value_matches(actual, item) for item in expected)
        if isinstance(actual, list):
            return any(self._value_matches(item, expected) for item in actual)
        return self._normalize(actual) == self._normalize(expected)

    def _normalize(self, value: Any) -> str:
        return " ".join(str(value).strip().casefold().split())

    def _first_fields(self, documents: list[ParsedDocument]) -> dict[str, str]:
        values: dict[str, str] = {}
        for document in documents:
            for field in document.fields:
                values.setdefault(field.canonical.value, field.value)
        return values

    def _infer_shipment_type(self, case: CaseWorkflow) -> str:
        text = "\n".join(segment.text for segment in case.documents).casefold()
        if "cfs" in text:
            return "CFS"
        if "fcl" in text or "20ft" in text or "40ft" in text:
            return "FCL"
        return case.match_keys.get("shipment_type", "")

    def _infer_country(self, fields: dict[str, str], case: CaseWorkflow) -> str:
        text = " ".join([fields.get(CanonicalField.POD.value, ""), fields.get(CanonicalField.PORT.value, ""), *case.match_keys.values()])
        normalized = text.casefold()
        if "vietnam" in normalized or "viet nam" in normalized:
            return "Vietnam"
        return case.match_keys.get("destination_country", "")

    def _calculate_freight_by_cbm(self, rule: RuleDefinition, context: dict[str, Any]) -> str:
        table = self.rate_tables.get(str(rule.calculation.get("rate_table_ref", "")), {})
        cbm = self._decimal(context.get("cbm"))
        threshold = self._decimal(table.get("threshold"))
        lte = self._decimal(table.get("lte_threshold"))
        gt = self._decimal(table.get("gt_threshold"))
        if cbm is None or threshold is None or lte is None or gt is None:
            return ""
        freight = lte if cbm <= threshold else gt
        return f"Expected freight: {table.get('currency', '')} {freight.quantize(Decimal('0.01'))} (CBM={cbm})"

    def _calculate_insurance(self, rule: RuleDefinition, context: dict[str, Any]) -> str:
        table = self.rate_tables.get(str(rule.calculation.get("rate_ref", "")), {})
        amount = self._decimal(context.get("amount"))
        rate = self._decimal(context.get("insurance_rate"))
        if amount is None or rate is None:
            return ""
        multiplier = self._decimal(table.get("multiplier")) or Decimal("1")
        minimum = self._decimal(table.get("minimum_premium")) or Decimal("0")
        premium = max(amount * multiplier * rate, minimum).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"Expected insurance: {table.get('currency', '')} {premium} (amount={amount}, rate={rate})"

    def _decimal(self, value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value).replace(",", "").strip())
        except (InvalidOperation, ValueError):
            return None

    def _document_code(self, document_type: DocumentType) -> str:
        return {
            DocumentType.DS2_DECLARATION: "DS2",
            DocumentType.INVOICE: "INV",
            DocumentType.PACKING_LIST: "PKG",
            DocumentType.BILL_OF_LADING: "B/L",
            DocumentType.ARRIVAL_NOTICE: "Arrival Notice",
            DocumentType.CLEARANCE_LIST: "Clearance List",
            DocumentType.BOOKING: "BOOKING",
            DocumentType.SHIPPING_ORDER: "S/O",
            DocumentType.BOOKING_CONFIRMATION: "BOOKING_CONFIRMATION",
            DocumentType.EXPORT_DECLARATION: "EXPORT_DECLARATION",
            DocumentType.PACKING_DETAIL: "PACKING_DETAIL",
        }.get(document_type, document_type.value)
