"""SQLite storage layer with FTS5 for agentmemory-sr."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import (
    Grade,
    GradeEvent,
    HealthReport,
    Memory,
    MemoryState,
    ReviewResult,
)

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT 'general',
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    -- FSRS scheduling state
    stability REAL,
    difficulty REAL,
    due TEXT NOT NULL,
    last_review TEXT,
    state TEXT NOT NULL DEFAULT 'new',
    step INTEGER DEFAULT 0,
    fsrs_card_id INTEGER,

    -- Agent tracking
    lapses INTEGER NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0,
    retrieval_count INTEGER NOT NULL DEFAULT 0,
    usage_count INTEGER NOT NULL DEFAULT 0,
    last_retrieved TEXT,
    last_used TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    namespace,
    content=memories,
    content_rowid=rowid
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, namespace)
    VALUES (new.rowid, new.content, new.namespace);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, namespace)
    VALUES ('delete', old.rowid, old.content, old.namespace);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF content, namespace ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, namespace)
    VALUES ('delete', old.rowid, old.content, old.namespace);
    INSERT INTO memories_fts(rowid, content, namespace)
    VALUES (new.rowid, new.content, new.namespace);
END;

CREATE TABLE IF NOT EXISTS grade_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL REFERENCES memories(id),
    grade TEXT NOT NULL,
    graded_at TEXT NOT NULL,
    context TEXT
);

CREATE TABLE IF NOT EXISTS review_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL REFERENCES memories(id),
    grade TEXT NOT NULL,
    stability_before REAL,
    stability_after REAL,
    difficulty_before REAL,
    difficulty_after REAL,
    state_before TEXT NOT NULL,
    state_after TEXT NOT NULL,
    reviewed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_state ON memories(state);
CREATE INDEX IF NOT EXISTS idx_memories_due ON memories(due);
CREATE INDEX IF NOT EXISTS idx_memories_namespace ON memories(namespace);
CREATE INDEX IF NOT EXISTS idx_grade_history_memory ON grade_history(memory_id);
CREATE INDEX IF NOT EXISTS idx_review_log_memory ON review_log(memory_id);
"""


