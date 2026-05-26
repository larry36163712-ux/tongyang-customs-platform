# Production Runtime / EXE Runtime Environment

## EXE Runtime Architecture

The packaged app starts at `v2/main.py`, calls `multiprocessing.freeze_support()`, installs a global exception hook, and writes startup diagnostics to `logs/runtime.log`.

Runtime resource lookup uses two roots:

- writable runtime root: the EXE directory
- bundled read-only root: `sys._MEIPASS` when running from PyInstaller one-file mode

Config and rule loading first checks the EXE directory, then falls back to bundled resources.

## OCR Runtime Flow

1. Workflow startup initializes `FileIntakeEngine`.
2. `OcrEngine.is_available()` logs OCR startup status.
3. Image files and scanned PDF pages call Tesseract through `pytesseract`.
4. If Python OCR modules are missing, the UI receives the module/import error.
5. If Tesseract is missing, the UI receives: `未安裝 OCR runtime：Tesseract`.
6. Every OCR start, completion, and failure is recorded in `logs/runtime.log`.

## Parser Runtime Flow

The parser registry logs each parser candidate:

- parser support checks
- parser start
- parser completion
- parser crash with parser name, source file, and traceback

This makes packaged EXE parser failures visible instead of leaving the UI in a waiting state.

## Worker Threading Model

The UI runs workflow work inside `WorkflowRunWorker`, which owns a backend Python thread and a queue. The worker thread reports progress by stage:

- Upload
- OCR
- Document Split
- parser
- workflow grouping
- audit
- Completed

If a stage stops reporting progress, the watchdog emits a `WorkflowFailure`, records thread status and a Python stack dump, and the UI shows the stage, message, traceback, and runtime log path.

## PyInstaller Packaging

`AI_Customs_ERP_V2.spec` now explicitly bundles:

- `engine/`
- `v2/`
- `templates/`
- `config/`
- parser rules under `config/rules`
- workflow/runtime config files

Hidden imports collect submodules for:

- `engine`
- `v2`
- `PIL`
- `pytesseract`
- `fitz`

## Production Logging

`logs/runtime.log` records:

- application startup and exit
- OCR startup and failures
- parser startup and failures
- workflow grouping
- audit engine initialization and case audit
- exception tracebacks
- missing modules
- missing executables
- timeouts
- worker thread status and stack dumps
