from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from v2.core.settings import app_base_dir


@dataclass(frozen=True)
class AuditFeedback:
    case_id: str
    source_file: str
    predicted_result: str
    corrected_result: str = ""
    error_type: str = ""
    note: str = ""
    is_correct: bool = False
    created_at: str = ""


@dataclass(frozen=True)
class AuditFeedbackRecord(AuditFeedback):
    id: int = 0


@dataclass(frozen=True)
class FeedbackStatistics:
    total: int
    correct_count: int
    issue_count: int
    error_counts: dict[str, int]


class AuditFeedbackEngine:
    """Persist customs audit reviewer feedback for later QA and tuning."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or app_base_dir() / "database" / "feedback.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def record(self, feedback: AuditFeedback) -> int:
        created_at = feedback.created_at or datetime.now().isoformat(timespec="seconds")
        error_type = feedback.error_type.strip() or ("正確" if feedback.is_correct else "其他")
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO audit_feedback (
                    created_at,
                    case_id,
                    source_file,
                    predicted_result,
                    corrected_result,
                    error_type,
                    is_correct,
                    note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    feedback.case_id.strip(),
                    feedback.source_file.strip(),
                    feedback.predicted_result.strip(),
                    feedback.corrected_result.strip(),
                    error_type,
                    1 if feedback.is_correct else 0,
                    feedback.note.strip(),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def recent(self, limit: int = 100) -> list[AuditFeedbackRecord]:
        safe_limit = max(1, min(int(limit), 1000))
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT
                    id,
                    created_at,
                    case_id,
                    source_file,
                    predicted_result,
                    corrected_result,
                    error_type,
                    is_correct,
                    note
                FROM audit_feedback
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        finally:
            conn.close()
        return [
            AuditFeedbackRecord(
                id=int(row["id"]),
                created_at=str(row["created_at"] or ""),
                case_id=str(row["case_id"] or ""),
                source_file=str(row["source_file"] or ""),
                predicted_result=str(row["predicted_result"] or ""),
                corrected_result=str(row["corrected_result"] or ""),
                error_type=str(row["error_type"] or ""),
                is_correct=bool(row["is_correct"]),
                note=str(row["note"] or ""),
            )
            for row in rows
        ]

    def statistics(self, limit: int = 100) -> FeedbackStatistics:
        records = self.recent(limit)
        correct_count = sum(1 for record in records if record.is_correct)
        issue_records = [record for record in records if not record.is_correct]
        counts = Counter(record.error_type or "其他" for record in issue_records)
        return FeedbackStatistics(
            total=len(records),
            correct_count=correct_count,
            issue_count=len(issue_records),
            error_counts=dict(counts.most_common()),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    source_file TEXT NOT NULL DEFAULT '',
                    predicted_result TEXT NOT NULL DEFAULT '',
                    corrected_result TEXT NOT NULL DEFAULT '',
                    error_type TEXT NOT NULL DEFAULT '',
                    is_correct INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_feedback_created_at ON audit_feedback(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_feedback_case_id ON audit_feedback(case_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_feedback_error_type ON audit_feedback(error_type)"
            )
            conn.commit()
        finally:
            conn.close()
