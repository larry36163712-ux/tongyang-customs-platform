from __future__ import annotations

import re

from v2.core.models import CanonicalField, DocumentType, ParsedDocument, ParsedField, SemanticAlias
from v2.core.document_understanding import SemanticDocumentClassifier


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
        SemanticAlias(CanonicalField.VESSEL, ("vessel", "vessel name", "船名")),
        SemanticAlias(CanonicalField.VOYAGE, ("voyage", "voy", "航次")),
        SemanticAlias(CanonicalField.BOOKING_NO, ("booking no", "booking number", "booking#", "定倉號碼", "訂艙號碼")),
        SemanticAlias(CanonicalField.SHIPPING_ORDER_NO, ("s/o no", "so no", "shipping order no", "s/o", "裝貨單號")),
        SemanticAlias(CanonicalField.DECLARATION_NO, ("declaration no", "entry no", "報單號碼", "報單號別")),
        SemanticAlias(CanonicalField.INVOICE_NO, ("invoice no", "invoice number", "inv no", "發票號碼", "發票編號")),
        SemanticAlias(CanonicalField.BL_NO, ("b/l no", "bl no", "bill of lading no", "提單號碼")),
        SemanticAlias(CanonicalField.POL, ("pol", "port of loading", "loading port", "起運港", "裝貨港")),
        SemanticAlias(CanonicalField.POD, ("pod", "port of discharge", "discharge port", "目的港", "卸貨港")),
        SemanticAlias(CanonicalField.ETD, ("etd", "estimated time of departure", "開航日")),
        SemanticAlias(CanonicalField.ETA, ("eta", "estimated time of arrival", "到港日")),
        SemanticAlias(CanonicalField.CBM, ("cbm", "measurement", "m3", "材積")),
        SemanticAlias(CanonicalField.CARRIER, ("carrier", "shipping line", "船公司")),
        SemanticAlias(CanonicalField.FORWARDER, ("forwarder", "forwarding agent", "承攬", "貨代")),
        SemanticAlias(CanonicalField.NOTIFY, ("notify", "notify party", "通知人")),
        SemanticAlias(CanonicalField.ORIGIN, ("origin", "country of origin", "產地")),
        SemanticAlias(CanonicalField.CUSTOMER, ("customer", "buyer", "客戶", "買方")),
        SemanticAlias(CanonicalField.SUPPLIER, ("supplier", "vendor", "shipper", "供應商", "賣方")),
        SemanticAlias(CanonicalField.INCOTERM, ("incoterm", "trade term", "貿易條件", "交易條件")),
        SemanticAlias(CanonicalField.CIF, ("cif", "cif value", "cif amount", "完稅價格")),
        SemanticAlias(CanonicalField.FOB, ("fob", "fob value", "fob amount", "離岸價格")),
        SemanticAlias(CanonicalField.FREIGHT, ("freight", "ocean freight", "運費")),
        SemanticAlias(CanonicalField.INSURANCE, ("insurance", "ins", "保費", "保險費")),
        SemanticAlias(CanonicalField.EXCHANGE_RATE, ("exchange rate", "ex rate", "rate", "匯率")),
        SemanticAlias(CanonicalField.STATISTICAL_METHOD, ("statistical method", "stat method", "統計方式", "統計單位")),
        SemanticAlias(CanonicalField.DUTY_AMOUNT, ("duty", "tax", "duty amount", "稅額", "進口稅")),
        SemanticAlias(CanonicalField.CUSTOMS_VALUE, ("customs value", "dutiable value", "完稅價格", "完稅價值", "海關完稅價格")),
        SemanticAlias(CanonicalField.TRADE_PROMOTION_FEE, ("trade promotion fee", "推貿費", "推廣貿易服務費")),
        SemanticAlias(CanonicalField.BUSINESS_TAX, ("business tax", "vat", "營業稅", "加值稅")),
        SemanticAlias(CanonicalField.IMPORT_REGULATION, ("import regulation", "import requirements", "輸入規定", "輸入規定代號")),
        SemanticAlias(CanonicalField.MP1, ("mp1", "mp 1", "mp-1", "mp1 規定")),
        SemanticAlias(CanonicalField.BSMI, ("bsmi", "商品檢驗", "標準檢驗局", "商檢局")),
        SemanticAlias(CanonicalField.COMMODITY_INSPECTION, ("commodity inspection", "inspection", "商檢", "檢驗方式", "商品檢驗")),
        SemanticAlias(CanonicalField.CLOSING_DATE, ("closing date", "cut off", "cutoff", "結關日")),
    )

    DOCUMENT_TERMS: tuple[tuple[DocumentType, tuple[str, ...]], ...] = (
        (DocumentType.EXPORT_DECLARATION, ("export declaration", "出口報單")),
        (DocumentType.DS2_DECLARATION, ("ds2", "進口報單", "海關報單")),
        (DocumentType.BILL_OF_LADING, ("bill of lading", "b/l", "bl no")),
        (DocumentType.PACKING_LIST, ("packing list", "pkg", "p/l")),
        (DocumentType.INVOICE, ("commercial invoice", "invoice")),
        (DocumentType.ARRIVAL_NOTICE, ("arrival notice", "到貨通知")),
        (DocumentType.DELIVERY_ORDER, ("delivery order", "d/o", "提貨單", "小提單")),
        (DocumentType.MANIFEST, ("cargo manifest", "manifest no", "艙單號碼", "艙單", "倉單")),
        (DocumentType.CLEARANCE_LIST, ("清表",)),
        (DocumentType.DATA_CLEARANCE, ("資料清表",)),
        (DocumentType.MATERIAL_CLEARANCE, ("用料清表",)),
        (DocumentType.DRAWBACK_CLEARANCE, ("核退清表",)),
        (DocumentType.TAX_SHEET, ("稅單", "duty memo", "tax sheet")),
        (DocumentType.IMAGE_SCAN, ("jpg 掃描件", "image scan")),
        (DocumentType.BOOKING_CONFIRMATION, ("booking confirmation",)),
        (DocumentType.SHIPPING_ORDER, ("shipping order", "s/o", "s.o.")),
        (DocumentType.BOOKING, ("booking", "booking no", "booking number", "定倉單", "訂艙單")),
        (DocumentType.PACKING_DETAIL, ("packing detail", "container loading list", "裝箱明細")),
    )

    def classify_document(self, text: str, source_name: str = "") -> DocumentType:
        semantic = SemanticDocumentClassifier().best(text, source_name)
        if self._accept_ds2_candidate(text, semantic):
            return DocumentType.DS2_DECLARATION
        if semantic.document_type != DocumentType.UNKNOWN and semantic.confidence >= 0.42:
            return semantic.document_type
        normalized = text.casefold()
        header = "\n".join(line.strip() for line in text.splitlines()[:8]).casefold()
        first_line = next((line.strip().casefold() for line in text.splitlines() if line.strip()), "")
        scores: list[tuple[float, DocumentType]] = []
        for document_type, terms in self.DOCUMENT_TERMS:
            score = 0.0
            for term in terms:
                needle = term.casefold()
                if needle and needle in first_line:
                    score += 1.0
                if needle and needle in header:
                    score += 0.45
                if needle and needle in normalized:
                    score += 0.15
            if score:
                scores.append((score, document_type))
        if not scores:
            return DocumentType.UNKNOWN
        return max(scores, key=lambda item: item[0])[1]

    def _accept_ds2_candidate(self, text: str, semantic) -> bool:
        if semantic.document_type != DocumentType.DS2_DECLARATION or semantic.confidence < 0.30:
            return False
        normalized = text.casefold()
        customs_terms = (
            "外貨進口",
            "進口",
            "離岸價格",
            "完稅價格",
            "統計方式",
            "稅率",
            "稅額",
            "推貿費",
            "營業稅",
            "fob",
            "cif",
        )
        hits = sum(1 for term in customs_terms if term.casefold() in normalized)
        has_tariff = bool(re.search(r"\b\d{4}\.\d{2}(?:\.\d{2})?(?:\.\d{2})?\b", normalized))
        return hits >= 3 or (hits >= 2 and has_tariff)

    def map_label(self, label: str) -> CanonicalField | None:
        normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", label).strip().casefold()
        for alias in self.FIELD_ALIASES:
            if any(term.casefold() == normalized or term.casefold() in normalized for term in alias.aliases):
                return alias.canonical
        return None

    def parse_document(self, text: str, customer: str = "", supplier: str = "", source_name: str = "") -> ParsedDocument:
        document_type = self.classify_document(text, source_name)
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
            return self._detect_inline_field(raw) or self._detect_identifier_field(raw)

        canonical = self.map_label(label)
        if not canonical:
            return self._detect_identifier_field(raw)
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

    def _detect_identifier_field(self, line: str) -> ParsedField | None:
        patterns = (
            (CanonicalField.INVOICE_NO, r"\b(?:invoice|inv)\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
            (CanonicalField.DECLARATION_NO, r"\b(?:declaration|entry)\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
            (CanonicalField.BL_NO, r"\b(?:b/l|bl|bill of lading)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
            (CanonicalField.BOOKING_NO, r"\b(?:booking|bkg)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
            (CanonicalField.SHIPPING_ORDER_NO, r"\b(?:s/o|so|shipping order)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
            (CanonicalField.CONTAINER_NO, r"\b([A-Z]{4}\s*\d{7})\b"),
            (CanonicalField.INCOTERM, r"\b(FOB|CIF|CFR|CNF|EXW|DAP|DDP)\b"),
            (CanonicalField.EXCHANGE_RATE, r"(?:exchange\s*rate|ex\s*rate|匯率)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)"),
            (CanonicalField.HS_CODE, r"\b(?:hs\s*code|hscode|tariff|稅則(?:號別)?)\s*[:：]?\s*([0-9.\-]{6,14})"),
            (CanonicalField.SEAL_NO, r"\b(?:seal)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)"),
        )
        for field, pattern in patterns:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                return ParsedField(field, field.value, match.group(1).strip(), 0.72, line)
        return None
