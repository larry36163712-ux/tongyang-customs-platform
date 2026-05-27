# TongYang Customs Platform v1.1.5

Production Windows desktop app experience and OCR runtime packaging.

- Bundles production OCR/parser dependencies for PyInstaller, including PyMuPDF, pytesseract, pdf2image, Pillow, OpenCV, NumPy, openpyxl, and pandas.
- Keeps startup responsive by moving update checks to a background worker and logging startup timing to runtime logs.
- Adds runtime self-test support for packaged EXE dependency verification.
- Improves scanned PDF/image OCR error handling with clear user-facing messages and full details in logs/runtime.log.
- Expands the ERP import area so files and folders can be dragged onto the full upload panel.
- Keeps updater checks non-blocking and preserves SHA-first release manifest compatibility.
