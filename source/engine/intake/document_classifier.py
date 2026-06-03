from __future__ import annotations

import re
from dataclasses import dataclass

from engine.intake.shipment_model import ClassifiedDocument
from v2.core.models import DocumentType
from v2.workflow.matcher import WorkflowMatcher
from v2.workflow.models import IntakeFile


@dataclass(frozen=True)
class ClassificationRule:
    document_type: str
    terms: tuple[str, ...]
    negative_terms: tuple[str, ...] = ()
    base_confidence: float = 0.55


class DocumentClassifier:
    """Content-first classifier for customs documents.

    Filenames are deliberately excluded from scoring. A file named scan001.pdf
    or IMG_8832.jpg is classified from extracted text/OCR, semantic keywords,
    and shipment identifiers.
    """

    RULES: tuple[ClassificationRule, ...] = (
        ClassificationRule("declaration", ("報單", "進口報單", "出口報單", "海關報單", "DECLARATION", "DS2"), base_confidence=0.78),
        ClassificationRule("invoice", ("COMMERCIAL INVOICE", "INVOICE", "INV NO", "INVOICE NO", "發票"), base_confidence=0.76),
        ClassificationRule("packing", ("PACKING LIST", "PACKING", "P/L", "PACKAGE", "CTNS", "裝箱單", "裝箱明細"), base_confidence=0.72),
        ClassificationRule("bl", ("BILL OF LADING", "B/L", "BL NO", "LADING", "提單"), base_confidence=0.78),
        ClassificationRule("so", ("SHIPPING ORDER", "S/O", "BOOKING CONFIRMATION", "BOOKING NO", "訂艙", "定倉"), base_confidence=0.74),
        ClassificationRule("clearance_list", ("清表", "資料清表", "用料清表", "MATERIAL LIST", "MATERIAL CLEARANCE"), base_confidence=0.72),
        ClassificationRule("drawback_standard", ("核退標準", "核退清表", "DRAWBACK STANDARD", "退稅標準"), base_confidence=0.74),
        ClassificationRule("tax_sheet", ("稅單", "稅額", "進口稅", "TAX", "DUTY", "DUTY MEMO"), base_confidence=0.70),
        ClassificationRule("arrival_notice", ("ARRIVAL NOTICE", "到貨通知", "抵港通知"), base_confidence=0.70),
    )

    DOCUMENT_TYPE_MAP = {
        "declaration": DocumentType.DS2_DECLARATION,
        "invoice": DocumentType.INVOICE,
        "packing": DocumentType.PACKING_LIST,
        "bl": DocumentType.BILL_OF_LADING,
        "so": DocumentType.SHIPPING_ORDER,
        "clearance_list": DocumentType.CLEARANCE_LIST,
        "drawback_standard": DocumentType.DRAWBACK_CLEARANCE,
        "tax_sheet": DocumentType.TAX_SHEET,
        "arrival_notice": DocumentType.ARRIVAL_NOTICE,
        "image_scan": DocumentType.IMAGE_SCAN,
    }

    IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

    def __init__(self) -> None:
        self.matcher = WorkflowMatcher()

    def classify(self, intake_file: IntakeFile) -> ClassifiedDocument:
        text = intake_file.text or ""
        normalized = self._normalize(text)
        scores: list[tuple[float, ClassificationRule, list[str]]] = []
        first_lines = "\n".join(line.strip() for line in text.splitlines()[:8])
        normalized_header = self._normalize(first_lines)
        for rule in self.RULES:
            hits = [term for term in rule.terms if self._normalize(term) in normalized]
            negative_hits = [term for term in rule.negative_terms if self._normalize(term) in normalized]
            if not hits or negative_hits:
                continue
            header_hits = [term for term in hits if self._normalize(term) in normalized_header]
            score = rule.base_confidence + min(0.18, 0.04 * (len(hits) - 1))
            if header_hits:
                score += 0.08
            if self._normalize(rule.terms[0]) in normalized_header:
                score += 0.08
            scores.append((min(0.98, score), rule, hits))

        if scores:
            score, rule, hits = sorted(scores, key=lambda item: item[0], reverse=True)[0]
            document_type = rule.document_type
            confidence = score
            reasons = [f"content terms: {', '.join(hits[:4])}"]
        else:
            document_type = "image_scan" if intake_file.suffix.lower() in self.IMAGE_SUFFIXES else "unknown"
            confidence = 0.35 if text.strip() else 0.0
            reasons = ["no document-specific content terms matched"]

        keys = self.matcher.match_keys(None, text)
        warnings = []
        if confidence < 0.55:
            warnings.append("low classification confidence")
        if not text.strip():
            warnings.append("no extracted text")

        return ClassifiedDocument(
            path=intake_file.path,
            source_name=intake_file.path.name,
            suffix=intake_file.suffix,
            document_type=document_type,
            confidence=confidence,
            text=text,
            keys=keys,
            reasons=reasons,
            warnings=warnings,
        )

    def to_v2_document_type(self, document_type: str) -> DocumentType:
        return self.DOCUMENT_TYPE_MAP.get(document_type, DocumentType.UNKNOWN)

    def _normalize(self, value: str) -> str:
        value = value.casefold()
        value = re.sub(r"\s+", " ", value)
        return value.strip()
