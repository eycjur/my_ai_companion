"""長期記憶の永続化 — profile.txt + episodic.db。"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..logging_conf import get_logger

logger = get_logger("memory.store")

_EPISODIC_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    summary TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    summary,
    tokenize='trigram'
);
"""


@dataclass
class SessionSummary:
    started_at: str
    summary: str


def profile_path(memory_dir: Path) -> Path:
    return memory_dir / "profile.txt"


def episodic_path(memory_dir: Path) -> Path:
    return memory_dir / "episodic.db"


def load_profile(memory_dir: Path) -> str:
    path = profile_path(memory_dir)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def save_profile(memory_dir: Path, text: str) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    path = profile_path(memory_dir)
    tmp = path.with_suffix(".txt.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _connect_episodic(memory_dir: Path) -> sqlite3.Connection:
    memory_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(episodic_path(memory_dir))
    conn.row_factory = sqlite3.Row
    conn.executescript(_EPISODIC_SCHEMA)
    return conn


def insert_session(
    memory_dir: Path,
    *,
    session_id: str,
    started_at: str,
    ended_at: str,
    summary: str,
) -> None:
    with _connect_episodic(memory_dir) as conn:
        cur = conn.execute(
            """
            INSERT INTO sessions (id, started_at, ended_at, summary)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, started_at, ended_at, summary),
        )
        rowid = cur.lastrowid
        conn.execute(
            "INSERT INTO memory_fts(rowid, summary) VALUES (?, ?)",
            (rowid, summary),
        )
        conn.commit()
    logger.info("セッションを保存: %s", session_id)


def recent_summaries(memory_dir: Path, limit: int = 3) -> list[SessionSummary]:
    with _connect_episodic(memory_dir) as conn:
        rows = conn.execute(
            """
            SELECT started_at, summary FROM sessions
            ORDER BY started_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        SessionSummary(started_at=row["started_at"], summary=row["summary"])
        for row in rows
    ]


def _format_date(iso: str) -> str:
    return iso[:10] if len(iso) >= 10 else iso


def _build_fts_query(terms: list[str]) -> str | None:
    """trigram は 3 文字未満の語単独ではヒットしないため、短い語は結合する。"""
    long_terms = [t for t in terms if len(t) >= 3]
    if long_terms:
        return " OR ".join(long_terms)
    combined = "".join(terms)
    return combined if len(combined) >= 3 else None


def search_sessions(memory_dir: Path, query: str, limit: int = 5) -> list[str]:
    """summary を FTS5 キーワード検索する。"""
    terms = [t.strip() for t in query.split() if t.strip()]
    if not terms:
        return []

    fts_query = _build_fts_query(terms)
    if fts_query is None:
        return []

    with _connect_episodic(memory_dir) as conn:
        rows = conn.execute(
            """
            SELECT s.started_at, s.summary
            FROM memory_fts f
            JOIN sessions s ON f.rowid = s.rowid
            WHERE memory_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()

    return [f"{_format_date(r['started_at'])}: {r['summary']}" for r in rows]


def session_id_from_started_at(started_at: str) -> str:
    """started_at からセッション ID を生成（ファイル名安全）。"""
    return started_at.replace(":", "").replace("+", "").replace(".", "")


class SQLiteMemoryStore:
    """MemoryStorePort の具象実装。モジュールレベル関数をクラスでラップする。"""

    def __init__(self, memory_dir: Path) -> None:
        self._dir = memory_dir

    @property
    def memory_dir(self) -> Path:
        return self._dir

    def ensure_initialized(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        if not profile_path(self._dir).exists():
            save_profile(self._dir, "")

    def load_profile(self) -> str:
        return load_profile(self._dir)

    def save_profile(self, text: str) -> None:
        save_profile(self._dir, text)

    def recent_summaries(self, limit: int = 3) -> list[SessionSummary]:
        return recent_summaries(self._dir, limit=limit)

    def search(self, query: str, limit: int = 5) -> list[str]:
        return search_sessions(self._dir, query, limit=limit)

    def insert_session(
        self,
        session_id: str,
        started_at: str,
        ended_at: str,
        summary: str,
    ) -> None:
        insert_session(
            self._dir,
            session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            summary=summary,
        )
