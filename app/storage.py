import sqlite3
import hashlib
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_PATH = Path("static/agent_history.db")


def get_connection() -> sqlite3.Connection:
    """Create a thread-safe SQLite connection with dictionary-like row access."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize SQLite tables for news deduplication and post archive history."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Table 1: Stores hashes of already used news articles so they never repeat
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS seen_topics (
                topic_hash TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                link TEXT,
                source TEXT,
                seen_at TEXT NOT NULL
            )
        """)

        # Table 2: Stores every generated and published post for the History UI
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS post_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                link TEXT NOT NULL,
                post_text TEXT NOT NULL,
                image_url TEXT NOT NULL,
                image_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                linkedin_urn TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                published_at TEXT
            )
        """)
        conn.commit()


def normalize_title(title: str) -> str:
    """Strip source suffixes and punctuation for reliable topic hashing."""
    clean = title.rsplit(" - ", 1)[0].lower().strip()
    clean = re.sub(r"[^a-z0-9\s]", "", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean


def compute_topic_hash(title: str) -> str:
    """Return a SHA-256 fingerprint of the normalized article headline."""
    normalized = normalize_title(title)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_topic_seen(title: str, link: str = "") -> bool:
    """Check if a news headline or URL has already been generated in the past."""
    init_db()
    topic_hash = compute_topic_hash(title)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM seen_topics WHERE topic_hash = ? OR (link != '' AND link = ?) LIMIT 1",
            (topic_hash, link)
        )
        return cursor.fetchone() is not None


def mark_topic_seen(title: str, link: str, source: str) -> None:
    """Record a news article in SQLite so it will never be selected again."""
    init_db()
    topic_hash = compute_topic_hash(title)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO seen_topics (topic_hash, title, link, source, seen_at)
            VALUES (?, ?, ?, ?, ?)
        """, (topic_hash, title, link, source, now))
        conn.commit()


def save_post_record(
    title: str,
    source: str,
    link: str,
    post_text: str,
    image_url: str,
    image_path: str,
    status: str = "draft"
) -> int:
    """Save a newly generated draft into the post_history table and return its ID."""
    init_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO post_history (
                title, source, link, post_text, image_url, image_path, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, source, link, post_text, image_url, image_path, status, now))
        conn.commit()
        return int(cursor.lastrowid)


def update_post_status(
    post_id: int,
    post_text: str,
    status: str = "published",
    linkedin_urn: str = ""
) -> None:
    """Mark an existing post as published and store the final edited caption."""
    init_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE post_history
            SET post_text = ?, status = ?, linkedin_urn = ?, published_at = ?
            WHERE id = ?
        """, (post_text, status, linkedin_urn, now, post_id))
        conn.commit()


def delete_post_record(post_id: int) -> bool:
    """
    Delete an unwanted draft or post from post_history and remove its image file.
    Note: The topic hash remains in seen_topics so the unwanted news never repeats.
    """
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT image_path FROM post_history WHERE id = ?", (post_id,))
        row = cursor.fetchone()
        if not row:
            return False

        image_path = row["image_path"]
        cursor.execute("DELETE FROM post_history WHERE id = ?", (post_id,))
        conn.commit()

    # Clean up generated image file from disk if it exists
    if image_path:
        try:
            img_file = Path(image_path)
            if img_file.exists():
                img_file.unlink()
        except Exception:
            pass

    return True


def delete_all_drafts() -> int:
    """Delete all unpublished drafts from post_history and clean up their images."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, image_path FROM post_history WHERE status = 'draft'")
        rows = cursor.fetchall()

        cursor.execute("DELETE FROM post_history WHERE status = 'draft'")
        conn.commit()

    for row in rows:
        if row["image_path"]:
            try:
                img_file = Path(row["image_path"])
                if img_file.exists():
                    img_file.unlink()
            except Exception:
                pass

    return len(rows)


def get_post_history(status_filter: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Return past posts ordered from newest to oldest, with optional status filter."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        if status_filter in ("published", "draft"):
            cursor.execute("""
                SELECT id, title, source, link, post_text, image_url, image_path,
                       status, linkedin_urn, created_at, published_at
                FROM post_history
                WHERE status = ?
                ORDER BY id DESC
                LIMIT ?
            """, (status_filter, limit))
        else:
            cursor.execute("""
                SELECT id, title, source, link, post_text, image_url, image_path,
                       status, linkedin_urn, created_at, published_at
                FROM post_history
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_latest_post_record() -> Optional[Dict[str, Any]]:
    """Return the most recent remaining post in history, or None if empty."""
    history = get_post_history(limit=1)
    return history[0] if history else None


def get_agent_stats() -> Dict[str, int]:
    """Return counters for total generated, published, drafts, and seen articles."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM post_history")
        total_generated = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM post_history WHERE status = 'published'")
        total_published = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM post_history WHERE status = 'draft'")
        total_drafts = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM seen_topics")
        unique_topics_seen = cursor.fetchone()[0]

        return {
            "total_generated": total_generated,
            "total_published": total_published,
            "total_drafts": total_drafts,
            "unique_topics_seen": unique_topics_seen
        }