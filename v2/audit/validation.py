from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from v2.audit.normalization import SemanticNormalizationEngine
from v2.audit.taiwan_rules import TaiwanCustomsAuditRulesEngine
from v2.core.models import CanonicalField, CheckResult, CheckStatus, ParsedDocument


@dataclass(frozen=True)
class ValidationFinding:
    title: str
    status: CheckStatus
    process: str
    explanation: str
    risk: str = ""


class AuditValidationEngine:
    """Formal broker-style validations built from parsed document fields."""

    def __init__(self, normalizer: SemanticNormalizationEngine | None = None) -> None:
        self.normalizer = normalizer or SemanticNormalizationEngine()
        self.taiwan_rules = TaiwanCustomsAuditRulesEngine(self.normalizer)

    def validate(self, declaration: ParsedDocument | None, documents: list[ParsedDocument], results: list[CheckResult]) -> list[ValidationFinding]:
        findings = [
            self.cif_validation(declaration, documents),
            self.unit_price_validation(declaration, documents),
            self.weight_validation(results),
            self.exchange_rate_validation(declaration, documents),
            self.package_validation(results),
            self.hs_code_validation(results),
            self.statistics_validation(declaration, documents),
        ]
        formal_findings = [finding for finding in findings if finding is not None]
        formal_findings.extend(
            ValidationFinding(
                finding.title,
                finding.status,
                finding.process,
                finding.explanation,
                finding.risk,
            )
            for finding in self.taiwan_rules.evaluate(declaration, documents)
        )
        return formal_findings

    def cif_validation(self, declaration: ParsedDocument | None, documents: list[ParsedDocument]) -> ValidationFinding | None:
        fob = self._first_number(CanonicalField.FOB, declaration, documents)
        freight = self._first_number(CanonicalField.FREIGHT, declaration, documents)
        insurance = self._first_number(CanonicalField.INSURANCE, declaration, documents)
        cif = self._first_number(CanonicalField.CIF, declaration, documents)
        if None in {fob, freight, insurance, cif}:
            return ValidationFinding("CIF 驗算", CheckStatus.MISSING, "CIF = FOB + 運費 + 保費；目前缺少其中一項來源。", "缺資料時不能確認完稅價格是否正確。", "CIF 可能需人工回推。")
        total = fob + freight + insurance
        if total == cif:
            return ValidationFinding("CIF 驗算", CheckStatus.MATCH, f"{fob} + {freight} + {insurance} = {total}", "FOB、運費、保費加總等於 CIF。")
        return ValidationFinding("CIF 驗算", CheckStatus.MISMATCH, f"{fob} + {freight} + {insurance} = {total}，文件 CIF = {cif}", "CIF 與組成項目不一致。", f"差額 {cif - total} 需確認。")

    def unit_price_validation(self, declaration: ParsedDocument | None, documents: list[ParsedDocument]) -> ValidationFinding | None:
        amount = self._first_number(CanonicalField.AMOUNT, declaration, documents)
        quantity = self._first_number(CanonicalField.QUANTITY, declaration, documents)
        if amount is None or quantity in {None, Decimal("0")}:
            return ValidationFinding("單價驗算", CheckStatus.MISSING, "單價 = 金額 / 數量；目前缺少金額或數量。", "單價無法由 parser 結果回推。", "需人工確認 INV 單價。")
        unit_price = amount / quantity
        return ValidationFinding("單價驗算", CheckStatus.MATCH, f"{amount} / {quantity} = {unit_price:.6f}", "可由總金額與數量回推出單價，供人工與 INV 單價欄交叉確認。")

    def weight_validation(self, results: list[CheckResult]) -> ValidationFinding | None:
        weight_results = [result for result in results if result.field in {CanonicalField.NET_WEIGHT, CanonicalField.GROSS_WEIGHT}]
        mismatches = [result.message for result in weight_results if result.status == CheckStatus.MISMATCH]
        if mismatches:
            return ValidationFinding("重量換算", CheckStatus.MISMATCH, "；".join(mismatches), "重量經 KG/MTS 正規化後仍不一致。", "毛重/淨重錯填會影響申報與統計。")
        matches = [result for result in weight_results if result.status == CheckStatus.MATCH]
        if matches:
            return ValidationFinding("重量換算", CheckStatus.MATCH, "已將 MTS 轉 KGS、KG/KGS 視為同單位後比對。", "重量單位換算後一致。")
        return ValidationFinding("重量換算", CheckStatus.MISSING, "缺少可換算的毛重或淨重。", "重量尚不能完成正式核對。", "需補 PL 或 B/L 重量。")

    def exchange_rate_validation(self, declaration: ParsedDocument | None, documents: list[ParsedDocument]) -> ValidationFinding | None:
        rate = self._first_number(CanonicalField.EXCHANGE_RATE, declaration, documents)
        amount = self._first_number(CanonicalField.CIF, declaration, documents) or self._first_number(CanonicalField.AMOUNT, declaration, documents)
        if rate is None or amount is None:
            return ValidationFinding("匯率換算", CheckStatus.MISSING, "台幣基礎 = 外幣金額 x 匯率；目前缺少匯率或金額。", "無法驗算台幣完稅價格。", "需確認報單匯率。")
        return ValidationFinding("匯率換算", CheckStatus.MATCH, f"{amount} x {rate} = {amount * rate}", "可依報單匯率回推台幣基礎，請與正式報單台幣欄確認。")

    def package_validation(self, results: list[CheckResult]) -> ValidationFinding | None:
        package = next((result for result in results if result.field == CanonicalField.PACKAGE_COUNT), None)
        if not package:
            return None
        if package.status == CheckStatus.MATCH:
            return ValidationFinding("件數合理性", CheckStatus.MATCH, "已將 BLE/BALE/BALES、CTN/CTNS 等報關同義單位正規化。", "件數語意一致。")
        return ValidationFinding("件數合理性", package.status, package.message, "件數需以實際包裝單位核對，不可把櫃數當件數。", package.message)

    def hs_code_validation(self, results: list[CheckResult]) -> ValidationFinding | None:
        hs = next((result for result in results if result.field == CanonicalField.HS_CODE), None)
        if not hs:
            return None
        if hs.status == CheckStatus.MATCH:
            return ValidationFinding("稅則合理性", CheckStatus.MATCH, "稅則已去除標點並以數字比對。", "稅則號別與佐證文件一致；仍需依品名材質用途做法規確認。")
        return ValidationFinding("稅則合理性", hs.status, hs.message, "稅則與品名、統計方式、輸入規定連動，差異需人工確認。", hs.message)

    def statistics_validation(self, declaration: ParsedDocument | None, documents: list[ParsedDocument]) -> ValidationFinding | None:
        method = self._first_text(CanonicalField.STATISTICAL_METHOD, declaration, documents)
        hs = self._first_text(CanonicalField.HS_CODE, declaration, documents)
        quantity = self._first_text(CanonicalField.QUANTITY, declaration, documents)
        if not method:
            return ValidationFinding("統計方式合理性", CheckStatus.MISSING, "缺少統計方式欄位。", "統計方式需依稅則與申報單位判斷。", "需確認報單統計方式。")
        return ValidationFinding("統計方式合理性", CheckStatus.MATCH, f"統計方式={method}；稅則={hs or '-'}；數量={quantity or '-'}", "統計方式已有來源，可與稅則法定統計單位交叉確認。")

    def _first_number(self, field: CanonicalField, declaration: ParsedDocument | None, documents: list[ParsedDocument]) -> Decimal | None:
        for value in self._values(field, declaration, documents):
            normalized = self.normalizer.normalize(field, value)
            if normalized.numeric is not None:
                return normalized.numeric
        return None

    def _first_text(self, field: CanonicalField, declaration: ParsedDocument | None, documents: list[ParsedDocument]) -> str:
        return next(iter(self._values(field, declaration, documents)), "")

    def _values(self, field: CanonicalField, declaration: ParsedDocument | None, documents: list[ParsedDocument]) -> list[str]:
        ordered = ([declaration] if declaration else []) + documents
        values: list[str] = []
        for document in ordered:
            if not document:
                continue
            for parsed in document.fields:
                if parsed.canonical == field and parsed.value:
                    values.append(parsed.value)
        return values