class MemoryDB:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # --- Memory CRUD ---

    def insert_memory(self, memory: Memory) -> Memory:
        if not memory.id:
            memory.id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO memories
            (id, content, namespace, source, created_at, updated_at,
             stability, difficulty, due, last_review, state, step, fsrs_card_id,
             lapses, reps, retrieval_count, usage_count, last_retrieved, last_used)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory.id,
                memory.content,
                memory.namespace,
                memory.source,
                memory.created_at.isoformat(),
                now,
                memory.stability,
                memory.difficulty,
                memory.due.isoformat(),
                memory.last_review.isoformat() if memory.last_review else None,
                memory.state.value,
                memory.step,
                memory.fsrs_card_id,
                memory.lapses,
                memory.reps,
                memory.retrieval_count,
                memory.usage_count,
                memory.last_retrieved.isoformat() if memory.last_retrieved else None,
                memory.last_used.isoformat() if memory.last_used else None,
            ),
        )
        self.conn.commit()
        return memory

    def update_memory(self, memory: Memory):
        self.conn.execute(
            """UPDATE memories SET
            content=?, namespace=?, source=?, updated_at=?,
            stability=?, difficulty=?, due=?, last_review=?, state=?, step=?, fsrs_card_id=?,
            lapses=?, reps=?, retrieval_count=?, usage_count=?, last_retrieved=?, last_used=?
            WHERE id=?""",
            (
                memory.content,
                memory.namespace,
                memory.source,
                memory.updated_at.isoformat(),
                memory.stability,
                memory.difficulty,
                memory.due.isoformat(),
                memory.last_review.isoformat() if memory.last_review else None,
                memory.state.value,
                memory.step,
                memory.fsrs_card_id,
                memory.lapses,
                memory.reps,
                memory.retrieval_count,
                memory.usage_count,
                memory.last_retrieved.isoformat() if memory.last_retrieved else None,
                memory.last_used.isoformat() if memory.last_used else None,
                memory.id,
            ),
        )
        self.conn.commit()

    def get_memory(self, memory_id: str) -> Optional[Memory]:
        row = self.conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_memory(row)

    def delete_memory(self, memory_id: str):
        self.conn.execute("DELETE FROM grade_history WHERE memory_id=?", (memory_id,))
        self.conn.execute("DELETE FROM review_log WHERE memory_id=?", (memory_id,))
        self.conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        self.conn.commit()

    # --- Search ---

    def search_fts(self, query: str, namespace: Optional[str] = None, limit: int = 20) -> list[tuple[str, float]]:
        """FTS5 search. Returns list of (memory_id, bm25_rank).

        Converts the query to OR-based terms for fuzzy matching.
        FTS5 rank is negative (lower = better match).
        """
        # Build an OR query from individual terms for broader matching
        terms = [w.strip() for w in query.split() if len(w.strip()) > 1]
        if not terms:
            return []
        fts_query = " OR ".join(f'"{t}"' for t in terms)

        try:
            if namespace:
                rows = self.conn.execute(
                    """SELECT m.id, rank FROM memories_fts
                    JOIN memories m ON memories_fts.rowid = m.rowid
                    WHERE memories_fts MATCH ? AND m.namespace = ?
                    AND m.state NOT IN ('suspended', 'buried')
                    ORDER BY rank
                    LIMIT ?""",
                    (fts_query, namespace, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    """SELECT m.id, rank FROM memories_fts
                    JOIN memories m ON memories_fts.rowid = m.rowid
                    WHERE memories_fts MATCH ?
                    AND m.state NOT IN ('suspended', 'buried')
                    ORDER BY rank
                    LIMIT ?""",
                    (fts_query, limit),
                ).fetchall()
        except sqlite3.OperationalError:
            return []

        return [(row["id"], row["rank"]) for row in rows]

    def find_similar(self, content: str, namespace: str, exclude_id: Optional[str] = None, limit: int = 5) -> list[Memory]:
        """Find memories with similar content in the same namespace using FTS5."""
        # Extract key terms for matching
        terms = " OR ".join(w for w in content.lower().split() if len(w) > 3)
        if not terms:
            return []
        try:
            rows = self.conn.execute(
                """SELECT m.* FROM memories_fts
                JOIN memories m ON memories_fts.rowid = m.rowid
                WHERE memories_fts MATCH ? AND m.namespace = ?
                AND m.state NOT IN ('suspended', 'buried')
                ORDER BY rank LIMIT ?""",
                (terms, namespace, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        results = []
        for row in rows:
            mem = self._row_to_memory(row)
            if exclude_id and mem.id == exclude_id:
                continue
            results.append(mem)
        return results

    # --- Due memories ---

    def get_due_memories(self, now: Optional[datetime] = None) -> list[Memory]:
        if now is None:
            now = datetime.now(timezone.utc)
        rows = self.conn.execute(
            """SELECT * FROM memories
            WHERE due <= ? AND state NOT IN ('suspended', 'buried')
            ORDER BY due ASC""",
            (now.isoformat(),),
        ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def get_all_active_memories(self) -> list[Memory]:
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE state NOT IN ('suspended', 'buried') ORDER BY updated_at DESC"
        ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    # --- Grade history ---

    def log_grade(self, event: GradeEvent):
        self.conn.execute(
            "INSERT INTO grade_history (memory_id, grade, graded_at, context) VALUES (?, ?, ?, ?)",
            (event.memory_id, event.grade.value, event.graded_at.isoformat(), event.context),
        )
        self.conn.commit()

    def log_review(self, result: ReviewResult):
        self.conn.execute(
            """INSERT INTO review_log
            (memory_id, grade, stability_before, stability_after,
             difficulty_before, difficulty_after, state_before, state_after, reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result.memory_id,
                result.grade.value,
                result.stability_before,
                result.stability_after,
                result.difficulty_before,
                result.difficulty_after,
                result.state_before.value,
                result.state_after.value,
                result.reviewed_at.isoformat(),
            ),
        )
        self.conn.commit()

    # --- Health stats ---

    def get_health_stats(self, now: Optional[datetime] = None) -> dict:
        if now is None:
            now = datetime.now(timezone.utc)

        total = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

        state_counts = {}
        for row in self.conn.execute("SELECT state, COUNT(*) as cnt FROM memories GROUP BY state"):
            state_counts[row["state"]] = row["cnt"]

        leeches = self.conn.execute(
            "SELECT COUNT(*) FROM memories WHERE state = 'suspended' AND lapses >= 8"
        ).fetchone()[0]

        due_now = self.conn.execute(
            "SELECT COUNT(*) FROM memories WHERE due <= ? AND state NOT IN ('suspended', 'buried')",
            (now.isoformat(),),
        ).fetchone()[0]

        avg_row = self.conn.execute(
            "SELECT AVG(stability) as avg_s, AVG(difficulty) as avg_d FROM memories WHERE stability IS NOT NULL"
        ).fetchone()

        ns_counts = {}
        for row in self.conn.execute("SELECT namespace, COUNT(*) as cnt FROM memories GROUP BY namespace"):
            ns_counts[row["namespace"]] = row["cnt"]

        return {
            "total": total,
            "by_state": state_counts,
            "leeches": leeches,
            "due_now": due_now,
            "avg_stability": avg_row["avg_s"],
            "avg_difficulty": avg_row["avg_d"],
            "namespaces": ns_counts,
        }

    # --- Helpers ---

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"],
            content=row["content"],
            namespace=row["namespace"],
            source=row["source"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            stability=row["stability"],
            difficulty=row["difficulty"],
            due=datetime.fromisoformat(row["due"]),
            last_review=datetime.fromisoformat(row["last_review"]) if row["last_review"] else None,
            state=MemoryState(row["state"]),
            step=row["step"],
            fsrs_card_id=row["fsrs_card_id"],
            lapses=row["lapses"],
            reps=row["reps"],
            retrieval_count=row["retrieval_count"],
            usage_count=row["usage_count"],
            last_retrieved=datetime.fromisoformat(row["last_retrieved"]) if row["last_retrieved"] else None,
            last_used=datetime.fromisoformat(row["last_used"]) if row["last_used"] else None,
        )
