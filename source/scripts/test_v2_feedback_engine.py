from __future__ import annotations

import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v2.audit.feedback import AuditFeedback, AuditFeedbackEngine


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "feedback.db"
        engine = AuditFeedbackEngine(db_path)

        first_id = engine.record(
            AuditFeedback(
                case_id="CASE-001",
                source_file="invoice.pdf、ds2.pdf",
                predicted_result="件數一致；稅則待確認",
                is_correct=True,
            )
        )
        assert first_id == 1

        engine.record(
            AuditFeedback(
                case_id="CASE-002",
                source_file="pl.pdf",
                predicted_result="PL 判定為 B/L",
                corrected_result="文件應為 PL",
                error_type="文件分類錯誤",
                note="Packing table contains carton / gross weight / net weight.",
            )
        )
        engine.record(
            AuditFeedback(
                case_id="CASE-002",
                source_file="pl.pdf",
                predicted_result="PL 判定為 B/L",
                corrected_result="文件應為 PL",
                error_type="DS2 誤判",
                note="Regression guard sample.",
            )
        )

        recent = engine.recent(100)
        assert len(recent) == 3
        assert recent[0].case_id == "CASE-002"
        assert db_path.exists()

        stats = engine.statistics(100)
        assert stats.total == 3
        assert stats.correct_count == 1
        assert stats.issue_count == 2
        assert stats.error_counts["文件分類錯誤"] == 1
        assert stats.error_counts["DS2 誤判"] == 1

        print("feedback engine ok")


if __name__ == "__main__":
    main()
