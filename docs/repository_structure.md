# Repository Structure

This repository is the formal AI Customs ERP project. Prototype build files, legacy Tkinter packaging files, temporary release worktrees, and generated build outputs are not part of the maintained source tree.

## Core Directories

### `app/`

Legacy-compatible application modules that still provide shared business utilities, historical checker logic, runtime helpers, and parser support. Keep this directory because current code and compatibility paths still reference it.

### `v2/`

Primary AI Customs ERP application.

- `v2/main.py`: PySide6 application entry point.
- `v2/ui/`: formal workflow UI.
- `v2/workflow/`: document intake, split, parser execution, case grouping, and workflow result models.
- `v2/parsers/`: document parser registry and concrete parsers.
- `v2/audit/`: declaration/document audit orchestration.
- `v2/rules/`: rule engine boundary.
- `v2/core/`: settings, updater, declaration checking, document loading, template learning, and shared V2 services.
- `v2/ocr/`: OCR boundary.

### `config/`

Runtime and release configuration.

- `config/version.json`: canonical local version manifest.
- `config/v2_settings.json`: V2 runtime/update settings.
- `config/rules/`: layered customs rule configuration.
- `config/customs_rules.json`: deprecated flat-rule pointer; retained only to prevent older callers from treating legacy flat rules as global rules.

### `docs/`

Architecture, release, and repository documentation.

- `AI_CONTRACT.md`: AI/audit/rule-engine constraints.
- `ARCHITECTURE.md`: layered system and rule architecture.
- `docs/release-github.md`: GitHub release asset naming and pipeline contract.
- `docs/repository_structure.md`: this repository layout guide.

### `scripts/`

Maintained automation and verification scripts.

- `make_release_manifest.py`: creates GitHub release `version.json`.
- `upload_release_asset.ps1`: uploads release assets with enforced executable asset naming.
- `check_github_release_auth.ps1`: checks local Git/GitHub CLI authentication and repository access for release publishing.
- `test_v2_document_workflow.py`: workflow engine regression test.
- `test_v2_declaration_workflow.py`: declaration workflow regression test.
- `test_v2_updater_version_source.py`: version-source/update status regression test.
- `test_v2_updater_workflow.py`: updater replacement workflow regression test.

### `templates/`

Runtime template storage seed directory.

## Build Pipeline

Formal build files:

- `AI_Customs_ERP_V2.spec`
- `build_v2_exe.ps1`
- `build_dev_release.ps1`

`build_v2_exe.ps1` builds the V2 PySide6 executable from `v2/main.py`.

`build_dev_release.ps1` coordinates DEV release preparation: version sync, tests, build, manifest/SHA generation, commit/push, prerelease creation, and asset upload.

The GitHub release executable asset name is always:

`TongYangCustomsPlatform.exe`

The local built executable may remain:

`通洋報關平台.exe`

This separation avoids GitHub Release asset filename issues without changing UI text, product name, or window title.

## Release Pipeline

`.github/workflows/release.yml` is the maintained DEV/STABLE release workflow.

DEV releases:

- require a `-dev` version
- are prereleases
- do not depend on GitHub `/releases/latest`
- verify tag-specific release assets and download URLs
- upload `TongYangCustomsPlatform.exe`, `version.json`, and `SHA256.txt`

Stable releases:

- must not use `-dev`
- are separate from DEV releases
- are normal GitHub releases
- may be marked latest and verified through `/releases/latest`

## Parser Architecture

Parser responsibilities:

1. Classify document type.
2. Extract structured fields.
3. Provide parser confidence and debug metadata.
4. Provide evidence for workflow grouping and rule activation.

Parsers do not decide business-rule applicability. They feed case context into audit and rule layers.

## Workflow Architecture

Workflow flow:

1. Intake files.
2. OCR or text extraction.
3. Split documents into segments.
4. Detect document type.
5. Parse fields.
6. Group segments into case workflows.
7. Audit declaration/source document differences.
8. Apply configured rule engine findings.
9. Render workflow UI view models.

## Removed Deprecated Source

The formal repository excludes:

- old Tkinter build script
- old Tkinter PyInstaller spec
- root prototype entry point
- old PyInstaller Tkinter runtime hooks
- temporary release clone worktrees
- generated build outputs
