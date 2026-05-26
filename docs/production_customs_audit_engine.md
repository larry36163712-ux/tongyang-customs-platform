# Production Customs Audit Engine

## Architecture

The production audit layer is built on real parser output from `ParsedDocument` and `ParsedField`.

Modules:

- `v2.audit.normalization.SemanticNormalizationEngine`
- `v2.audit.validation.AuditValidationEngine`
- `v2.core.checking.DeclarationDocumentChecker`
- `v2.audit.engine.CustomsAuditEngine`
- `engine.report.NarrativeGenerator`
- `engine.report.SectionRenderer`

The workflow is:

1. Intake/OCR produces text.
2. Semantic parser extracts canonical fields.
3. Audit checker compares declaration fields against INV, PL, SO, B/L, clearance and refund-related documents.
4. Normalization engine applies customs semantic equivalence.
5. Validation engine performs formula and reasonableness checks.
6. Report renderer produces a human customs-broker style report.

## Normalization Engine

`SemanticNormalizationEngine` handles practical broker equivalence:

- `97 BLE`, `97 BALE`, `97 BALES` normalize to the same package meaning.
- `99.270 MTS` normalizes to `99,270 KGS`.
- `USD30277.35` and `USD 30,277.35` normalize to the same money value.
- HS codes compare by digits, so `7208.39` and `720839` match.
- Container, seal, invoice, B/L and booking identifiers are stripped of punctuation and OCR-repaired.

## Audit Logic

Implemented checks:

- Document completeness and identity numbers.
- Declaration audit.
- Invoice audit.
- Packing audit.
- B/L audit.
- SO / Booking audit.
- Clearance field logic.
- Tax and CIF logic.
- Refund/clearance support logic through clearance and drawback document fields.
- Risk detection.
- Human-readable summary and final conclusion.

## Validation Rules

`AuditValidationEngine` performs:

- CIF validation: `CIF = FOB + freight + insurance`.
- Unit price validation: `amount / quantity`.
- Weight conversion validation: MTS/KGS/KG normalization.
- Exchange-rate validation: foreign amount multiplied by declaration rate.
- Package reasonableness: package units are compared semantically.
- HS-code reasonableness: punctuation-insensitive tariff comparison.
- Statistical-method reasonableness: checks availability and links quantity/unit/HS code.

## Semantic Compare Strategy

Each field comparison uses parser output only. It does not use filenames or mock values. The checker first extracts declaration values, then compares supporting document values after semantic normalization. Missing extended report fields are displayed as risks in the report without breaking legacy core-field audits.

## Report Renderer

The formal report sections are:

1. 文件完整度與單號
2. 船名航次
3. 港口
4. 結關日
5. 件數
6. 重量
7. 金額
8. 單價
9. 運費保費
10. 匯率
11. 稅則
12. 統計方式
13. 買賣方與 Incoterm
14. 風險提醒
15. 最後結論

Every section includes document values, declaration values, AI judgment, consistency status, validation process, plain-language explanation and risk reminder.

## Release Compatibility

No updater or release pipeline behavior was changed. The audit engine is integrated behind the existing workflow and report boundaries.
