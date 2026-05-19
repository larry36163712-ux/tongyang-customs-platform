from __future__ import annotations

import re

from v2.core.models import CanonicalField, DocumentType, ParsedDocument, ParsedField, SemanticAlias


class SemanticParserEngine:
    """Rule-light semantic parser boundary for future AI providers.

    This first phase only defines the contract and a small synonym mapper.
    It deliberately avoids customer-specific fixed-column parsing.
    """

    FIELD_ALIASES: tuple[SemanticAlias, ...] = (
        SemanticAlias(CanonicalField.QUANTITY, ("qty", "quantity", "pcs", "數量", "件數")),
        SemanticAlias(CanonicalField.UNIT, ("unit", "uom", "單位")),
        SemanticAlias(CanonicalField.ITEM_NO, ("item", "item no", "part no", "品號", "料號")),
        SemanticAlias(CanonicalField.DESCRIPTION, ("description", "goods", "品名", "貨名")),
        SemanticAlias(CanonicalField.GROSS_WEIGHT, ("gross weight", "gw", "毛重")),
        SemanticAlias(CanonicalField.NET_WEIGHT, ("net weight", "nw", "淨重")),
        SemanticAlias(CanonicalField.AMOUNT, ("amount", "total", "金額")),
        SemanticAlias(CanonicalField.CURRENCY, ("currency", "幣別")),
        SemanticAlias(CanonicalField.ORIGIN, ("origin", "country of origin", "產地")),
        SemanticAlias(CanonicalField.CUSTOMER, ("customer", "buyer", "客戶", "買方")),
        SemanticAlias(CanonicalField.SUPPLIER, ("supplier", "vendor", "shipper", "供應商", "賣方")),
    )

    DOCUMENT_TERMS: tuple[tuple[DocumentType, tuple[str, ...]], ...] = (
        (DocumentType.INVOICE, ("invoice", "commercial invoice", "inv")),
        (DocumentType.PACKING_LIST, ("packing list", "pkg", "p/l")),
        (DocumentType.BILL_OF_LADING, ("bill of lading", "b/l", "bl no")),
        (DocumentType.DATA_CLEARANCE, ("資料清表",)),
        (DocumentType.MATERIAL_CLEARANCE, ("用料清表",)),
        (DocumentType.DRAWBACK_CLEARANCE, ("核退清表",)),
    )

    def classify_document(self, text: str) -> DocumentType:
        normalized = text.casefold()
        for document_type, terms in self.DOCUMENT_TERMS:
            if any(term.casefold() in normalized for term in terms):
                return document_type
        return DocumentType.INVOICE

    def map_label(self, label: str) -> CanonicalField | None:
        normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", label).strip().casefold()
        for alias in self.FIELD_ALIASES:
            if any(term.casefold() == normalized or term.casefold() in normalized for term in alias.aliases):
                return alias.canonical
        return None

    def parse_preview(self, text: str, customer: str = "", supplier: str = "") -> ParsedDocument:
        document_type = self.classify_document(text)
        fields: list[ParsedField] = []
        for line in text.splitlines():
            if ":" not in line:
                continue
            label, value = line.split(":", 1)
            canonical = self.map_label(label)
            if canonical:
                fields.append(
                    ParsedField(
                        canonical=canonical,
                        source_label=label.strip(),
                        value=value.strip(),
                        confidence=0.72,
                        evidence=line.strip(),
                    )
                )

        warnings = []
        if not fields:
            warnings.append("尚未擷取到語意欄位；等待 AI provider 或模板學習資料。")

        return ParsedDocument(
            document_type=document_type,
            customer=customer or "未指定客戶",
            supplier=supplier or "未分類供應商",
            template_id="semantic-draft",
            fields=fields,
            warnings=warnings,
        )

