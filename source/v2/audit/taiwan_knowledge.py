from __future__ import annotations

from dataclasses import dataclass
import re

from v2.core.models import CanonicalField, CheckStatus, ParsedDocument


@dataclass(frozen=True)
class TaiwanCustomsKnowledgeObject:
    """Parsed Taiwan customs knowledge extracted from the current case."""

    hs_code: str = ""
    duty_rate: str = ""
    import_regulation: str = ""
    mp1: str = ""
    bsmi: str = ""
    commodity_inspection: str = ""

    @property
    def has_tariff_context(self) -> bool:
        return bool(self.hs_code or self.duty_rate or self.import_regulation)

    @property
    def import_regulation_tokens(self) -> set[str]:
        text = self.import_regulation.upper()
        return {token for token in re.split(r"[^A-Z0-9]+", text) if token}


@dataclass(frozen=True)
class TaiwanCustomsKnowledgeFinding:
    rule_id: str
    title: str
    status: CheckStatus
    reason: str
    impact: str
    next_action: str
    evidence: str = ""

    @property
    def formal_status(self) -> str:
        return {
            CheckStatus.MATCH: "一致",
            CheckStatus.MISMATCH: "不一致",
            CheckStatus.MISSING: "缺失",
            CheckStatus.HIGH_RISK: "待人工確認",
        }.get(self.status, "待人工確認")

    def broker_note(self) -> str:
        evidence = f"；依據：{self.evidence}" if self.evidence else ""
        return f"{self.title}：{self.formal_status}。原因：{self.reason}。影響：{self.impact}。建議：{self.next_action}{evidence}"


