"""The learning memory: a local SQLite database.

Stores every video you processed, every expression / verb / grammar point
extracted from it, the exercises for each item, the spaced-repetition state,
and a log of everything you did (so the daily report can tell you what you
watched and learned).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .srs import SrsState

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    language    TEXT NOT NULL,
    transcript  TEXT NOT NULL,
    lesson_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY,
    video_id      INTEGER NOT NULL REFERENCES videos(id),
    kind          TEXT NOT NULL CHECK (kind IN ('expression', 'verb', 'grammar')),
    language      TEXT NOT NULL,
    text          TEXT NOT NULL,
    meaning_ar    TEXT NOT NULL,
    pronunciation TEXT NOT NULL DEFAULT '',
    example       TEXT NOT NULL DEFAULT '',
    example_ar    TEXT NOT NULL DEFAULT '',
    details_json  TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    UNIQUE (kind, language, text)
);
CREATE INDEX IF NOT EXISTS items_video ON items(video_id);

CREATE TABLE IF NOT EXISTS exercises (
    id       INTEGER PRIMARY KEY,
    item_id  INTEGER NOT NULL REFERENCES items(id),
    type     TEXT NOT NULL,
    prompt   TEXT NOT NULL,
    answer   TEXT NOT NULL,
    hint_ar  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS exercises_item ON exercises(item_id);

CREATE TABLE IF NOT EXISTS srs (
    item_id       INTEGER PRIMARY KEY REFERENCES items(id),
    ease          REAL NOT NULL DEFAULT 2.5,
    interval_days INTEGER NOT NULL DEFAULT 0,
    repetitions   INTEGER NOT NULL DEFAULT 0,
    lapses        INTEGER NOT NULL DEFAULT 0,
    due_date      TEXT,
    first_seen    TEXT,
    mastered_at   TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id           INTEGER PRIMARY KEY,
    item_id      INTEGER NOT NULL REFERENCES items(id),
    exercise_id  INTEGER REFERENCES exercises(id),
    grade        INTEGER NOT NULL,
    correct      INTEGER NOT NULL,
    seconds      REAL NOT NULL DEFAULT 0,
    reviewed_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reviews_day ON reviews(reviewed_at);

CREATE TABLE IF NOT EXISTS activity (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    ref_id     INTEGER,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "daily_new": "10",       # new items to learn per day
    "daily_reviews": "30",   # reviews per day
    "target_mastered": "1000",
    "target_date": "",       # ISO date for the long-term goal
}


def home_dir() -> Path:
    path = Path(os.environ.get("HAYAT_HOME", Path.home() / ".hayat"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = str(path or home_dir() / "hayat.db")
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    # -- settings ---------------------------------------------------------

    def setting(self, key: str) -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else DEFAULT_SETTINGS.get(key, "")

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    # -- videos & items ---------------------------------------------------

    def add_video(self, source: str, title: str, language: str, transcript: str, lesson: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO videos(source, title, language, transcript, lesson_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (source, title, language, transcript, json.dumps(lesson, ensure_ascii=False), now_iso()),
        )
        self.log("video", cur.lastrowid, title)
        self.conn.commit()
        return cur.lastrowid

    def add_item(self, video_id: int, kind: str, language: str, text: str, meaning_ar: str,
                 pronunciation: str = "", example: str = "", example_ar: str = "",
                 details: dict | None = None) -> tuple[int, bool]:
        """Insert an item; returns (item_id, created). Known items are not duplicated."""
        row = self.conn.execute(
            "SELECT id FROM items WHERE kind = ? AND language = ? AND text = ?",
            (kind, language, text),
        ).fetchone()
        if row:
            return row["id"], False
        cur = self.conn.execute(
            "INSERT INTO items(video_id, kind, language, text, meaning_ar, pronunciation, example, "
            "example_ar, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (video_id, kind, language, text, meaning_ar, pronunciation, example, example_ar,
             json.dumps(details or {}, ensure_ascii=False), now_iso()),
        )
        self.conn.execute("INSERT INTO srs(item_id) VALUES (?)", (cur.lastrowid,))
        self.conn.commit()
        return cur.lastrowid, True

    def add_exercise(self, item_id: int, type_: str, prompt: str, answer: str, hint_ar: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO exercises(item_id, type, prompt, answer, hint_ar) VALUES (?, ?, ?, ?, ?)",
            (item_id, type_, prompt, answer, hint_ar),
        )
        self.conn.commit()
        return cur.lastrowid

    def video(self, video_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()

    def videos(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM videos ORDER BY id DESC").fetchall()

    def item(self, item_id: int) -> sqlite3.Row:
        return self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()

    def exercises_for(self, item_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM exercises WHERE item_id = ? ORDER BY id", (item_id,)
        ).fetchall()

    # -- spaced repetition -------------------------------------------------

    def srs_state(self, item_id: int) -> SrsState:
        row = self.conn.execute("SELECT * FROM srs WHERE item_id = ?", (item_id,)).fetchone()
        return SrsState(
            ease=row["ease"],
            interval_days=row["interval_days"],
            repetitions=row["repetitions"],
            lapses=row["lapses"],
            due_date=date.fromisoformat(row["due_date"]) if row["due_date"] else None,
        )

    def record_review(self, item_id: int, exercise_id: int | None, grade: int, correct: bool,
                      new_state: SrsState, seconds: float = 0.0, when: datetime | None = None) -> None:
        when = when or datetime.now()
        stamp = when.isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT INTO reviews(item_id, exercise_id, grade, correct, seconds, reviewed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, exercise_id, grade, int(correct), seconds, stamp),
        )
        self.conn.execute(
            "UPDATE srs SET ease = ?, interval_days = ?, repetitions = ?, lapses = ?, due_date = ?, "
            "first_seen = COALESCE(first_seen, ?), "
            "mastered_at = CASE WHEN ? THEN COALESCE(mastered_at, ?) ELSE NULL END "
            "WHERE item_id = ?",
            (new_state.ease, new_state.interval_days, new_state.repetitions, new_state.lapses,
             new_state.due_date.isoformat() if new_state.due_date else None,
             stamp, int(new_state.mastered), stamp, item_id),
        )
        self.conn.commit()

    def due_items(self, today: date, limit: int) -> list[sqlite3.Row]:
        """Items already started and due today, weakest first."""
        return self.conn.execute(
            "SELECT i.*, s.lapses, s.interval_days FROM items i JOIN srs s ON s.item_id = i.id "
            "WHERE s.first_seen IS NOT NULL AND s.due_date <= ? "
            "ORDER BY s.lapses DESC, s.due_date ASC LIMIT ?",
            (today.isoformat(), limit),
        ).fetchall()

    def new_items(self, limit: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT i.* FROM items i JOIN srs s ON s.item_id = i.id "
            "WHERE s.first_seen IS NULL ORDER BY i.id LIMIT ?",
            (limit,),
        ).fetchall()

    def weak_items(self, limit: int = 10) -> list[sqlite3.Row]:
        """Items you keep getting wrong - the agent's view of your weak spots."""
        return self.conn.execute(
            "SELECT i.*, s.lapses, "
            "SUM(CASE WHEN r.correct = 0 THEN 1 ELSE 0 END) AS wrong, COUNT(r.id) AS total "
            "FROM items i JOIN srs s ON s.item_id = i.id JOIN reviews r ON r.item_id = i.id "
            "GROUP BY i.id HAVING wrong > 0 "
            "ORDER BY (1.0 * wrong / total) DESC, wrong DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def wrong_count_by_type(self, item_id: int) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT e.type, SUM(CASE WHEN r.correct = 0 THEN 1 ELSE 0 END) AS wrong, COUNT(*) AS n "
            "FROM reviews r JOIN exercises e ON e.id = r.exercise_id WHERE r.item_id = ? "
            "GROUP BY e.type",
            (item_id,),
        ).fetchall()
        return {r["type"]: (r["wrong"], r["n"]) for r in rows}

    # -- activity log -------------------------------------------------------

    def log(self, kind: str, ref_id: int | None = None, note: str = "") -> None:
        self.conn.execute(
            "INSERT INTO activity(kind, ref_id, note, created_at) VALUES (?, ?, ?, ?)",
            (kind, ref_id, note, now_iso()),
        )
        self.conn.commit()
