from __future__ import annotations

import hashlib
from collections import defaultdict

from engine.intake.shipment_model import ClassifiedDocument, Shipment
from v2.workflow.matcher import _key_similarity


GROUPING_KEYS = ("booking_no", "shipping_order_no", "bl_no", "invoice_no", "container_no", "vessel_voyage")


class ShipmentGrouper:
    def group(self, documents: list[ClassifiedDocument]) -> list[Shipment]:
        if not documents:
            return []

        parent = list(range(len(documents)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        reasons: dict[int, list[str]] = defaultdict(list)
        scores: dict[int, list[float]] = defaultdict(list)
        for left in range(len(documents)):
            for right in range(left + 1, len(documents)):
                score, reason = self._score_pair(documents[left], documents[right])
                if score >= 0.6:
                    union(left, right)
                    bucket = find(left)
                    reasons[bucket].append(reason)
                    scores[bucket].append(score)

        buckets: dict[int, list[ClassifiedDocument]] = defaultdict(list)
        for index, document in enumerate(documents):
            buckets[find(index)].append(document)

        if len(buckets) == len(documents) and self._can_fallback_single_shipment(documents):
            shipment = Shipment(
                shipment_id=self._shipment_id(self._merge_keys(documents), documents),
                grouping_keys=self._merge_keys(documents),
                grouping_confidence="pending_review",
                grouping_reasons=["single intake folder without conflicting shipment keys"],
            )
            for document in documents:
                self._assign(shipment, document)
            return [shipment]

        shipments: list[Shipment] = []
        for bucket, docs in buckets.items():
            merged_keys = self._merge_keys(docs)
            score = max(scores.get(bucket, [0.0]))
            shipment = Shipment(
                shipment_id=self._shipment_id(merged_keys, docs),
                grouping_keys=merged_keys,
                grouping_confidence=self._confidence(score, len(docs)),
                grouping_reasons=self._dedupe(reasons.get(bucket, [])),
            )
            for doc in docs:
                self._assign(shipment, doc)
            shipments.append(shipment)

        if len(shipments) > 1:
            return shipments

        shipment = shipments[0]
        if not shipment.grouping_reasons and len(shipment.documents) > 1:
            shipment.grouping_reasons.append("single intake folder with no conflicting shipment keys")
            shipment.grouping_confidence = "pending_review"
        return shipments

    def _can_fallback_single_shipment(self, documents: list[ClassifiedDocument]) -> bool:
        values_by_key: dict[str, set[str]] = defaultdict(set)
        for document in documents:
            for key in GROUPING_KEYS:
                value = document.keys.get(key)
                if value:
                    values_by_key[key].add(value)
        for values in values_by_key.values():
            if len(values) > 1:
                return False
        high_signal_types = {"invoice", "packing", "declaration", "bl", "so", "clearance_list", "drawback_standard", "tax_sheet"}
        counts: dict[str, int] = defaultdict(int)
        for document in documents:
            if document.document_type in high_signal_types:
                counts[document.document_type] += 1
        return not any(count > 1 for count in counts.values())

    def _score_pair(self, left: ClassifiedDocument, right: ClassifiedDocument) -> tuple[float, str]:
        best_score = 0.0
        best_reason = ""
        for key in GROUPING_KEYS:
            left_value = left.keys.get(key, "")
            right_value = right.keys.get(key, "")
            if not left_value or not right_value:
                continue
            score = _key_similarity(left_value, right_value)
            if score > best_score:
                best_score = score
                best_reason = f"{key}: {left_value} ~= {right_value}"
        if best_score >= 0.88:
            return 0.9, best_reason
        if best_score >= 0.72:
            return 0.65, best_reason
        return 0.0, ""

    def _merge_keys(self, docs: list[ClassifiedDocument]) -> dict[str, str]:
        merged: dict[str, str] = {}
        for key in GROUPING_KEYS:
            values = [doc.keys.get(key, "") for doc in docs if doc.keys.get(key)]
            if values:
                merged[key] = values[0]
        return merged

    def _shipment_id(self, keys: dict[str, str], docs: list[ClassifiedDocument]) -> str:
        for key in ("booking_no", "shipping_order_no", "bl_no", "invoice_no", "container_no"):
            if keys.get(key):
                return keys[key]
        digest = hashlib.sha1("|".join(doc.source_name for doc in docs).encode("utf-8", errors="ignore")).hexdigest()[:8]
        return f"SHIPMENT-{digest.upper()}"

    def _confidence(self, score: float, count: int) -> str:
        if count <= 1:
            return "pending_review"
        if score >= 0.88:
            return "high_confidence"
        if score >= 0.6:
            return "partial_match"
        return "pending_review"

    def _assign(self, shipment: Shipment, document: ClassifiedDocument) -> None:
        if document.document_type == "invoice" and shipment.invoice is None:
            shipment.invoice = document
        elif document.document_type == "packing" and shipment.packing is None:
            shipment.packing = document
        elif document.document_type == "declaration" and shipment.declaration is None:
            shipment.declaration = document
        elif document.document_type == "bl" and shipment.bl is None:
            shipment.bl = document
        elif document.document_type == "so" and shipment.so is None:
            shipment.so = document
        elif document.document_type == "clearance_list" and shipment.material_list is None:
            shipment.material_list = document
        elif document.document_type == "drawback_standard" and shipment.drawback_standard is None:
            shipment.drawback_standard = document
        elif document.document_type == "tax_sheet" and shipment.tax_sheet is None:
            shipment.tax_sheet = document
        elif document.document_type == "image_scan":
            shipment.images.append(document)
        else:
            shipment.other_documents.append(document)

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result
