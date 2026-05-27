# TongYang Customs Platform v1.1.6

Production deployment finalization and single EXE runtime layout.

- Installs the running production EXE into `%LOCALAPPDATA%/TongYangCustomsPlatform/TongYangCustomsPlatform.exe`.
- Repairs Desktop and Start Menu shortcuts so users always launch the production EXE.
- Cleans stale updater cache, temp EXE files, pending manifests, and dirty updater state during startup and updater reset.
- Keeps updater replacement focused on the single production EXE target.
- Runs shortcut repair and update helper processes without console windows.
- Preserves production OCR packaging, SHA-first update compare, background update checks, and ERP drag/drop workflow.
