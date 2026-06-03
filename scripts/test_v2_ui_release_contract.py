from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v2.ui.main_window import CustomsErpWindow  # noqa: E402


FORBIDDEN_VISIBLE_WORDS = (
    "WARNING_GLOBAL",
    "COMPARE_COMMON_FIELDS",
    "declaration_core",
    "traceback",
    "RuntimeError",
)


def main() -> None:
    class DummyWindow:
        _human_document_name = CustomsErpWindow._human_document_name
        _humanize_warning = CustomsErpWindow._humanize_warning
        _human_workflow_message = CustomsErpWindow._human_workflow_message
        _format_workflow_failure = CustomsErpWindow._format_workflow_failure

    window = DummyWindow()
    window.settings = SimpleNamespace(developer_mode=False)

    for raw in (
        "WARNING_GLOBAL_DECLARATION_IS_CORE",
        "WARNING_GLOBAL_COMPARE_COMMON_FIELDS",
        "COMPARE_COMMON_FIELDS",
        "traceback RuntimeError parser failed",
    ):
        text = window._humanize_warning(raw)
        lowered = text.casefold()
        for forbidden in FORBIDDEN_VISIBLE_WORDS:
            if forbidden.casefold() in lowered:
                raise RuntimeError(f"formal UI warning leaked developer wording: {forbidden} -> {text}")

    failure = window._format_workflow_failure(
        "Document Split",
        "RuntimeError: parser failed with traceback",
        "Traceback (most recent call last): ...",
    )
    lowered_failure = failure.casefold()
    for forbidden in FORBIDDEN_VISIBLE_WORDS:
        if forbidden.casefold() in lowered_failure:
            raise RuntimeError(f"formal workflow failure leaked developer wording: {forbidden}")
    if "runtime.log" in lowered_failure:
        raise RuntimeError("formal workflow failure should not show log path unless developer mode is enabled")

    window.settings = SimpleNamespace(developer_mode=True)
    debug_failure = window._format_workflow_failure("Document Split", "RuntimeError", "Traceback")
    if "runtime.log" not in debug_failure.casefold() or "Traceback" not in debug_failure:
        raise RuntimeError("developer mode should preserve runtime log and exception details")

    print("ui release contract ok")


if __name__ == "__main__":
    main()
