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
    """Content-first customs document understanding.

    The classifier does not trust filenames as the primary signal. It scores
    layout, field structure, customs vocabulary, table shape, shipping language,
    and trade-document fingerprints. Filenames are only used as weak tie-break
    evidence for scanned files with sparse OCR.
    """

    CONFIRMED_THRESHOLD = 0.78
    CANDIDATE_THRESHOLD = 0.34

    PROFILES: tuple[DocumentSemanticProfile, ...] = (
        DocumentSemanticProfile(
            DocumentType.DS2_DECLARATION,
            layout_terms=("進口報單", "海關進口報單", "報單", "import declaration", "declaration", "ds2"),
            semantic_fields=(
                "報單號碼",
                "進口人",
                "納稅義務人",
                "申報單位",
                "稅則",
                "統計方式",
                "完稅價格",
                "稅率",
                "稅額",
                "推貿費",
                "匯率",
                "船名航次",
                "淨重",
                "毛重",
                "件數",
                "貨物名稱",
                "cif",
                "fob",
                "hs code",
                "duty amount",
                "exchange rate",
            ),
            customs_vocabulary=("海關", "進口", "報單", "稅則", "完稅", "統計", "稅額", "納稅", "申報"),
            table_patterns=("項次", "稅則", "貨名", "完稅價格", "統計方式", "稅率", "稅額", "毛重", "淨重"),
            trade_fingerprint=("cif", "fob", "運費", "保費", "匯率", "納稅辦法", "通關方式"),
            identifier_patterns=(
                r"進口\s*報單",
                r"海關\s*進口\s*報單",
                r"報單\s*(?:號碼|號別|號碼?)",
                r"稅則",
                r"統計方式",
                r"完稅價格",
                r"\bds2\b",
                r"\bimport\s+declaration\b",
                r"\bhs\s*code\b",
            ),
            minimum_score=0.30,
        ),
        DocumentSemanticProfile(
            DocumentType.INVOICE,
            layout_terms=("commercial invoice", "invoice", "發票"),
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
            table_patterns=("n.w.", "g.w.", "nw", "gw", "meas", "cbm", "kgs", "kg", "carton", "ctn", "bales"),
            trade_fingerprint=("shipping mark", "marks", "description of goods", "package type"),
            identifier_patterns=(r"\b(?:gross|net)\s*weight\b", r"\b\d+(?:\.\d+)?\s*(?:ctns|cartons|packages|pkgs|bales)\b", r"毛重|淨重|材積"),
        ),
        DocumentSemanticProfile(
            DocumentType.BILL_OF_LADING,
            layout_terms=("bill of lading", "b/l", "bl no", "提單"),
            semantic_fields=("b/l no", "bl no", "bill of lading no", "shipper", "consignee", "notify party", "vessel", "voyage", "no of original b/l", "託運人", "受貨人", "提單號碼"),
            table_patterns=("container", "seal", "packages", "gross weight", "measurement"),
            shipping_terms=("port of loading", "port of discharge", "place of receipt", "place of delivery", "freight", "carrier", "裝貨港", "卸貨港"),
            trade_fingerprint=("original", "no of original b/l", "non-negotiable", "laden on board", "ocean vessel", "shipped on board"),
            identifier_patterns=(r"\b(?:b/l|bl)\s*(?:no|number|#)\b", r"\bno\s+of\s+original\s+b/l\b", r"\bbill\s+of\s+lading\b", r"\b[A-Z]{4}\s*\d{7}\b", r"提單號碼|託運人|受貨人"),
        ),
        DocumentSemanticProfile(
            DocumentType.ARRIVAL_NOTICE,
            layout_terms=("arrival notice", "notice of arrival", "到貨通知", "抵港通知"),
            semantic_fields=("notice no", "arrival date", "free time", "delivery order", "d/o no", "pickup location", "eta", "到港日", "免費倉期", "貨櫃場", "費用明細"),
            table_patterns=("demurrage", "detention", "free time", "charge", "storage", "delivery order", "費用", "倉租"),
            shipping_terms=("port of discharge", "terminal", "container yard", "carrier", "vessel", "voyage", "cy", "cfs"),
            trade_fingerprint=("arrival notice", "free time", "delivery order", "cargo release", "do release"),
            identifier_patterns=(r"\barrival\s+notice\b", r"\bnotice\s+of\s+arrival\b", r"\bfree\s+time\b", r"\bdelivery\s+order\b", r"到貨通知|抵港通知|到港日|費用明細"),
        ),
        DocumentSemanticProfile(
            DocumentType.SHIPPING_ORDER,
            layout_terms=("shipping order", "s/o", "so no", "shipping instruction", "裝船通知", "訂艙單"),
            semantic_fields=("shipping order no", "s/o no", "booking no", "vessel", "voyage", "container", "cut off", "close date"),
            shipping_terms=("cy cut", "si cut", "carrier", "forwarder", "port of loading", "port of discharge", "container type"),
            trade_fingerprint=("booking confirmation", "export closing", "terminal"),
            identifier_patterns=(r"\b(?:s/o|so|shipping order)\s*(?:no|number|#)\b", r"\bbooking\s*(?:no|number|#)\b", r"結關日|截關日"),
        ),
        DocumentSemanticProfile(
            DocumentType.BOOKING,
            layout_terms=("booking confirmation", "booking no", "booking", "訂艙"),
            semantic_fields=("booking no", "carrier", "forwarder", "vessel", "voyage", "etd", "eta", "container"),
            shipping_terms=("cy cut", "si cut", "port of loading", "port of discharge", "cut off"),
            trade_fingerprint=("space confirmation", "service contract", "closing time"),
            identifier_patterns=(r"\bbooking\s*(?:no|number|#)\b", r"訂艙|艙位確認"),
        ),
        DocumentSemanticProfile(
            DocumentType.TAX_SHEET,
            layout_terms=("稅單", "進口稅單", "稅費繳納"),
            semantic_fields=("稅額", "營業稅", "進口稅", "推貿費", "完稅價格", "繳納金額"),
            customs_vocabulary=("海關", "稅款", "稅單", "稅額", "推貿費"),
            table_patterns=("稅別", "稅率", "稅額", "合計"),
            identifier_patterns=(r"稅單", r"營業稅|進口稅|稅額", r"推貿費"),
        ),
        DocumentSemanticProfile(
            DocumentType.DRAWBACK_CLEARANCE,
            layout_terms=("核退標準", "核退清表", "退稅標準"),
            semantic_fields=("料號", "用料", "出口報單", "進口報單", "數量", "核退標準"),
            customs_vocabulary=("核退", "退稅", "清表", "標準"),
            table_patterns=("料號", "品名", "數量", "核退"),
            identifier_patterns=(r"核退", r"退稅標準", r"核退標準"),
        ),
        DocumentSemanticProfile(
            DocumentType.MATERIAL_CLEARANCE,
            layout_terms=("用料清表", "清表"),
            semantic_fields=("料號", "品名", "數量", "單位", "用量"),
            customs_vocabulary=("用料", "清表", "核退"),
            table_patterns=("料號", "品名", "數量", "單位"),
            identifier_patterns=(r"用料清表", r"用料", r"料號"),
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
        structure = self._structure(text)
        candidates: list[DocumentCandidate] = []

        for profile in self.PROFILES:
            breakdown = self._score_profile(profile, structure, filename)
            confidence = round(min(0.98, max(0.0, sum(breakdown.values()))), 2)
            if confidence >= profile.minimum_score:
                candidates.append(
                    DocumentCandidate(
                        profile.document_type,
                        confidence,
                        self._evidence(profile, structure, filename),
                        confidence < self.CONFIRMED_THRESHOLD,
                        {key: round(value, 2) for key, value in breakdown.items() if abs(value) > 0.001},
                    )
                )

        if not candidates and text.strip():
            candidates.append(
                DocumentCandidate(
                    DocumentType.UNKNOWN,
                    0.28,
                    ["已讀取文字，但版面與欄位不足以判斷文件類型"],
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
            return "尚未成功辨識"
        if candidate.needs_manual_confirm:
            return "AI 低信心，需人工確認"
        return "已確認文件"

    def _score_profile(self, profile: DocumentSemanticProfile, structure: OCRStructure, filename: str) -> dict[str, float]:
        layout_hits = self._semantic_hits(structure.header, profile.layout_terms) or self._semantic_hits(structure.normalized, profile.layout_terms)
        field_hits = self._semantic_hits(structure.normalized, profile.semantic_fields)
        customs_hits = self._semantic_hits(structure.normalized, profile.customs_vocabulary)
        table_hits = self._semantic_hits(structure.normalized, profile.table_patterns)
        shipping_hits = self._semantic_hits(structure.normalized, profile.shipping_terms)
        fingerprint_hits = self._semantic_hits(structure.normalized, profile.trade_fingerprint)
        identifier_hits = self._regex_hits(structure.normalized, profile.identifier_patterns)
        filename_hits = self._filename_hints(profile.document_type, filename)

        breakdown = {
            "layout_analysis": min(0.22, 0.12 * len(layout_hits)),
            "semantic_fields": min(0.32, 0.055 * len(field_hits)),
            "customs_vocabulary": min(0.20, 0.045 * len(customs_hits)),
            "ocr_structure": self._ocr_structure_score(profile.document_type, structure),
            "table_pattern": min(0.16, 0.035 * len(table_hits) + (0.05 if table_hits and structure.table_ratio > 0.18 else 0.0)),
            "shipping_terms": min(0.18, 0.045 * len(shipping_hits)),
            "trade_fingerprint": min(0.14, 0.04 * len(fingerprint_hits)),
            "identifier_detection": min(0.24, 0.09 * len(identifier_hits)),
            "document_similarity": self._document_similarity_score(profile, structure),
            "filename_hint": filename_hits,
        }
        if profile.document_type == DocumentType.DS2_DECLARATION:
            ds2_bonus = self._ds2_partial_bonus(structure, field_hits, customs_hits, table_hits, identifier_hits)
            if ds2_bonus:
                breakdown["ds2_partial_structure"] = ds2_bonus
        penalty = min(0.12, structure.noisy_ratio * 0.12)
        if penalty:
            breakdown["ocr_noise_penalty"] = -penalty
        return breakdown

    def _ds2_partial_bonus(
        self,
        structure: OCRStructure,
        field_hits: list[str],
        customs_hits: list[str],
        table_hits: list[str],
        identifier_hits: list[str],
    ) -> float:
        evidence_count = len(set(field_hits + customs_hits + table_hits + identifier_hits))
        if evidence_count >= 4:
            return 0.12
        if evidence_count >= 2 and structure.numeric_ratio >= 0.10:
            return 0.10
        if any(term in structure.normalized for term in ("稅則", "統計方式", "完稅價格", "報單")):
            return 0.08
        return 0.0

    def _filename_hints(self, document_type: DocumentType, filename: str) -> float:
        normalized = self._normalize(filename)
        if not normalized:
            return 0.0
        hints = {
            DocumentType.DS2_DECLARATION: ("報單", "ds2", "declaration"),
            DocumentType.INVOICE: ("invoice", "inv", "iv", "發票"),
            DocumentType.PACKING_LIST: ("packing", "pack", "pl", "pkg", "裝箱", "包裝"),
            DocumentType.ARRIVAL_NOTICE: ("arrival", "notice", "到貨", "抵港"),
            DocumentType.BILL_OF_LADING: ("b/l", "bl", "提單"),
            DocumentType.SHIPPING_ORDER: ("so", "s/o", "shipping order"),
            DocumentType.BOOKING: ("booking", "訂艙"),
            DocumentType.TAX_SHEET: ("稅單", "tax"),
        }
        if any(hint in normalized for hint in hints.get(document_type, ())):
            return 0.06
        return 0.0

    def _ocr_structure_score(self, document_type: DocumentType, structure: OCRStructure) -> float:
        score = 0.0
        if structure.key_value_ratio >= 0.16:
            score += 0.05
        if structure.table_ratio >= 0.18:
            score += 0.05
        if document_type == DocumentType.INVOICE and structure.money_count:
            score += min(0.08, 0.025 * structure.money_count)
        if document_type == DocumentType.PACKING_LIST and structure.weight_count:
            score += min(0.10, 0.03 * structure.weight_count)
        if document_type in {DocumentType.BILL_OF_LADING, DocumentType.BOOKING, DocumentType.SHIPPING_ORDER, DocumentType.ARRIVAL_NOTICE} and structure.container_count:
            score += 0.06
        if document_type in {DocumentType.DS2_DECLARATION, DocumentType.EXPORT_DECLARATION, DocumentType.TAX_SHEET} and structure.numeric_ratio >= 0.12:
            score += 0.08
        return min(0.16, score)

    def _structure(self, text: str) -> OCRStructure:
        normalized = self._normalize(text)
        raw_lines = tuple(line.strip() for line in text.replace("\r\n", "\n").splitlines() if line.strip())
        lines = tuple(self._normalize(line) for line in raw_lines)
        header = self._normalize("\n".join(raw_lines[:16]))
        line_count = max(1, len(lines))
        key_value_lines = sum(1 for line in lines if re.search(r"[:：]\s*\S+|(?:no|number|號碼|號別)\s*[:：]?", line))
        table_lines = sum(1 for line in lines if self._looks_like_table_row(line))
        numeric_chars = sum(1 for char in normalized if char.isdigit())
        noisy_chars = sum(1 for char in normalized if char in "�□■◆◇")
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
        return bool(re.search(r"\b(?:qty|quantity|ctn|ctns|kgs?|cbm|amount|unit price|稅則|件數|單價|金額|毛重|淨重)\b", line))

    def _evidence(self, profile: DocumentSemanticProfile, structure: OCRStructure, filename: str) -> list[str]:
        evidence = [
            *self._semantic_hits(structure.header, profile.layout_terms)[:3],
            *self._semantic_hits(structure.normalized, profile.semantic_fields)[:5],
            *self._semantic_hits(structure.normalized, profile.customs_vocabulary)[:4],
            *self._semantic_hits(structure.normalized, profile.shipping_terms)[:4],
            *self._semantic_hits(structure.normalized, profile.trade_fingerprint)[:3],
        ]
        if self._filename_hints(profile.document_type, filename):
            evidence.append(f"檔名弱提示：{filename}")
        return self._dedupe(evidence)[:8] or ["版面與欄位結構符合此類文件"]

    def _semantic_hits(self, text: str, terms: tuple[str, ...]) -> list[str]:
        hits = [term for term in terms if term and self._normalize(term) in text]
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
        anchors = profile.layout_terms + profile.semantic_fields + profile.customs_vocabulary + profile.shipping_terms + profile.trade_fingerprint
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
        text = re.sub(r"[：﹕]", ":", text)
        text = re.sub(r"[／]", "/", text)
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
