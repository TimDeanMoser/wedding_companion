import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("data/wedding.db")
DB_PATH.parent.mkdir(exist_ok=True)


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db() -> None:
    with _connect() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_admin   INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS uploads (
                filename    TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL REFERENCES sessions(id),
                uploaded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS songs (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                artist      TEXT NOT NULL,
                cover       TEXT,
                album       TEXT,
                session_id  TEXT NOT NULL REFERENCES sessions(id),
                added_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS likes (
                filename   TEXT NOT NULL,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                PRIMARY KEY (filename, session_id)
            );

            CREATE TABLE IF NOT EXISTS spotify_auth (
                id            INTEGER PRIMARY KEY CHECK (id = 1),
                access_token  TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at    REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS timeline_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                sort_order INTEGER NOT NULL,
                time       TEXT NOT NULL,
                label      TEXT NOT NULL
            );
        """)
        # Migrate: add is_admin column if it doesn't exist (for existing DBs)
        try:
            con.execute("ALTER TABLE sessions ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column already exists
        # Seed timeline from config if table is empty
        count = con.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0]
        if count == 0:
            from config import ABLAUF_EVENTS
            for i, ev in enumerate(ABLAUF_EVENTS):
                con.execute(
                    "INSERT INTO timeline_events (sort_order, time, label) VALUES (?, ?, ?)",
                    (i, ev["time"], ev["label"]),
                )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def get_session(session_id: str) -> sqlite3.Row | None:
    with _connect() as con:
        return con.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()


def create_session(name: str, is_admin: bool = False) -> str:
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as con:
        con.execute(
            "INSERT INTO sessions (id, name, created_at, is_admin) VALUES (?, ?, ?, ?)",
            (session_id, name, now, 1 if is_admin else 0),
        )
    return session_id


def list_sessions() -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            "SELECT id, name, created_at, is_admin FROM sessions ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_session(session_id: str) -> None:
    with _connect() as con:
        con.execute("DELETE FROM likes WHERE session_id = ?", (session_id,))
        con.execute("DELETE FROM songs WHERE session_id = ?", (session_id,))
        con.execute("DELETE FROM uploads WHERE session_id = ?", (session_id,))
        con.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------

def add_upload(filename: str, session_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as con:
        con.execute(
            "INSERT OR IGNORE INTO uploads (filename, session_id, uploaded_at) VALUES (?, ?, ?)",
            (filename, session_id, now),
        )


def get_upload_meta(filename: str) -> dict | None:
    with _connect() as con:
        row = con.execute(
            """
            SELECT s.name AS session_name, u.uploaded_at
            FROM uploads u
            JOIN sessions s ON s.id = u.session_id
            WHERE u.filename = ?
            """,
            (filename,),
        ).fetchone()
    if row is None:
        return None
    return {"session_name": row["session_name"], "uploaded_at": row["uploaded_at"]}


def delete_upload(filename: str) -> None:
    with _connect() as con:
        con.execute("DELETE FROM uploads WHERE filename = ?", (filename,))
        con.execute("DELETE FROM likes WHERE filename = ?", (filename,))


def delete_all_uploads() -> None:
    with _connect() as con:
        con.execute("DELETE FROM likes")
        con.execute("DELETE FROM uploads")


# ---------------------------------------------------------------------------
# Songs
# ---------------------------------------------------------------------------

def count_songs_last_hour(session_id: str) -> int:
    with _connect() as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS cnt FROM songs
            WHERE session_id = ?
              AND added_at > datetime('now', '-1 hour')
            """,
            (session_id,),
        ).fetchone()
    return row["cnt"] if row else 0


def load_songs() -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            """
            SELECT songs.*, sessions.name AS session_name
            FROM songs
            LEFT JOIN sessions ON sessions.id = songs.session_id
            ORDER BY songs.added_at ASC
            """,
        ).fetchall()
    return [dict(r) for r in rows]


def song_exists(song_id: str) -> bool:
    with _connect() as con:
        row = con.execute(
            "SELECT 1 FROM songs WHERE id = ?", (song_id,)
        ).fetchone()
    return row is not None


def add_song(track: dict, session_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as con:
        con.execute(
            """
            INSERT INTO songs (id, name, artist, cover, album, session_id, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                track["id"],
                track["name"],
                track["artist"],
                track.get("cover"),
                track.get("album", ""),
                session_id,
                now,
            ),
        )


def delete_song(song_id: str) -> None:
    with _connect() as con:
        con.execute("DELETE FROM songs WHERE id = ?", (song_id,))


def delete_all_songs() -> None:
    with _connect() as con:
        con.execute("DELETE FROM songs")


def reset_all() -> None:
    """Full reset: delete the database file and recreate it fresh."""
    DB_PATH.unlink(missing_ok=True)
    init_db()


# ---------------------------------------------------------------------------
# Likes
# ---------------------------------------------------------------------------

def toggle_like(filename: str, session_id: str) -> dict:
    with _connect() as con:
        existing = con.execute(
            "SELECT 1 FROM likes WHERE filename = ? AND session_id = ?",
            (filename, session_id),
        ).fetchone()
        if existing:
            con.execute(
                "DELETE FROM likes WHERE filename = ? AND session_id = ?",
                (filename, session_id),
            )
            liked = False
        else:
            con.execute(
                "INSERT INTO likes (filename, session_id) VALUES (?, ?)",
                (filename, session_id),
            )
            liked = True
        count = con.execute(
            "SELECT COUNT(*) FROM likes WHERE filename = ?", (filename,)
        ).fetchone()[0]
    return {"liked": liked, "count": count}


def get_like_counts() -> dict:
    with _connect() as con:
        rows = con.execute(
            "SELECT filename, COUNT(*) AS cnt FROM likes GROUP BY filename"
        ).fetchall()
    return {r["filename"]: r["cnt"] for r in rows}


def get_liked_by_session(session_id: str) -> set:
    with _connect() as con:
        rows = con.execute(
            "SELECT filename FROM likes WHERE session_id = ?", (session_id,)
        ).fetchall()
    return {r["filename"] for r in rows}


# ---------------------------------------------------------------------------
# Spotify auth
# ---------------------------------------------------------------------------

def get_spotify_auth() -> sqlite3.Row | None:
    with _connect() as con:
        return con.execute("SELECT * FROM spotify_auth WHERE id = 1").fetchone()


def delete_spotify_auth() -> None:
    with _connect() as con:
        con.execute("DELETE FROM spotify_auth WHERE id = 1")


def save_spotify_auth(access_token: str, refresh_token: str, expires_at: float) -> None:
    with _connect() as con:
        con.execute(
            """
            INSERT INTO spotify_auth (id, access_token, refresh_token, expires_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at
            """,
            (access_token, refresh_token, expires_at),
        )


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

def load_timeline() -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            "SELECT time, label FROM timeline_events ORDER BY sort_order ASC"
        ).fetchall()
    return [{"time": r["time"], "label": r["label"]} for r in rows]


def save_timeline(events: list[dict]) -> None:
    with _connect() as con:
        con.execute("DELETE FROM timeline_events")
        for i, ev in enumerate(events):
            con.execute(
                "INSERT INTO timeline_events (sort_order, time, label) VALUES (?, ?, ?)",
                (i, ev["time"], ev["label"]),
            )
