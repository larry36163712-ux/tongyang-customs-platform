from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from v2.core.models import DocumentType


@dataclass
class DocumentCandidate:
    document_type: DocumentType
    confidence: float
    reasons: list[str]
    needs_manual_confirm: bool = False
    score_breakdown: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentSemanticProfile:
    document_type: DocumentType
    layout_terms: tuple[str, ...] = ()
    semantic_fields: tuple[str, ...] = ()
    customs_vocabulary: tuple[str, ...] = ()
    table_patterns: tuple[str, ...] = ()
    shipping_terms: tuple[str, ...] = ()
    trade_fingerprint: tuple[str, ...] = ()
    identifier_patterns: tuple[str, ...] = ()
    minimum_score: float = 0.42


@dataclass(frozen=True)
class OCRStructure:
    normalized: str
    header: str
    lines: tuple[str, ...]
    key_value_ratio: float
    table_ratio: float
    numeric_ratio: float
    money_count: int
    weight_count: int
    container_count: int
    noisy_ratio: float
    tokens: tuple[str, ...]


class SemanticDocumentClassifier:
    """AI-style content understanding for customs trade documents.

    The classifier intentionally ignores filename semantics. It combines layout,
    OCR structure, table fingerprints, shipping vocabulary, customs vocabulary,
    and trade-document field patterns to decide how a document is used.
    """

    CONFIRMED_THRESHOLD = 0.78

    PROFILES: tuple[DocumentSemanticProfile, ...] = (
        DocumentSemanticProfile(
            DocumentType.INVOICE,
            layout_terms=("commercial invoice", "invoice", "發票", "商業發票"),
            semantic_fields=("invoice no", "invoice number", "inv no", "seller", "buyer", "unit price", "amount", "total amount", "currency", "發票號碼", "買方", "賣方", "單價", "金額"),
            customs_vocabulary=("cif", "fob", "cfr", "exw", "incoterm", "payment term", "trade term"),
            table_patterns=("description", "quantity", "unit price", "amount", "total", "品名", "數量", "單價", "總價"),
            trade_fingerprint=("seller", "buyer", "invoice date", "purchase order", "terms", "country of origin"),
            identifier_patterns=(r"\b(?:invoice|inv)\s*(?:no|number|#)\b", r"\b(?:fob|cif|cfr|exw)\b", r"發票號碼"),
        ),
        DocumentSemanticProfile(
            DocumentType.PACKING_LIST,
            layout_terms=("packing list", "packing", "裝箱單", "包裝單"),
            semantic_fields=("package", "packages", "carton", "cartons", "ctn", "ctns", "gross weight", "net weight", "measurement", "件數", "毛重", "淨重", "材積"),
            table_patterns=("n.w.", "g.w.", "nw", "gw", "meas", "cbm", "kgs", "kg", "carton", "ctn"),
            trade_fingerprint=("shipping mark", "marks", "description of goods", "package type"),
            identifier_patterns=(r"\b(?:gross|net)\s*weight\b", r"\b\d+(?:\.\d+)?\s*(?:ctns|cartons|packages|pkgs|bales)\b", r"毛重|淨重|材積"),
        ),
        DocumentSemanticProfile(
            DocumentType.BILL_OF_LADING,
            layout_terms=("bill of lading", "b/l", "bl no", "提單"),
            semantic_fields=("b/l no", "bl no", "bill of lading no", "shipper", "consignee", "notify party", "vessel", "voyage", "no of original b/l", "船名", "航次", "提單號碼"),
            table_patterns=("container", "seal", "packages", "gross weight", "measurement"),
            shipping_terms=("port of loading", "port of discharge", "place of receipt", "place of delivery", "freight", "carrier", "裝貨港", "卸貨港"),
            trade_fingerprint=("original", "no of original b/l", "non-negotiable", "laden on board", "ocean vessel", "shipped on board"),
            identifier_patterns=(r"\b(?:b/l|bl)\s*(?:no|number|#)\b", r"\bno\s+of\s+original\s+b/l\b", r"\bbill\s+of\s+lading\b", r"\b[A-Z]{4}\s*\d{7}\b", r"提單號碼|船名|航次"),
        ),
        DocumentSemanticProfile(
            DocumentType.ARRIVAL_NOTICE,
            layout_terms=("arrival notice", "notice of arrival", "到貨通知"),
            semantic_fields=("notice no", "arrival date", "free time", "delivery order", "d/o no", "pickup location", "eta", "到港日", "免費期", "提貨單"),
            table_patterns=("demurrage", "detention", "free time", "charge", "storage", "delivery order"),
            shipping_terms=("port of discharge", "terminal", "container yard", "carrier", "vessel", "voyage"),
            trade_fingerprint=("arrival notice", "free time", "delivery order", "cargo release", "do release"),
            identifier_patterns=(r"\barrival\s+notice\b", r"\bnotice\s+of\s+arrival\b", r"\bfree\s+time\b", r"\bdelivery\s+order\b", r"\bnotice\s*no\b"),
        ),
        DocumentSemanticProfile(
            DocumentType.SHIPPING_ORDER,
            layout_terms=("shipping order", "s/o", "so no", "裝船通知", "裝貨單"),
            semantic_fields=("shipping order no", "s/o no", "booking no", "vessel", "voyage", "container", "cut off"),
            shipping_terms=("cy cut", "si cut", "carrier", "forwarder", "port of loading", "port of discharge"),
            trade_fingerprint=("booking confirmation", "export closing", "terminal"),
            identifier_patterns=(r"\b(?:s/o|so|shipping order)\s*(?:no|number|#)\b", r"\bbooking\s*(?:no|number|#)\b"),
        ),
        DocumentSemanticProfile(
            DocumentType.BOOKING,
            layout_terms=("booking confirmation", "booking no", "訂艙", "訂艙單"),
            semantic_fields=("booking no", "carrier", "forwarder", "vessel", "voyage", "etd", "eta", "container"),
            shipping_terms=("cy cut", "si cut", "port of loading", "port of discharge", "cut off"),
            trade_fingerprint=("space confirmation", "service contract", "closing time"),
            identifier_patterns=(r"\bbooking\s*(?:no|number|#)\b",),
        ),
        DocumentSemanticProfile(
            DocumentType.DS2_DECLARATION,
            layout_terms=("ds2", "declaration", "import declaration", "進口報單", "海關進口報單", "報單"),
            semantic_fields=("declaration no", "hs code", "duty amount", "exchange rate", "報單號碼", "進口人", "申報單位", "完稅價格", "納稅辦法", "稅則", "統計方式", "稅額", "匯率", "貨物名稱"),
            customs_vocabulary=("customs", "duty", "tariff", "hs code", "import", "declaration", "海關", "完稅", "稅則", "營業稅", "關稅", "統計方式", "進口", "申報"),
            table_patterns=("稅則", "貨物名稱", "完稅價格", "稅額", "淨重", "數量"),
            trade_fingerprint=("cif", "fob", "運費", "保費", "結關", "放行"),
            identifier_patterns=(r"\bds2\b", r"\bimport\s+declaration\b", r"\bhs\s*code\b", r"報單", r"稅則", r"統計方式", r"完稅價格"),
        ),
        DocumentSemanticProfile(
            DocumentType.EXPORT_DECLARATION,
            layout_terms=("出口報單", "海關出口報單", "出口統計"),
            semantic_fields=("報單號碼", "出口人", "申報單位", "統計方式", "稅則", "貨物名稱"),
            customs_vocabulary=("海關", "出口", "報單", "統計方式", "稅則", "申報"),
            table_patterns=("稅則", "貨物名稱", "數量", "離岸價格", "淨重"),
            trade_fingerprint=("結關", "放行", "出口統計"),
            identifier_patterns=(r"出口報單", r"出口統計", r"報單號碼"),
        ),
        DocumentSemanticProfile(
            DocumentType.TAX_SHEET,
            layout_terms=("稅單", "進口稅單", "繳納證"),
            semantic_fields=("稅額", "應納稅額", "營業稅", "關稅", "完稅價格", "繳納期限"),
            customs_vocabulary=("海關", "稅款", "納稅", "稅單", "關稅", "營業稅"),
            table_patterns=("稅別", "稅率", "稅額", "合計"),
            identifier_patterns=(r"稅單", r"應納稅額|稅額", r"營業稅|關稅"),
        ),
        DocumentSemanticProfile(
            DocumentType.DRAWBACK_CLEARANCE,
            layout_terms=("核退", "核退清表", "沖退", "退稅"),
            semantic_fields=("料號", "用料", "出口報單", "進口報單", "數量", "核退標準"),
            customs_vocabulary=("核退", "保稅", "沖退", "退稅", "清表"),
            table_patterns=("料號", "品名", "數量", "單耗", "核退"),
            trade_fingerprint=("核退標準", "保稅工廠", "外銷品"),
            identifier_patterns=(r"核退", r"退稅", r"核退標準"),
        ),
        DocumentSemanticProfile(
            DocumentType.MATERIAL_CLEARANCE,
            layout_terms=("用料清表", "用料", "清表"),
            semantic_fields=("料號", "品名", "規格", "用量", "單耗", "數量"),
            customs_vocabulary=("用料", "清表", "核退", "保稅"),
            table_patterns=("料號", "品名", "規格", "用量", "單耗"),
            trade_fingerprint=("原料", "成品", "用料明細"),
            identifier_patterns=(r"用料清表", r"用料", r"單耗"),
        ),
        DocumentSemanticProfile(
            DocumentType.CLEARANCE_LIST,
            layout_terms=("清表", "資料清表"),
            semantic_fields=("料號", "品名", "數量", "報單號碼"),
            customs_vocabulary=("清表", "核退", "報單"),
            table_patterns=("料號", "品名", "數量"),
            identifier_patterns=(r"清表", r"料號"),
        ),
    )

    def classify(self, text: str, filename: str = "") -> list[DocumentCandidate]:
        del filename
        structure = self._structure(text)
        candidates: list[DocumentCandidate] = []

        for profile in self.PROFILES:
            breakdown = self._score_profile(profile, structure)
            confidence = round(min(0.98, max(0.0, sum(breakdown.values()))), 2)
            if confidence >= profile.minimum_score:
                reasons = self._evidence(profile, structure)
                candidates.append(
                    DocumentCandidate(
                        profile.document_type,
                        confidence,
                        reasons,
                        confidence < self.CONFIRMED_THRESHOLD,
                        {key: round(value, 2) for key, value in breakdown.items() if value > 0},
                    )
                )

        if not candidates and text.strip():
            candidates.append(
                DocumentCandidate(
                    DocumentType.UNKNOWN,
                    0.28,
                    ["內容可讀但缺少足夠文件用途特徵"],
                    True,
                    {"ocr_structure": 0.28},
                )
            )
        return sorted(candidates, key=lambda candidate: candidate.confidence, reverse=True)

    def best(self, text: str, filename: str = "") -> DocumentCandidate:
        candidates = self.classify(text, filename)
        if candidates:
            return candidates[0]
        return DocumentCandidate(DocumentType.UNKNOWN, 0.0, ["未取得可辨識文字"], True)

    def confidence_label(self, candidate: DocumentCandidate) -> str:
        if candidate.document_type == DocumentType.UNKNOWN:
            return "缺失"
        if candidate.needs_manual_confirm:
            return "AI低信心待確認"
        return "已確認文件"

    def _score_profile(self, profile: DocumentSemanticProfile, structure: OCRStructure) -> dict[str, float]:
        layout_hits = self._semantic_hits(structure.header, profile.layout_terms) or self._semantic_hits(structure.normalized, profile.layout_terms)
        field_hits = self._semantic_hits(structure.normalized, profile.semantic_fields)
        customs_hits = self._semantic_hits(structure.normalized, profile.customs_vocabulary)
        table_hits = self._semantic_hits(structure.normalized, profile.table_patterns)
        shipping_hits = self._semantic_hits(structure.normalized, profile.shipping_terms)
        fingerprint_hits = self._semantic_hits(structure.normalized, profile.trade_fingerprint)
        identifier_hits = self._regex_hits(structure.normalized, profile.identifier_patterns)

        breakdown = {
            "layout_analysis": min(0.22, 0.12 * len(layout_hits)),
            "semantic_fields": min(0.30, 0.055 * len(field_hits)),
            "customs_vocabulary": min(0.18, 0.045 * len(customs_hits)),
            "ocr_structure": self._ocr_structure_score(profile.document_type, structure),
            "table_pattern": min(0.16, 0.035 * len(table_hits) + (0.05 if table_hits and structure.table_ratio > 0.18 else 0.0)),
            "shipping_terms": min(0.18, 0.045 * len(shipping_hits)),
            "trade_fingerprint": min(0.14, 0.04 * len(fingerprint_hits)),
            "identifier_detection": min(0.22, 0.09 * len(identifier_hits)),
            "document_similarity": self._document_similarity_score(profile, structure),
        }
        penalty = min(0.16, structure.noisy_ratio * 0.18)
        if penalty:
            breakdown["ocr_noise_penalty"] = -penalty
        return breakdown

    def _ocr_structure_score(self, document_type: DocumentType, structure: OCRStructure) -> float:
        score = 0.0
        if structure.key_value_ratio >= 0.18:
            score += 0.05
        if structure.table_ratio >= 0.20:
            score += 0.05
        if document_type == DocumentType.INVOICE and structure.money_count:
            score += min(0.08, 0.025 * structure.money_count)
        if document_type == DocumentType.PACKING_LIST and structure.weight_count:
            score += min(0.10, 0.03 * structure.weight_count)
        if document_type in {DocumentType.BILL_OF_LADING, DocumentType.BOOKING, DocumentType.SHIPPING_ORDER} and structure.container_count:
            score += 0.08
        if document_type in {DocumentType.DS2_DECLARATION, DocumentType.EXPORT_DECLARATION, DocumentType.TAX_SHEET} and structure.numeric_ratio >= 0.16:
            score += 0.06
        return min(0.16, score)

    def _structure(self, text: str) -> OCRStructure:
        normalized = self._normalize(text)
        raw_lines = tuple(line.strip() for line in text.replace("\r\n", "\n").splitlines() if line.strip())
        lines = tuple(self._normalize(line) for line in raw_lines)
        header = self._normalize("\n".join(raw_lines[:14]))
        line_count = max(1, len(lines))
        key_value_lines = sum(1 for line in lines if re.search(r"[:：]\s*\S+|(?:no|number|日期|號碼)\s*[:：]?", line))
        table_lines = sum(1 for line in lines if self._looks_like_table_row(line))
        numeric_chars = sum(1 for char in normalized if char.isdigit())
        noisy_chars = sum(1 for char in normalized if char in "�□■◆◇�")
        return OCRStructure(
            normalized=normalized,
            header=header,
            lines=lines,
            key_value_ratio=key_value_lines / line_count,
            table_ratio=table_lines / line_count,
            numeric_ratio=numeric_chars / max(1, len(normalized)),
            money_count=len(re.findall(r"\b(?:usd|eur|jpy|ntd|twd)?\s*\d{1,3}(?:,\d{3})*(?:\.\d{2,4})\b", normalized)),
            weight_count=len(re.findall(r"\b\d+(?:,\d{3})*(?:\.\d+)?\s*(?:kgs?|mts?|mt|lb|lbs)\b|毛重|淨重", normalized)),
            container_count=len(re.findall(r"\b[A-Z]{4}\s*\d{7}\b", normalized, re.IGNORECASE)),
            noisy_ratio=noisy_chars / max(1, len(normalized)),
            tokens=tuple(re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]{1,}", normalized)),
        )

    def _looks_like_table_row(self, line: str) -> bool:
        if line.count("|") >= 2 or line.count("\t") >= 2:
            return True
        columns = [part for part in re.split(r"\s{2,}", line) if part]
        if len(columns) >= 3 and any(re.search(r"\d", column) for column in columns):
            return True
        return bool(re.search(r"\b(?:qty|quantity|ctn|ctns|kgs?|cbm|amount|unit price|稅則|數量|單價|金額)\b", line))

    def _evidence(self, profile: DocumentSemanticProfile, structure: OCRStructure) -> list[str]:
        evidence = [
            *self._semantic_hits(structure.header, profile.layout_terms)[:3],
            *self._semantic_hits(structure.normalized, profile.semantic_fields)[:5],
            *self._semantic_hits(structure.normalized, profile.customs_vocabulary)[:4],
            *self._semantic_hits(structure.normalized, profile.shipping_terms)[:4],
            *self._semantic_hits(structure.normalized, profile.trade_fingerprint)[:3],
        ]
        return self._dedupe(evidence)[:8] or ["版面與欄位結構符合此類文件"]

    def _hits(self, text: str, terms: tuple[str, ...]) -> list[str]:
        return [term for term in terms if term and term.casefold() in text]

    def _semantic_hits(self, text: str, terms: tuple[str, ...]) -> list[str]:
        hits = self._hits(text, terms)
        for term in terms:
            if not term or term in hits:
                continue
            if self._approximate_contains(text, term):
                hits.append(term)
        return self._dedupe(hits)

    def _approximate_contains(self, text: str, term: str) -> bool:
        normalized_term = self._normalize(term)
        if len(normalized_term) < 5 or normalized_term in text:
            return normalized_term in text
        compact_text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)
        compact_term = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", normalized_term)
        if len(compact_term) < 5:
            return compact_term in compact_text
        if compact_term in compact_text:
            return True
        window = len(compact_term)
        best = 0.0
        for index in range(0, max(1, len(compact_text) - window + 1), max(1, window // 3)):
            chunk = compact_text[index : index + window]
            best = max(best, SequenceMatcher(None, compact_term, chunk).ratio())
            if best >= 0.82:
                return True
        return False

    def _document_similarity_score(self, profile: DocumentSemanticProfile, structure: OCRStructure) -> float:
        anchors = (
            profile.layout_terms
            + profile.semantic_fields
            + profile.customs_vocabulary
            + profile.shipping_terms
            + profile.trade_fingerprint
        )
        anchor_tokens = {
            token
            for anchor in anchors
            for token in re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]{1,}", self._normalize(anchor))
            if token not in {"no", "of", "the"}
        }
        if not anchor_tokens:
            return 0.0
        overlap = len(anchor_tokens.intersection(structure.tokens)) / len(anchor_tokens)
        return min(0.12, overlap * 0.22)

    def _regex_hits(self, text: str, patterns: tuple[str, ...]) -> list[str]:
        return [pattern for pattern in patterns if re.search(pattern, text, re.IGNORECASE)]

    def _normalize(self, text: str) -> str:
        text = text.casefold()
        text = text.replace("：", ":").replace("　", " ")
        text = re.sub(r"[‐‑‒–—]", "-", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result
