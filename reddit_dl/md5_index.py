"""SQLite-backed MD5 index for reddit-dl.

Provides a small thread-safe API for mapping normalized URLs and ETags to md5
and mapping md5 -> local file paths. Uses WAL mode for cheap, safe updates.

This is intentionally lightweight and keeps a simple sqlite3 schema.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Iterable, List, Optional, Tuple


class Md5Index:
    def __init__(self, sqlite_path: str) -> None:
        self.path = sqlite_path
        d = os.path.dirname(sqlite_path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

        # allow access from multiple threads; serialize with our own lock
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        self._create_tables()

    def _create_tables(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS url_to_md5 (
                    url TEXT PRIMARY KEY,
                    md5 TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS md5_to_paths (
                    md5 TEXT,
                    path TEXT,
                    PRIMARY KEY(md5, path)
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_md5_to_paths_md5 ON md5_to_paths(md5)
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS etag_to_md5 (
                    etag TEXT PRIMARY KEY,
                    md5 TEXT
                )
                """
            )
            self._conn.commit()

    def close(self) -> None:
        try:
            with self._lock:
                self._conn.commit()
                self._conn.close()
        except Exception:
            pass

    def checkpoint(self) -> None:
        # allow callers to checkpoint WAL if they want; best-effort
        try:
            with self._lock:
                self._conn.execute("PRAGMA wal_checkpoint(FULL);")
        except Exception:
            pass

    # URL mappings
    def get_md5_for_url(self, url: str) -> Optional[str]:
        with self._lock:
            cur = self._conn.execute("SELECT md5 FROM url_to_md5 WHERE url = ?", (url,))
            row = cur.fetchone()
            return row[0] if row else None

    def set_url_md5(self, url: str, md5: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO url_to_md5(url, md5) VALUES(?, ?)", (url, md5))
            self._conn.commit()

    # etag mappings
    def get_md5_for_etag(self, etag: str) -> Optional[str]:
        with self._lock:
            cur = self._conn.execute("SELECT md5 FROM etag_to_md5 WHERE etag = ?", (etag,))
            row = cur.fetchone()
            return row[0] if row else None

    def set_etag_md5(self, etag: str, md5: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO etag_to_md5(etag, md5) VALUES(?, ?)", (etag, md5))
            self._conn.commit()

    # md5 -> paths
    def get_paths_for_md5(self, md5: str) -> List[str]:
        with self._lock:
            cur = self._conn.execute("SELECT path FROM md5_to_paths WHERE md5 = ?", (md5,))
            return [row[0] for row in cur.fetchall()]

    def add_path_for_md5(self, md5: str, path: str) -> None:
        with self._lock:
            try:
                self._conn.execute("INSERT OR IGNORE INTO md5_to_paths(md5, path) VALUES(?, ?)", (md5, path))
                self._conn.commit()
            except Exception:
                pass

    def iter_md5_paths(self) -> Iterable[Tuple[str, str]]:
        with self._lock:
            cur = self._conn.execute("SELECT md5, path FROM md5_to_paths ORDER BY md5")
            for md5, path in cur.fetchall():
                yield md5, path

    def has_any_entries(self) -> bool:
        with self._lock:
            cur = self._conn.execute("SELECT 1 FROM url_to_md5 LIMIT 1")
            return cur.fetchone() is not None

    def migrate_from_json(self, json_path: str) -> None:
        """Migrate an existing JSON md5 index into the sqlite DB. No-op if DB already populated."""
        if not os.path.exists(json_path):
            return
        # if DB already has entries, skip migration
        try:
            if self.has_any_entries():
                return
        except Exception:
            pass

        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception:
            return

        raw_map = raw.get("url_to_md5", {}) if isinstance(raw, dict) else {}
        raw_paths = raw.get("md5_to_paths", {}) if isinstance(raw, dict) else {}
        raw_etags = raw.get("etag_to_md5", {}) if isinstance(raw, dict) else {}

        # insert mappings
        for url, md5 in raw_map.items():
            try:
                self.set_url_md5(url, md5)
            except Exception:
                pass

        for md5, paths in raw_paths.items():
            if not isinstance(paths, list):
                continue
            for p in paths:
                try:
                    self.add_path_for_md5(md5, p)
                except Exception:
                    pass

        for etag, md5 in raw_etags.items():
            try:
                self.set_etag_md5(etag, md5)
            except Exception:
                pass

        # checkpoint after bulk load
        try:
            self.checkpoint()
        except Exception:
            pass
