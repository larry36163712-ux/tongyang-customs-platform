from __future__ import annotations

from collections import Counter

from v2.core.models import DocumentType, TemplateProfile


class CustomerTemplateLearningService:
    """Stores the future learning/classification boundary for customer formats."""

    def __init__(self) -> None:
        self._profiles: list[TemplateProfile] = [
            TemplateProfile(
                template_id="scanteak-supplier-cluster-a",
                customer="詩肯",
                supplier="未分類供應商 A",
                country="VN",
                document_type=DocumentType.INVOICE,
                signature_terms=("invoice", "quantity", "pcs"),
                sample_count=18,
                failure_count=2,
            ),
            TemplateProfile(
                template_id="scanteak-supplier-cluster-b",
                customer="詩肯",
                supplier="未分類供應商 B",
                country="MY",
                document_type=DocumentType.PACKING_LIST,
                signature_terms=("packing list", "carton", "gross weight"),
                sample_count=11,
                failure_count=3,
            ),
        ]

    def profiles(self) -> list[TemplateProfile]:
        return list(self._profiles)

    def customer_format_counts(self) -> Counter[str]:
        counts: Counter[str] = Counter()
        for profile in self._profiles:
            counts[profile.customer] += 1
        return counts

