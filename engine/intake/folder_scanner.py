from __future__ import annotations

from pathlib import Path


SUPPORTED_INTAKE_SUFFIXES = {
    ".pdf",
    ".xlsx",
    ".csv",
    ".tsv",
    ".txt",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
}


class FolderScanner:
    def __init__(self, supported_suffixes: set[str] | None = None) -> None:
        self.supported_suffixes = {suffix.lower() for suffix in (supported_suffixes or SUPPORTED_INTAKE_SUFFIXES)}

    def scan(self, folder: str | Path, recursive: bool = True) -> list[Path]:
        root = Path(folder)
        if not root.exists():
            raise FileNotFoundError(f"intake folder does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"intake path is not a folder: {root}")

        iterator = root.rglob("*") if recursive else root.glob("*")
        files = [
            path
            for path in iterator
            if path.is_file() and path.suffix.lower() in self.supported_suffixes and not path.name.startswith("~$")
        ]
        return sorted(files, key=lambda path: str(path).casefold())
