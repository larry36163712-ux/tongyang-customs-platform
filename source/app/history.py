from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.parser.document import ParsedDocument, UploadedDocument
from app.runtime import app_base_dir
from app.shared.models import CheckReport


def init_history_database() -> Path:
    db_path = app_base_dir() / "database" / "history.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                summary TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS parsed_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_id INTEGER NOT NULL,
                doc_type TEXT NOT NULL,
                source_name TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                error TEXT NOT NULL,
                FOREIGN KEY(check_id) REFERENCES checks(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS check_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                field TEXT NOT NULL,
                message TEXT NOT NULL,
                expected TEXT NOT NULL,
                actual TEXT NOT NULL,
                FOREIGN KEY(check_id) REFERENCES checks(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uploaded_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_id INTEGER NOT NULL,
                doc_type TEXT NOT NULL,
                source_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                FOREIGN KEY(check_id) REFERENCES checks(id)
            )
            """
        )
    return db_path


def save_check_history(
    mode: str,
    documents: dict[str, list[UploadedDocument]],
    parsed_documents: dict[str, list[ParsedDocument]],
    report: CheckReport,
) -> int:
    db_path = init_history_database()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO checks (created_at, mode, summary) VALUES (?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), mode, report.summary),
        )
        check_id = int(cursor.lastrowid)

        for doc_type, docs in documents.items():
            for doc in docs:
                conn.execute(
                    "INSERT INTO uploaded_documents (check_id, doc_type, source_name, stored_name) VALUES (?, ?, ?, ?)",
                    (check_id, doc_type, doc.display_name, Path(doc.stored_path).name),
                )

        for doc_type, docs in parsed_documents.items():
            for parsed in docs:
                conn.execute(
                    """
                    INSERT INTO parsed_results (check_id, doc_type, source_name, fields_json, error)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        check_id,
                        doc_type,
                        parsed.source_name,
                        json.dumps(parsed.fields, ensure_ascii=False, sort_keys=True),
                        parsed.error,
                    ),
                )

        for item in report.items:
            conn.execute(
                """
                INSERT INTO check_items (check_id, status, field, message, expected, actual)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (check_id, item.status, item.field, item.message, item.expected, item.actual),
            )
    return check_id