class TaiwanCustomsKnowledgeLayer:
    """Small, local Taiwan customs knowledge layer.

    Phase 7B intentionally avoids external customs APIs. The object is built
    only from parsed case fields, so it remains deterministic and safe for RC
    use while leaving a clear extension point for future tariff tables.
    """

    def build(self, documents: list[ParsedDocument]) -> TaiwanCustomsKnowledgeObject:
        return TaiwanCustomsKnowledgeObject(
            hs_code=self._first_text(CanonicalField.HS_CODE, documents),
            duty_rate=self._first_text(CanonicalField.DUTY_RATE, documents),
            import_regulation=self._first_text(CanonicalField.IMPORT_REGULATION, documents),
            mp1=self._first_text(CanonicalField.MP1, documents),
            bsmi=self._first_text(CanonicalField.BSMI, documents),
            commodity_inspection=self._first_text(CanonicalField.COMMODITY_INSPECTION, documents),
        )

    def evaluate(self, documents: list[ParsedDocument]) -> list[TaiwanCustomsKnowledgeFinding]:
        knowledge = self.build(documents)
        return [
            self._hs_code_rule(knowledge),
            self._duty_rate_rule(knowledge),
            self._import_regulation_rule(knowledge),
            self._mp1_rule(knowledge),
            self._bsmi_rule(knowledge),
            self._commodity_inspection_rule(knowledge),
        ]

    def _hs_code_rule(self, knowledge: TaiwanCustomsKnowledgeObject) -> TaiwanCustomsKnowledgeFinding:
        if knowledge.hs_code:
            return self._match(
                "稅則",
                f"已取得稅則 {knowledge.hs_code}",
                "可作為稅率、輸入規定、MP1、BSMI 與商檢判斷基礎。",
                "依品名與材質覆核稅則是否適用。",
                knowledge.hs_code,
            )
        return self._missing(
            "稅則",
            "本案尚未取得稅則欄位。",
            "無法判斷適用稅率、輸入規定、MP1、BSMI 與商檢。",
            "請補正式報單或確認發票、型錄、品名材質後補稅則。",
        )

    def _duty_rate_rule(self, knowledge: TaiwanCustomsKnowledgeObject) -> TaiwanCustomsKnowledgeFinding:
        if knowledge.duty_rate:
            return self._match(
                "稅率",
                f"已取得稅率 {knowledge.duty_rate}",
                "可與稅額、完稅價格交叉驗算。",
                "後續可接正式稅則表確認法定稅率。",
                knowledge.duty_rate,
            )
        if knowledge.hs_code:
            return self._pending(
                "稅率",
                "已有稅則但未取得稅率欄位。",
                "目前只能回推稅率，不能確認是否符合法定稅率。",
                "請補報單稅率欄位，或依稅則表人工確認。",
                knowledge.hs_code,
            )
        return self._missing(
            "稅率",
            "缺少稅則與稅率。",
            "無法做稅額合理性確認。",
            "請先確認稅則，再確認適用稅率。",
        )

    def _import_regulation_rule(self, knowledge: TaiwanCustomsKnowledgeObject) -> TaiwanCustomsKnowledgeFinding:
        if knowledge.import_regulation:
            return self._match(
                "輸入規定",
                f"已取得輸入規定 {knowledge.import_regulation}",
                "可判斷是否牽涉 MP1、商檢或其他進口限制。",
                "請依輸入規定代號確認應備文件。",
                knowledge.import_regulation,
            )
        if knowledge.hs_code:
            return self._pending(
                "輸入規定",
                "已有稅則但未取得輸入規定欄位。",
                "可能漏看 MP1、商檢或其他進口條件。",
                "請補報單輸入規定欄位或依稅則表查核。",
                knowledge.hs_code,
            )
        return self._missing(
            "輸入規定",
            "缺少稅則與輸入規定。",
            "無法判斷是否有進口限制或額外文件需求。",
            "請先補齊報單或稅則資料。",
        )

    def _mp1_rule(self, knowledge: TaiwanCustomsKnowledgeObject) -> TaiwanCustomsKnowledgeFinding:
        requires_mp1 = "MP1" in knowledge.import_regulation_tokens or self._positive(knowledge.mp1)
        if requires_mp1 and not self._positive(knowledge.mp1):
            return self._pending(
                "MP1",
                "輸入規定已出現 MP1，但文件未取得 MP1 確認欄位。",
                "可能需要額外確認輸入許可或相關文件，否則申報前風險偏高。",
                "請人工確認 MP1 是否適用，並補齊對應文件或註記。",
                knowledge.import_regulation,
            )
        if self._has_value(knowledge.mp1):
            return self._match(
                "MP1",
                f"已取得 MP1 資訊 {knowledge.mp1}",
                "已具備 MP1 初步佐證。",
                "仍需依實際輸入規定確認文件是否完整。",
                knowledge.mp1,
            )
        if knowledge.has_tariff_context:
            return self._pending(
                "MP1",
                "已有稅則或輸入規定，但 MP1 欄位未明確出現。",
                "若該稅則帶 MP1，可能漏列必要確認。",
                "請依稅則表確認是否需 MP1。",
                knowledge.hs_code or knowledge.import_regulation,
            )
        return self._missing("MP1", "缺少稅則脈絡與 MP1 欄位。", "目前無法判斷 MP1 是否適用。", "請補稅則或報單資料。")

    def _bsmi_rule(self, knowledge: TaiwanCustomsKnowledgeObject) -> TaiwanCustomsKnowledgeFinding:
        if self._has_value(knowledge.bsmi):
            return self._match(
                "BSMI",
                f"已取得 BSMI 資訊 {knowledge.bsmi}",
                "已可初步判斷是否牽涉標檢局規定。",
                "請依品名與稅則確認 BSMI 文件是否完整。",
                knowledge.bsmi,
            )
        return self._pending(
            "BSMI",
            "文件未取得 BSMI 欄位。",
            "若商品屬標檢局管制品，可能缺少應備文件或審查。",
            "請依稅則與品名確認是否適用 BSMI。",
            knowledge.hs_code,
        )

    def _commodity_inspection_rule(self, knowledge: TaiwanCustomsKnowledgeObject) -> TaiwanCustomsKnowledgeFinding:
        if self._has_value(knowledge.commodity_inspection):
            return self._match(
                "商檢",
                f"已取得商檢資訊 {knowledge.commodity_inspection}",
                "已可初步判斷商檢處理方向。",
                "請確認商檢方式與文件是否符合該品項要求。",
                knowledge.commodity_inspection,
            )
        return self._pending(
            "商檢",
            "文件未取得商檢欄位。",
            "若商品需商檢，放行前可能需要補辦或提供證明。",
            "請依稅則、品名、材質與輸入規定確認是否需商檢。",
            knowledge.hs_code,
        )

    def _first_text(self, field: CanonicalField, documents: list[ParsedDocument]) -> str:
        for document in documents:
            for parsed in document.fields:
                if parsed.canonical == field and parsed.value:
                    return parsed.value.strip()
        return ""

    def _has_value(self, value: str) -> bool:
        return bool(value.strip())

    def _positive(self, value: str) -> bool:
        text = value.strip().upper()
        return bool(text and text not in {"N", "NO", "NONE", "無", "免", "-", "N/A"})

    def _match(self, title: str, reason: str, impact: str, next_action: str, evidence: str = "") -> TaiwanCustomsKnowledgeFinding:
        return TaiwanCustomsKnowledgeFinding(title.lower(), title, CheckStatus.MATCH, reason, impact, next_action, evidence)

    def _missing(self, title: str, reason: str, impact: str, next_action: str, evidence: str = "") -> TaiwanCustomsKnowledgeFinding:
        return TaiwanCustomsKnowledgeFinding(title.lower(), title, CheckStatus.MISSING, reason, impact, next_action, evidence)

    def _pending(self, title: str, reason: str, impact: str, next_action: str, evidence: str = "") -> TaiwanCustomsKnowledgeFinding:
        return TaiwanCustomsKnowledgeFinding(title.lower(), title, CheckStatus.HIGH_RISK, reason, impact, next_action, evidence)
