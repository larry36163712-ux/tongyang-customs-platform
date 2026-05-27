# v1.1.9 Production ERP Desktop Release

## Highlights

- Reworked the AI Customs Audit Workspace into a production ERP layout: 30% case documents, 70% audit workspace, larger evidence table, clearer typography, and reduced nested scrollbars.
- Strengthened semantic document understanding with layout, customs vocabulary, table structure, shipping terms, trade-document fingerprinting, and OCR similarity scoring.
- Added D/O as a first-class document type and expanded dynamic evidence columns for Arrival Notice, D/O, SO/Booking, DS2, tax sheet, clearance list, and drawback documents.
- Hardened DS2 handling so uploaded low-confidence declaration candidates are shown as manual-confirmation items instead of hard missing documents.
- Added production installer bootstrapper for Program Files installation, desktop/start menu shortcut repair, and setup-based update migration.
- Added VERSIONINFO metadata for ProductName, CompanyName, FileDescription, and product/file version.

## Release Assets

- `TongYangCustomsPlatform_Setup.exe`
- `version.json`
- `SHA256.txt`

The release manifest keeps `app_sha256` for app-level SHA-first comparison and `package_sha256` for setup download verification.
