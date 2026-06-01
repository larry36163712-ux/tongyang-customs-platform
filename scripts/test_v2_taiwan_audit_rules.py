from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from v2.audit.taiwan_rules import TaiwanCustomsAuditRulesEngine
from v2.audit.taiwan_knowledge import TaiwanCustomsKnowledgeLayer
from v2.audit.validation import AuditValidationEngine
from v2.core.models import CanonicalField, CheckStatus, DocumentType, ParsedDocument, ParsedField


def _field(field: CanonicalField, value: str) -> ParsedField:
    return ParsedField(field, field.value, value, 0.95)


def _document(fields: list[ParsedField]) -> ParsedDocument:
    return ParsedDocument(
        DocumentType.DS2_DECLARATION,
        customer="",
        supplier="",
        template_id="test",
        source_name="ds2.txt",
        fields=fields,
    )


def test_taiwan_customs_rules_match_and_manual_review() -> None:
    declaration = _document(
        [
            _field(CanonicalField.FOB, "1000"),
            _field(CanonicalField.FREIGHT, "100"),
            _field(CanonicalField.INSURANCE, "10"),
            _field(CanonicalField.CIF, "1110"),
            _field(CanonicalField.EXCHANGE_RATE, "30"),
            _field(CanonicalField.CUSTOMS_VALUE, "33300"),
            _field(CanonicalField.TRADE_PROMOTION_FEE, "13"),
            _field(CanonicalField.DUTY_RATE, "3%"),
            _field(CanonicalField.DUTY_AMOUNT, "1000"),
            _field(CanonicalField.BUSINESS_TAX, "1716"),
            _field(CanonicalField.HS_CODE, "94036090"),
        ]
    )

    findings = TaiwanCustomsAuditRulesEngine().evaluate(declaration, [])
    by_title = {finding.title: finding for finding in findings}

    assert by_title["FOB / CIF / 運保費"].status == CheckStatus.MATCH
    assert by_title["完稅價格"].status == CheckStatus.MATCH
    assert by_title["推貿費"].status == CheckStatus.MATCH
    assert by_title["營業稅"].status == CheckStatus.MATCH
    assert by_title["稅則"].status == CheckStatus.MATCH
    assert by_title["稅率"].status == CheckStatus.MATCH
    assert by_title["MP1"].formal_status == "待人工確認"
    assert by_title["BSMI"].formal_status == "待人工確認"


def test_taiwan_customs_rules_integrate_with_validation_engine() -> None:
    declaration = _document(
        [
            _field(CanonicalField.CIF, "900"),
            _field(CanonicalField.FOB, "1000"),
            _field(CanonicalField.HS_CODE, "94036090"),
        ]
    )

    findings = AuditValidationEngine().validate(declaration, [], [])
    by_title = {finding.title: finding for finding in findings}

    assert by_title["FOB / CIF / 運保費"].status == CheckStatus.MISMATCH
    assert by_title["推貿費"].status == CheckStatus.MISSING
    assert by_title["MP1"].status == CheckStatus.HIGH_RISK


def test_taiwan_knowledge_layer_explains_reason_impact_and_next_action() -> None:
    declaration = _document(
        [
            _field(CanonicalField.HS_CODE, "94036090"),
            _field(CanonicalField.IMPORT_REGULATION, "MP1"),
        ]
    )

    findings = TaiwanCustomsKnowledgeLayer().evaluate([declaration])
    by_title = {finding.title: finding for finding in findings}

    assert by_title["MP1"].status == CheckStatus.HIGH_RISK
    assert "輸入規定" in by_title["MP1"].reason
    assert "風險" in by_title["MP1"].impact
    assert "確認 MP1" in by_title["MP1"].next_action
    assert by_title["BSMI"].status == CheckStatus.HIGH_RISK
    assert by_title["商檢"].status == CheckStatus.HIGH_RISK


if __name__ == "__main__":
    test_taiwan_customs_rules_match_and_manual_review()
    test_taiwan_customs_rules_integrate_with_validation_engine()
    test_taiwan_knowledge_layer_explains_reason_impact_and_next_action()
    print("taiwan_audit_rules=ok")
