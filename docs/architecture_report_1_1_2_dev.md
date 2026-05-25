# AI Customs ERP Architecture Report - 1.1.2-dev Baseline

## Scope

This report records the first safe architecture refactor after the
`baseline-1.1.2-dev` tag. The goal is to move the project from a parser-centric
shape toward workflow-centric, rule-centric, and audit-centric architecture
without breaking the current executable, UI, OCR boundary, compare table,
updater, or release workflow.

## Current Architecture Inventory

### Active V2 Application

- `v2/main.py` starts the PySide6 ERP UI.
- `v2/ui/main_window.py` owns the operational UI, upload flow, workflow display,
  compare table, debug panel, and update controls.
- `v2/workflow/` owns intake, document splitting, grouping, cache, and workflow
  orchestration.
- `v2/parsers/` owns parser registry and document-specific parser contracts.
- `v2/core/parser_engine.py` and `v2/core/checking.py` own semantic parsing and
  declaration compare behavior.
- `v2/audit/` owns case audit and human audit summary behavior.
- `v2/rules/` owns config-driven rule execution against workflow cases.
- `v2/ocr/` owns the OCR boundary.

### Legacy / Compatibility Code

- `app/parser/`, `app/shared/`, `app/import_checker/`, and
  `app/export_checker/` contain legacy parser/checker behavior and useful
  customs-domain logic.
- `app/updater.py` and `app/runtime.py` remain compatibility code for the older
  application path.
- `config/settings.json` and root `settings.json` remain legacy settings.

### Build And Release

- `AI_Customs_ERP_V2.spec` is the active PyInstaller spec.
- `build_v2_exe.ps1` builds the local V2 executable.
- `build_dev_release.ps1` performs DEV release packaging and upload.
- `.github/workflows/release.yml` owns GitHub Actions release lifecycle.
- `scripts/release_manager.ps1` owns DEV overwrite, asset upload, latest
  verification, and old DEV release cleanup.

## First-Stage Refactor

### Rule Engine Boundary

Added `engine/rules/`:

- `rule_loader.py` loads modular rule files from `config/rules/`.
- `condition_matcher.py` evaluates `applies_when` conditions.
- `rule_executor.py` exposes a formal Rule Executor facade over active
  `v2.rules.RuleEngine`.

Rule config remains in:

- `config/rules/global_rules.json`
- `config/rules/company_rules.json`
- `config/rules/customer_rules.json`
- `config/rules/route_rules.json`
- `config/rules/case_rules.json`
- `config/rules/document_rules.json`
- `config/rules/rate_tables.json`

### Workflow Engine Boundary

Added `engine/workflow/`:

- `grouping_engine.py` wraps active V2 workflow grouping.
- `relationship_engine.py` extracts document-to-case relationships.
- `confidence_engine.py` evaluates parser confidence at case level.
- `workflow_state_machine.py` maps cases into formal workflow states.

Formal states:

- `WAITING_BL`
- `WAITING_DECLARATION`
- `PARTIAL_WORKFLOW`
- `LOW_CONFIDENCE`
- `PENDING_MATCH`
- `READY_FOR_AUDIT`
- `AUDIT_COMPLETED`
- `NEEDS_HUMAN_REVIEW`

The active `DocumentWorkflowEngine` now writes `case.workflow_state` while
preserving the older `CaseStatus` for UI compatibility.

### Audit Summary Boundary

Added `engine/audit/`:

- `audit_summary_engine.py` wraps active V2 AI audit summary generation.
- `compare_formatter.py` converts raw compare results into human-readable rows.
- `human_readable_summary.py` renders customs-broker-facing summary text.

## Reusable Existing Capabilities

- PDF/text intake and document splitting.
- Parser registry and semantic parser layer.
- Booking/SO parser.
- DS2/document compare via `DeclarationDocumentChecker`.
- Case grouping by invoice, B/L, booking, SO, container, vessel/voyage.
- Rule config loading and rule finding generation.
- AI audit summary data model.
- DEV updater behavior and version source handling.
- DEV release asset verification and latest download URL validation.

## Compatibility Notes

- Existing UI imports and V2 build entry remain unchanged.
- Existing parser contracts remain unchanged.
- Existing updater URL rule remains `/releases/latest/download/version.json`.
- Existing local dist executable remains `通洋報關平台.exe`.
- GitHub release asset remains `TongYangCustomsPlatform.exe`.
- The new `engine/` package is additive and wraps active V2 implementation.

## Known Risks

- Legacy `app/` modules still contain useful customs-domain behavior and must
  be migrated gradually.
- OCR runtime dependencies may be unavailable on some machines.
- Some customs rules are currently review hints or calculations; semantic rule
  intelligence should be expanded behind the new rule boundary.
- The UI still displays legacy `CaseStatus` in places and should gradually move
  to `workflow_state` for broker-facing status.

## Next Refactor Order

1. Route UI case status display to formal `workflow_state`.
2. Move legacy freight/insurance logic behind `engine/rules/`.
3. Add semantic comparison services behind the compare formatter.
4. Add risk scoring output to audit summary.
5. Add tax and import regulation engines behind stable interfaces.
6. Migrate legacy `app/` checker behavior only after test coverage exists.
