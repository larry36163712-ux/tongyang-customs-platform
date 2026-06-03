from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from v2.audit.normalization import SemanticNormalizationEngine
from v2.audit.taiwan_knowledge import TaiwanCustomsKnowledgeFinding, TaiwanCustomsKnowledgeLayer
from v2.core.models import CanonicalField, CheckStatus, ParsedDocument


@dataclass(frozen=True)
class TaiwanCustomsRuleFinding:
    rule_id: str
    title: str
    status: CheckStatus
    process: str
    explanation: str
    risk: str = ""

    @property
    def formal_status(self) -> str:
        return {
            CheckStatus.MATCH: "一致",
            CheckStatus.MISMATCH: "不一致",
            CheckStatus.MISSING: "缺失",
            CheckStatus.HIGH_RISK: "待人工確認",
        }.get(self.status, "待人工確認")

    def summary_line(self) -> str:
        prefix = {
            CheckStatus.MATCH: "✓",
            CheckStatus.MISMATCH: "✗",
            CheckStatus.MISSING: "✗",
            CheckStatus.HIGH_RISK: "⚠",
        }.get(self.status, "⚠")
        detail = self.risk or self.explanation
        return f"{prefix} {self.title}：{self.formal_status}。{detail}"


class TaiwanCustomsAuditRulesEngine:
    """Taiwan customs practice checks based on parsed document fields.

    This engine is deliberately rule-based. It does not guess values from a
    specific customer template; it only evaluates fields already parsed by the
    existing document pipeline.
    """

    TRADE_PROMOTION_RATE = Decimal("0.0004")
    BUSINESS_TAX_RATE = Decimal("0.05")

    def __init__(self, normalizer: SemanticNormalizationEngine | None = None) -> None:
        self.normalizer = normalizer or SemanticNormalizationEngine()
        self.knowledge = TaiwanCustomsKnowledgeLayer()

    def evaluate(
        self,
        declaration: ParsedDocument | None,
        documents: list[ParsedDocument],
    ) -> list[TaiwanCustomsRuleFinding]:
        ordered = ([declaration] if declaration else []) + [document for document in documents if document]
        findings = [
            self.fob_cif_logic(ordered),
            self.customs_value_logic(ordered),
            self.trade_promotion_fee_logic(ordered),
            self.business_tax_logic(ordered),
            self.duty_amount_logic(ordered),
        ]
        findings.extend(self._from_knowledge(finding) for finding in self.knowledge.evaluate(ordered))
        return findings

    def _from_knowledge(self, finding: TaiwanCustomsKnowledgeFinding) -> TaiwanCustomsRuleFinding:
        process = f"原因：{finding.reason}；影響：{finding.impact}；建議：{finding.next_action}"
        return TaiwanCustomsRuleFinding(
            finding.rule_id,
            finding.title,
            finding.status,
            process,
            finding.impact,
            finding.next_action,
        )

    def fob_cif_logic(self, documents: list[ParsedDocument]) -> TaiwanCustomsRuleFinding:
        fob = self._first_number(CanonicalField.FOB, documents)
        cif = self._first_number(CanonicalField.CIF, documents)
        freight = self._first_number(CanonicalField.FREIGHT, documents)
        insurance = self._first_number(CanonicalField.INSURANCE, documents)
        if cif is None and fob is None:
            return self._missing("FOB / CIF / 運保費", "未取得 FOB 或 CIF，無法驗算完稅價格基礎。")
        if cif is not None and fob is not None and cif < fob:
            return self._mismatch("FOB / CIF / 運保費", f"CIF {cif} 小於 FOB {fob}。", "CIF 通常應包含貨價、運費與保費，需確認申報基礎。")
        if None not in {fob, cif, freight, insurance}:
            expected = fob + freight + insurance  # type: ignore[operator]
            if self._close(expected, cif):  # type: ignore[arg-type]
                return self._match("FOB / CIF / 運保費", f"FOB {fob} + 運費 {freight} + 保費 {insurance} = CIF {cif}。")
            return self._mismatch(
                "FOB / CIF / 運保費",
                f"FOB {fob} + 運費 {freight} + 保費 {insurance} = {expected}，文件 CIF = {cif}。",
                "CIF 與運保費組成不一致，需回查發票、報單或到貨費用資料。",
            )
        if cif is not None and fob is not None:
            return self._pending("FOB / CIF / 運保費", "已取得 FOB 與 CIF，但缺少運費或保費明細，需人工確認差額是否合理。")
        return self._pending("FOB / CIF / 運保費", "僅取得部分金額欄位，需人工確認 Incoterm 與完稅價格基礎。")

    def customs_value_logic(self, documents: list[ParsedDocument]) -> TaiwanCustomsRuleFinding:
        customs_value = self._first_number(CanonicalField.CUSTOMS_VALUE, documents)
        cif = self._first_number(CanonicalField.CIF, documents)
        rate = self._first_number(CanonicalField.EXCHANGE_RATE, documents)
        if customs_value is None:
            return self._missing("完稅價格", "未取得完稅價格欄位。")
        if cif is not None and rate is not None:
            expected = self._round_twd(cif * rate)
            if self._close(expected, customs_value, tolerance=Decimal("3")):
                return self._match("完稅價格", f"CIF {cif} x 匯率 {rate} ≈ 完稅價格 {customs_value}。")
            return self._mismatch(
                "完稅價格",
                f"CIF {cif} x 匯率 {rate} ≈ {expected}，報單完稅價格 = {customs_value}。",
                "完稅價格換算差異需確認匯率、幣別或運保費。",
            )
        return self._pending("完稅價格", "已取得完稅價格，但缺少 CIF 或匯率，無法完成換算驗證。")

    def trade_promotion_fee_logic(self, documents: list[ParsedDocument]) -> TaiwanCustomsRuleFinding:
        fee = self._first_number(CanonicalField.TRADE_PROMOTION_FEE, documents)
        base = self._customs_base(documents)
        if fee is None:
            return self._missing("推貿費", "未取得推貿費欄位。")
        if base is None:
            return self._pending("推貿費", "已取得推貿費，但缺少完稅價格或 CIF/匯率基礎，需人工確認。")
        expected = self._round_twd(base * self.TRADE_PROMOTION_RATE)
        if self._close(expected, fee, tolerance=Decimal("2")):
            return self._match("推貿費", f"完稅價格 {base} x 0.04% ≈ 推貿費 {fee}。")
        return self._mismatch("推貿費", f"完稅價格 {base} x 0.04% ≈ {expected}，文件推貿費 = {fee}。", "推貿費疑似與完稅價格不一致。")

    def business_tax_logic(self, documents: list[ParsedDocument]) -> TaiwanCustomsRuleFinding:
        business_tax = self._first_number(CanonicalField.BUSINESS_TAX, documents)
        base = self._customs_base(documents)
        duty = self._first_number(CanonicalField.DUTY_AMOUNT, documents) or Decimal("0")
        trade_fee = self._first_number(CanonicalField.TRADE_PROMOTION_FEE, documents) or Decimal("0")
        if business_tax is None:
            return self._missing("營業稅", "未取得營業稅欄位。")
        if base is None:
            return self._pending("營業稅", "已取得營業稅，但缺少完稅價格，需人工確認計稅基礎。")
        taxable_base = base + duty + trade_fee
        expected = self._round_twd(taxable_base * self.BUSINESS_TAX_RATE)
        if self._close(expected, business_tax, tolerance=Decimal("3")):
            return self._match("營業稅", f"({base} + 稅額 {duty} + 推貿費 {trade_fee}) x 5% ≈ {business_tax}。")
        return self._mismatch(
            "營業稅",
            f"({base} + 稅額 {duty} + 推貿費 {trade_fee}) x 5% ≈ {expected}，文件營業稅 = {business_tax}。",
            "營業稅與完稅價格、稅額或推貿費不一致。",
        )

    def duty_amount_logic(self, documents: list[ParsedDocument]) -> TaiwanCustomsRuleFinding:
        duty = self._first_number(CanonicalField.DUTY_AMOUNT, documents)
        base = self._customs_base(documents)
        if duty is None:
            return self._missing("稅額", "未取得稅額欄位。")
        if base is None:
            return self._pending("稅額", "已取得稅額，但缺少完稅價格，無法回推稅率合理性。")
        if duty < 0:
            return self._mismatch("稅額", f"稅額為負數：{duty}。", "稅額不可為負，需確認解析或報單資料。")
        inferred_rate = (duty / base * Decimal("100")) if base else Decimal("0")
        return self._match("稅額", f"完稅價格 {base}、稅額 {duty}，回推稅率約 {inferred_rate:.4f}%。已取得稅額，法定稅率仍依稅則表覆核。")

    def mp1_logic(self, documents: list[ParsedDocument]) -> TaiwanCustomsRuleFinding:
        return self._presence_rule("MP1", CanonicalField.MP1, documents, "未取得 MP1 欄位；若稅則涉及 MP1 應補確認。")

    def bsmi_logic(self, documents: list[ParsedDocument]) -> TaiwanCustomsRuleFinding:
        return self._presence_rule("BSMI", CanonicalField.BSMI, documents, "未取得 BSMI 欄位；商品若涉及標檢局規定需人工確認。")

    def commodity_inspection_logic(self, documents: list[ParsedDocument]) -> TaiwanCustomsRuleFinding:
        return self._presence_rule("商檢", CanonicalField.COMMODITY_INSPECTION, documents, "未取得商檢欄位；需依品名、稅則與輸入規定確認是否應辦商檢。")

    def import_regulation_logic(self, documents: list[ParsedDocument]) -> TaiwanCustomsRuleFinding:
        return self._presence_rule("輸入規定", CanonicalField.IMPORT_REGULATION, documents, "未取得輸入規定欄位；需確認稅則是否帶有輸入規定代號。")

    def _presence_rule(self, title: str, field: CanonicalField, documents: list[ParsedDocument], missing_message: str) -> TaiwanCustomsRuleFinding:
        value = self._first_text(field, documents)
        if value:
            return self._match(title, f"已取得欄位值：{value}。")
        hs_code = self._first_text(CanonicalField.HS_CODE, documents)
        if hs_code:
            return self._pending(title, missing_message)
        return self._missing(title, missing_message)

    def _customs_base(self, documents: list[ParsedDocument]) -> Decimal | None:
        customs_value = self._first_number(CanonicalField.CUSTOMS_VALUE, documents)
        if customs_value is not None:
            return customs_value
        cif = self._first_number(CanonicalField.CIF, documents)
        rate = self._first_number(CanonicalField.EXCHANGE_RATE, documents)
        if cif is not None and rate is not None:
            return self._round_twd(cif * rate)
        return None

    def _first_number(self, field: CanonicalField, documents: list[ParsedDocument]) -> Decimal | None:
        for value in self._values(field, documents):
            normalized = self.normalizer.normalize(field, value)
            if normalized.numeric is not None:
                return normalized.numeric
            number = self._number(value)
            if number is not None:
                return number
        return None

    def _first_text(self, field: CanonicalField, documents: list[ParsedDocument]) -> str:
        return next(iter(self._values(field, documents)), "")

    def _values(self, field: CanonicalField, documents: list[ParsedDocument]) -> list[str]:
        values: list[str] = []
        for document in documents:
            for parsed in document.fields:
                if parsed.canonical == field and parsed.value:
                    values.append(parsed.value)
        return values

    def _number(self, value: str) -> Decimal | None:
        match = re.search(r"-?[0-9][0-9,]*(?:\.[0-9]+)?|-?[0-9]+(?:\.[0-9]+)?", value)
        if not match:
            return None
        try:
            return Decimal(match.group(0).replace(",", ""))
        except (InvalidOperation, ValueError):
            return None

    def _round_twd(self, value: Decimal) -> Decimal:
        return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    def _close(self, expected: Decimal, actual: Decimal, tolerance: Decimal | None = None) -> bool:
        if tolerance is None:
            tolerance = max(Decimal("1"), abs(expected) * Decimal("0.005"))
        return abs(expected - actual) <= tolerance

    def _match(self, title: str, process: str) -> TaiwanCustomsRuleFinding:
        return TaiwanCustomsRuleFinding(title.lower().replace(" ", "_"), title, CheckStatus.MATCH, process, "資料一致。")

    def _mismatch(self, title: str, process: str, risk: str) -> TaiwanCustomsRuleFinding:
        return TaiwanCustomsRuleFinding(title.lower().replace(" ", "_"), title, CheckStatus.MISMATCH, process, "資料不一致。", risk)

    def _missing(self, title: str, risk: str) -> TaiwanCustomsRuleFinding:
        return TaiwanCustomsRuleFinding(title.lower().replace(" ", "_"), title, CheckStatus.MISSING, "欄位缺失，無法驗算。", "缺少必要資料。", risk)

    def _pending(self, title: str, process: str) -> TaiwanCustomsRuleFinding:
        return TaiwanCustomsRuleFinding(title.lower().replace(" ", "_"), title, CheckStatus.HIGH_RISK, process, "需由報關人員人工確認。", process)
