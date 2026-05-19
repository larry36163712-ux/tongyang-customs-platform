from __future__ import annotations

import re

from v2.core.models import CanonicalField, DocumentType, ParsedDocument, ParsedField, SemanticAlias


class SemanticParserEngine:
    """Rule-light semantic parser boundary for future AI providers.

    This first phase only defines the contract and a small synonym mapper.
    It deliberately avoids customer-specific fixed-column parsing.
    """

    FIELD_ALIASES: tuple[SemanticAlias, ...] = (
        SemanticAlias(CanonicalField.QUANTITY, ("qty", "quantity", "pcs", "數量")),
        SemanticAlias(CanonicalField.PACKAGE_COUNT, ("packages", "package", "carton", "ctn", "件數", "箱數")),
        SemanticAlias(CanonicalField.UNIT, ("unit", "uom", "單位")),
        SemanticAlias(CanonicalField.ITEM_NO, ("item", "item no", "part no", "品號", "料號")),
        SemanticAlias(CanonicalField.DESCRIPTION, ("description", "goods", "commodity", "品名", "貨名")),
        SemanticAlias(CanonicalField.GROSS_WEIGHT, ("gross weight", "g w", "gw", "毛重")),
        SemanticAlias(CanonicalField.NET_WEIGHT, ("net weight", "n w", "nw", "淨重")),
        SemanticAlias(CanonicalField.AMOUNT, ("amount", "total amount", "total", "value", "金額")),
        SemanticAlias(CanonicalField.CURRENCY, ("currency", "幣別")),
        SemanticAlias(CanonicalField.HS_CODE, ("hs code", "hscode", "tariff", "稅則", "稅則號別")),
        SemanticAlias(CanonicalField.PORT, ("port", "discharge port", "loading port", "港口", "卸貨港", "裝貨港")),
        SemanticAlias(CanonicalField.CONTAINER_NO, ("container", "container no", "cntr no", "櫃號", "貨櫃號碼")),
        SemanticAlias(CanonicalField.SEAL_NO, ("seal", "seal no", "封條", "封條號碼")),
        SemanticAlias(CanonicalField.VESSEL_VOYAGE, ("vessel voyage", "vessel/voyage", "vessel", "voyage", "船名航次")),
        SemanticAlias(CanonicalField.ORIGIN, ("origin", "country of origin", "產地")),
        SemanticAlias(CanonicalField.CUSTOMER, ("customer", "buyer", "客戶", "買方")),
        SemanticAlias(CanonicalField.SUPPLIER, ("supplier", "vendor", "shipper", "供應商", "賣方")),
    )

    DOCUMENT_TERMS: tuple[tuple[DocumentType, tuple[str, ...]], ...] = (
        (DocumentType.DS2_DECLARATION, ("ds2", "報單", "進口報單", "海關報單")),
        (DocumentType.INVOICE, ("invoice", "commercial invoice", "inv")),
        (DocumentType.PACKING_LIST, ("packing list", "pkg", "p/l")),
        (DocumentType.BILL_OF_LADING, ("bill of lading", "b/l", "bl no")),
        (DocumentType.ARRIVAL_NOTICE, ("arrival notice", "到貨通知")),
        (DocumentType.CLEARANCE_LIST, ("清表",)),
        (DocumentType.DATA_CLEARANCE, ("資料清表",)),
        (DocumentType.MATERIAL_CLEARANCE, ("用料清表",)),
        (DocumentType.DRAWBACK_CLEARANCE, ("核退清表",)),
    )

    def classify_document(self, text: str) -> DocumentType:
        normalized = text.casefold()
        for document_type, terms in self.DOCUMENT_TERMS:
            if any(term.casefold() in normalized for term in terms):
                return document_type
        return DocumentType.UNKNOWN

    def map_label(self, label: str) -> CanonicalField | None:
        normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", label).strip().casefold()
        for alias in self.FIELD_ALIASES:
            if any(term.casefold() == normalized or term.casefold() in normalized for term in alias.aliases):
                return alias.canonical
        return None

    def parse_document(self, text: str, customer: str = "", supplier: str = "", source_name: str = "") -> ParsedDocument:
        document_type = self.classify_document(text)
        fields: list[ParsedField] = []
        for line in text.splitlines():
            parsed = self._parse_line(line)
            if parsed:
                fields.append(parsed)

        warnings = []
        if not fields:
            warnings.append("尚未擷取到語意欄位；等待 AI provider 或模板學習資料。")

        return ParsedDocument(
            document_type=document_type,
            customer=customer or "未指定客戶",
            supplier=supplier or "未分類供應商",
            template_id="semantic-draft",
            source_name=source_name,
            fields=fields,
            warnings=warnings,
            raw_metadata={"source_name": source_name, "text_length": len(text)},
        )

    def parse_preview(self, text: str, customer: str = "", supplier: str = "") -> ParsedDocument:
        return self.parse_document(text, customer, supplier)

    def _parse_line(self, line: str) -> ParsedField | None:
        raw = line.strip()
        if not raw:
            return None

        label = ""
        value = ""
        for separator in (":", "：", "\t"):
            if separator in raw:
                label, value = raw.split(separator, 1)
                break
        if not label:
            match = re.match(r"^([A-Za-z\u4e00-\u9fff ./_-]{2,35})\s{2,}(.+)$", raw)
            if match:
                label, value = match.group(1), match.group(2)

        if not label:
            return self._detect_inline_field(raw)

        canonical = self.map_label(label)
        if not canonical:
            return None
        return ParsedField(canonical, label.strip(), value.strip(), 0.78, raw)

    def _detect_inline_field(self, line: str) -> ParsedField | None:
        normalized = line.casefold()
        for alias in self.FIELD_ALIASES:
            for term in alias.aliases:
                if term.casefold() not in normalized:
                    continue
                value = re.sub(re.escape(term), "", line, count=1, flags=re.IGNORECASE).strip(" :-：")
                if value:
                    return ParsedField(alias.canonical, term, value, 0.62, line)
        return None
