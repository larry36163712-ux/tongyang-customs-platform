from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.parser.document import ParsedDocument, UploadedDocument
from app.shared.models import CheckItem


DS2_DOC_TYPE = "DS2報單"
SUM_FIELDS = {"件數", "FOB", "毛重", "淨重"}
MERGED_BL_SUM_FIELDS = ["件數", "毛重", "淨重", "FOB"]


def document_items(required_documents: list[str], documents: dict[str, list[UploadedDocument]]) -> list[CheckItem]:
    items: list[CheckItem] = []
    for doc_type in required_documents:
        count = len(documents.get(doc_type, []))
        if count:
            items.append(CheckItem.match("文件", f"{doc_type} 已上傳 {count} 份"))
        else:
            items.append(CheckItem.warning("文件", f"{doc_type} 尚未上傳", expected="已上傳", actual="缺少"))
    return items


def parsed_field_items(parsed_documents: dict[str, list[ParsedDocument]]) -> list[CheckItem]:
    items: list[CheckItem] = []
    for doc_type, docs in parsed_documents.items():
        for index, parsed in enumerate(docs, start=1):
            label = _doc_label(doc_type, index, parsed)
            if parsed.error:
                items.append(CheckItem.warning(f"{label} 解析", parsed.error, expected="可解析文字", actual="解析失敗"))
                continue
            if not parsed.fields:
                items.append(CheckItem.warning(f"{label} 解析", "未抓到指定欄位。", expected="欄位值", actual="空白"))
                continue
            values = "；".join(f"{field}={value}" for field, value in parsed.fields.items())
            items.append(CheckItem.match(f"{label} 解析", values, expected=values, actual=values))
    return items


def compare_formal_documents(
    parsed_documents: dict[str, list[ParsedDocument]],
    fields: list[str],
) -> list[CheckItem]:
    items: list[CheckItem] = []
    formal_docs = _formal_documents(parsed_documents)
    for field in fields:
        values = _field_values(formal_docs, field)
        if len(values) < 2:
            continue
        if field in SUM_FIELDS:
            items.extend(_compare_aggregated_formal_field(field, values))
        elif merged_bl_item := _merged_bl_case_item(parsed_documents, field, values):
            items.append(merged_bl_item)
        else:
            items.append(_compare_value_set(field, values))
    return items


def compare_ds2_with_documents(
    parsed_documents: dict[str, list[ParsedDocument]],
    fields: list[str],
) -> list[CheckItem]:
    items: list[CheckItem] = []
    formal_docs = _formal_documents(parsed_documents)
    ds2_docs = parsed_documents.get(DS2_DOC_TYPE, [])
    if not ds2_docs:
        return items

    for field in fields:
        formal_values = _field_values(formal_docs, field)
        ds2_values = _field_values({DS2_DOC_TYPE: ds2_docs}, field)
        if not formal_values or not ds2_values:
            continue

        if field in SUM_FIELDS:
            formal_total = _formal_consensus_total(field, formal_values)
            ds2_total = _sum_values(ds2_values)
            if formal_total is None or ds2_total is None:
                continue
            if formal_total == ds2_total:
                items.append(CheckItem.match(field, f"DS2 與文件彙總一致：{_format_decimal(ds2_total)}"))
            else:
                items.append(
                    CheckItem.mismatch(
                        field,
                        "DS2 與文件不一致。",
                        expected=f"文件彙總：{_format_decimal(formal_total)}",
                        actual=_format_ds2_difference(field, formal_values, ds2_values),
                    )
                )
            continue

        consensus = _consensus_value(formal_values)
        if consensus is None and field == "貨櫃號":
            items.append(_compare_ds2_container_set(field, formal_values, ds2_values))
            continue
        if consensus is None:
            continue
        ds2_normalized = {_normalize_text(value) for _, value in ds2_values}
        if ds2_normalized == {consensus}:
            items.append(CheckItem.match(field, f"DS2 與文件一致：{_first_original(formal_values)}"))
        else:
            items.append(
                CheckItem.mismatch(
                    field,
                    "DS2 與文件不一致。",
                    expected=f"文件一致：{_matching_document_lines(formal_values)}",
                    actual=f"DS2：{_value_lines(ds2_values)}",
                )
            )
    return items


def resolved_fields(items: list[CheckItem]) -> set[str]:
    return {
        item.field
        for item in items
        if item.field != "文件" and not item.field.endswith("解析")
    }


def parsed_document_fields(parsed_documents: dict[str, list[ParsedDocument]]) -> set[str]:
    fields: set[str] = set()
    for docs in parsed_documents.values():
        for parsed in docs:
            fields.update(parsed.fields)
    return fields


def _formal_documents(parsed_documents: dict[str, list[ParsedDocument]]) -> dict[str, list[ParsedDocument]]:
    return {doc_type: docs for doc_type, docs in parsed_documents.items() if doc_type != DS2_DOC_TYPE}


def _field_values(
    documents: dict[str, list[ParsedDocument]],
    field: str,
) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for doc_type, docs in documents.items():
        for index, parsed in enumerate(docs, start=1):
            if field in parsed.fields:
                values.append((_doc_label(doc_type, index, parsed), parsed.fields[field]))
    return values


def _compare_aggregated_formal_field(field: str, values: list[tuple[str, str]]) -> list[CheckItem]:
    totals = _totals_by_doc_type(values)
    if len(totals) < 2:
        return []
    unique_totals = set(totals.values())
    details = "；".join(f"{doc_type}={_format_decimal(total)}" for doc_type, total in totals.items())
    if len(unique_totals) == 1:
        return [CheckItem.match(field, f"文件彙總一致：{details}")]
    return [
        CheckItem.warning(
            field,
            "文件彼此不一致。",
            expected="正式文件彼此一致",
            actual=details,
        )
    ]


