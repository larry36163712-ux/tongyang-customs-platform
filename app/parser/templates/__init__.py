from __future__ import annotations

from app.parser.templates.tai_hwei import parse_tai_hwei


def parse_with_customer_template(doc_type: str, text: str, source_name: str = "") -> dict[str, str]:
    """Dispatch customer-specific parser templates.

    New customer templates should be added here and return only fields they can
    confidently extract. The generic parser remains the fallback.
    """
    fields = parse_tai_hwei(doc_type, text, source_name)
    if fields:
        return fields
    return {}
