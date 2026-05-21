from __future__ import annotations

from dataclasses import dataclass


RELEASE_METHODS = ("C1", "C2", "C3M", "C3X")


@dataclass(frozen=True)
class ImportPrintWorkflow:
    release_method: str
    document_count: int

    def validate(self) -> list[str]:
        warnings: list[str] = []
        if self.release_method not in RELEASE_METHODS:
            warnings.append("放行方式需為 C1、C2、C3M 或 C3X。")
        if self.document_count <= 0:
            warnings.append("請先加入進口文件。")
        return warnings

    def preview_steps(self) -> list[str]:
        return [
            "確認進口文件與放行方式",
            "產生待印清單",
            "等待人工確認",
            "印表機控制尚未啟用",
        ]