def _compare_value_set(field: str, values: list[tuple[str, str]]) -> CheckItem:
    normalized = {_normalize_text(value) for _, value in values}
    details = _value_lines(values)
    if len(normalized) == 1:
        return CheckItem.match(field, f"文件彼此一致：{details}")
    return CheckItem.warning(field, "文件彼此不一致。", expected="正式文件彼此一致", actual=details)


def _merged_bl_case_item(
    parsed_documents: dict[str, list[ParsedDocument]],
    field: str,
    values: list[tuple[str, str]],
) -> CheckItem | None:
    if field != "貨櫃號":
        return None

    bl_docs = parsed_documents.get("B/L", [])
    if len(bl_docs) < 2:
        return None

    bl_containers = [doc.fields.get("貨櫃號", "") for doc in bl_docs if doc.fields.get("貨櫃號")]
    unique_containers = {_normalize_text(value) for value in bl_containers}
    if len(unique_containers) < 2:
        return None

    matched_fields = _merged_bl_consistent_sum_fields(parsed_documents)
    if not matched_fields:
        return None

    details = (
        "多份 B/L、多貨櫃屬正常情況。\n"
        f"B/L 份數：{len(bl_docs)}\n"
        f"貨櫃號：{', '.join(bl_containers)}\n"
        f"已確認加總合理：{', '.join(matched_fields)}\n"
        f"{_value_lines(values)}"
    )
    return CheckItem.warning("合併提單案件", "多份 B/L、多貨櫃屬正常情況。", expected="合併提單案件", actual=details)


def _merged_bl_consistent_sum_fields(parsed_documents: dict[str, list[ParsedDocument]]) -> list[str]:
    formal_docs = _formal_documents(parsed_documents)
    ds2_docs = parsed_documents.get(DS2_DOC_TYPE, [])
    matched: list[str] = []

    for field in MERGED_BL_SUM_FIELDS:
        formal_totals = _totals_by_doc_type(_field_values(formal_docs, field))
        ds2_total = _sum_values(_field_values({DS2_DOC_TYPE: ds2_docs}, field)) if ds2_docs else None

        if ds2_total is not None and ds2_total in set(formal_totals.values()):
            matched.append(field)
            continue

        if len(formal_totals) >= 2 and len(set(formal_totals.values())) == 1:
            matched.append(field)

    return matched


def _compare_ds2_container_set(
    field: str,
    formal_values: list[tuple[str, str]],
    ds2_values: list[tuple[str, str]],
) -> CheckItem:
    formal_containers = _container_set(value for _, value in formal_values)
    ds2_containers = _container_set(value for _, value in ds2_values)
    if formal_containers and formal_containers.issubset(ds2_containers):
        return CheckItem.match(field, f"DS2 已包含正式文件貨櫃：{', '.join(sorted(formal_containers))}")
    missing = formal_containers - ds2_containers
    return CheckItem.mismatch(
        field,
        "DS2 與文件貨櫃號不一致。",
        expected=f"正式文件貨櫃：{', '.join(sorted(formal_containers))}",
        actual=f"DS2：{', '.join(sorted(ds2_containers))}\n缺少：{', '.join(sorted(missing))}",
    )


def _container_set(values) -> set[str]:
    containers: set[str] = set()
    for value in values:
        containers.update(re.findall(r"[A-Z]{4}\d{7}", _normalize_text(value)))
    return containers


def _formal_consensus_total(field: str, values: list[tuple[str, str]]) -> Decimal | None:
    totals = _totals_by_doc_type(values)
    if not totals or len(set(totals.values())) != 1:
        return None
    return next(iter(totals.values()))


def _sum_values(values: list[tuple[str, str]]) -> Decimal | None:
    total = Decimal("0")
    found = False
    for _, value in values:
        number = _number(value)
        if number is None:
            continue
        total += number
        found = True
    return total if found else None


def _totals_by_doc_type(values: list[tuple[str, str]]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for label, value in values:
        doc_type = label.split("（", 1)[0].split("#", 1)[0]
        number = _number(value)
        if number is None:
            continue
        totals[doc_type] = totals.get(doc_type, Decimal("0")) + number
    return totals


def _number(value: str) -> Decimal | None:
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def _consensus_value(values: list[tuple[str, str]]) -> str | None:
    normalized = {_normalize_text(value) for _, value in values}
    if len(normalized) != 1:
        return None
    return next(iter(normalized))


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().upper()


def _value_lines(values: list[tuple[str, str]]) -> str:
    return "\n".join(f"{label}：{value}" for label, value in values)


def _matching_document_lines(values: list[tuple[str, str]]) -> str:
    return _value_lines(values)


def _format_ds2_difference(
    field: str,
    formal_values: list[tuple[str, str]],
    ds2_values: list[tuple[str, str]],
) -> str:
    return (
        f"哪些文件一致：\n{_value_lines(formal_values)}\n"
        f"DS2 與哪份不同：\n{_value_lines(ds2_values)}"
    )


def _first_original(values: list[tuple[str, str]]) -> str:
    return values[0][1]


def _format_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def _doc_label(doc_type: str, index: int, parsed: ParsedDocument) -> str:
    suffix = f"#{index}" if index > 1 else ""
    return f"{doc_type}{suffix}（{parsed.source_name}）"
