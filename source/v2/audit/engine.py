from __future__ import annotations

from v2.core.checking import DeclarationDocumentChecker
from v2.core.models import CanonicalField, CheckResult, CheckStatus, DocumentCheckReport, DocumentType, ParsedDocument
from v2.workflow.models import CaseStatus, CaseWorkflow


class CustomsAuditEngine:
    def __init__(self) -> None:
        self.checker = DeclarationDocumentChecker()

    def audit_case(self, case: CaseWorkflow) -> DocumentCheckReport:
        parsed = [segment.parsed for segment in case.documents if segment.parsed]
        if case.direction == "export":
            report = self._audit_export(parsed)
        else:
            report = self.checker.check_documents(parsed)
        case.audit_report = report
        if report.status in {CheckStatus.MISMATCH, CheckStatus.HIGH_RISK}:
            case.status = CaseStatus.EXCEPTION
        elif report.status == CheckStatus.MISSING or case.missing_documents:
            case.status = CaseStatus.MISSING_DOCUMENTS
        else:
            case.status = CaseStatus.COMPLETE
        return report

    def _audit_export(self, documents: list[ParsedDocument]) -> DocumentCheckReport:
        booking = next(
            (
                document
                for document in documents
                if document.document_type
                in {DocumentType.BOOKING, DocumentType.SHIPPING_ORDER, DocumentType.BOOKING_CONFIRMATION}
            ),
            None,
        )
        declaration = next((document for document in documents if document.document_type == DocumentType.EXPORT_DECLARATION), None)
        compare_targets = [
            document
            for document in documents
            if document is not booking
            and document.document_type
            in {DocumentType.BILL_OF_LADING, DocumentType.PACKING_LIST, DocumentType.PACKING_DETAIL, DocumentType.EXPORT_DECLARATION}
        ]
        if booking is None:
            return DocumentCheckReport(
                status=CheckStatus.HIGH_RISK,
                summary="缺少定倉單 / S/O / Booking，無法完成出口工作流核對。",
                declaration=declaration,
                documents=documents,
                high_risk_warnings=["請上傳 Booking Confirmation、S/O 或 Shipping Order。"],
            )

        fields = (
            CanonicalField.VESSEL_VOYAGE,
            CanonicalField.VESSEL,
            CanonicalField.VOYAGE,
            CanonicalField.POL,
            CanonicalField.POD,
            CanonicalField.ETD,
            CanonicalField.ETA,
            CanonicalField.CONTAINER_NO,
            CanonicalField.SEAL_NO,
            CanonicalField.PACKAGE_COUNT,
            CanonicalField.GROSS_WEIGHT,
            CanonicalField.CBM,
        )
        results = [self._compare_booking_field(field, booking, compare_targets) for field in fields]
        warnings = [result.message for result in results if result.status != CheckStatus.MATCH]
        if any(result.status == CheckStatus.MISMATCH for result in results):
            status = CheckStatus.MISMATCH
            summary = "出口文件與定倉單存在不一致欄位。"
        elif warnings:
            status = CheckStatus.MISSING
            summary = "出口文件仍有欄位缺漏，需補文件或人工確認。"
        else:
            status = CheckStatus.MATCH
            summary = "出口文件與定倉單核對一致。"
        return DocumentCheckReport(status, summary, declaration, documents, results, warnings)

    def _compare_booking_field(
        self,
        field: CanonicalField,
        booking: ParsedDocument,
        targets: list[ParsedDocument],
    ) -> CheckResult:
        booking_value = self._field_value(booking, field)
        values = {
            target.source_name or target.document_type.value: value
            for target in targets
            if (value := self._field_value(target, field))
        }
        if not booking_value:
            return CheckResult(field, CheckStatus.MISSING, "", values, f"{field.value}: 定倉單缺少欄位")
        if not values:
            return CheckResult(field, CheckStatus.MISSING, booking_value, values, f"{field.value}: 比對文件缺少欄位")
        mismatches = {name: value for name, value in values.items() if self._normalize(value) != self._normalize(booking_value)}
        if mismatches:
            return CheckResult(field, CheckStatus.MISMATCH, booking_value, values, f"{field.value}: 定倉單與 {', '.join(mismatches)} 不一致")
        return CheckResult(field, CheckStatus.MATCH, booking_value, values, f"{field.value}: 一致")

    def _field_value(self, document: ParsedDocument, field: CanonicalField) -> str:
        for parsed in document.fields:
            if parsed.canonical == field:
                return parsed.value
        return ""

    def _normalize(self, value: str) -> str:
        return " ".join(value.casefold().replace(",", "").split())
