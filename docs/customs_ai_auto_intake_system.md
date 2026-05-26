# Customs AI Auto Intake System

## System Architecture

`Customs AI Intake Engine` is integrated into TongYang Customs Platform through `DocumentWorkflowEngine.process_folder()`.

Core components:

- `engine.intake.FolderWatcher`: polling watcher for production intake folders.
- `engine.intake.FolderScanner`: recursive scanner for supported customs files.
- `v2.workflow.intake.FileIntakeEngine`: multi-format text extraction and OCR boundary.
- `engine.intake.DocumentClassifier`: content-first customs document classification.
- `engine.intake.ShipmentGrouper`: semantic shipment grouping by shipment identifiers.
- `v2.workflow.matcher.WorkflowMatcher`: workflow/case matching.
- `v2.core.parser_engine.SemanticParserEngine`: multi-format semantic field parsing.
- `v2.audit.CustomsAuditEngine`: declaration/document cross-checking.
- `engine.report.AuditReportEngine`: formal human customs audit report generation.

## Intake Pipeline

1. User drops all documents into one folder.
2. Folder scanner reads supported files: PDF, XLSX, CSV, TXT, JPG, PNG, TIFF.
3. File intake extracts text or runs OCR when needed.
4. Content classifier identifies INV, PACKING LIST, SO, B/L, declarations, clearance lists, drawback standards, tax sheets, and scanned images.
5. Shipment grouper links files by BL NO, INV NO, Booking NO, container number, vessel/voyage, company names, and shared shipment context.
6. Workflow matcher creates `CaseWorkflow` records.
7. Audit engine cross-checks declaration values against supporting documents.
8. Report engine renders a formal `AI Customs Audit Report`.

## OCR Pipeline

PDF files first use embedded text extraction through `pypdf`. Scanned PDF pages fall back to PyMuPDF rendering and Tesseract OCR. Image files use Pillow plus Tesseract with `eng+chi_tra`.

When OCR dependencies or the Tesseract runtime are unavailable, the engine returns a structured operational error instead of silently treating an OCR document as empty.

## Shipment Grouping Logic

Grouping does not use fixed filenames. It links documents by normalized identifiers and semantic context:

- BL NO
- INV NO
- Booking NO / S/O NO
- Container NO
- Vessel / Voyage
- Consignee / shipper / company context

If one intake folder has no conflicting shipment keys and no duplicate high-signal document types, the system creates one pending-review shipment rather than dropping documents.

## Customs Audit Engine

The audit engine cross-checks:

- INV vs declaration
- PACKING LIST vs declaration
- SO / Booking vs declaration
- B/L vs declaration
- Clearance list vs drawback/tax/declaration fields

Extended fields such as CIF, FOB, freight, insurance, exchange rate, duty amount, closing date, and statistical method are included in the formal report. Missing extended fields are surfaced as report risks without breaking legacy core-field match behavior.

## AI Semantic Matching

The semantic parser maps English and Traditional Chinese labels into canonical customs fields. Identifier extraction covers invoice numbers, B/L numbers, booking numbers, container numbers, seal numbers, incoterms, exchange rates, HS codes, duty, CIF, FOB, freight, and insurance.

## Parser Strategy

Parsing is content-first and format-independent:

- PDF: embedded text, then OCR fallback for scanned pages.
- XLSX: OpenXML worksheet/shared string extraction.
- CSV/TSV: structured delimiter extraction.
- TXT: UTF-8 / CP950 / Big5 fallback decoding.
- JPG/PNG/TIFF: OCR.

## UI Redesign

The formal workflow view now presents:

- Left side: document and workflow status, missing documents, risk reminders.
- Right side: complete customs-broker style audit report.

Engineering debug panels, parser confidence tables, and workflow trees are not part of the formal intake surface.

## Release Compatibility

The updater and GitHub release pipeline remain unchanged in behavior. Runtime OCR dependencies are declared in `requirements.txt`, build dependencies are mirrored in `requirements-build.txt`, and PyInstaller hidden imports were added for Pillow, pytesseract, and PyMuPDF.
