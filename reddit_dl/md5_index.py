"""SQLite-backed MD5 index for reddit-dl.

Provides a small thread-safe API for mapping normalized URLs and ETags to md5
and mapping md5 -> local file paths. Uses WAL    def get_failed_urls_count(self) -> int:
        \"\"\"Get the total number of failed URLs tracked.\"\"\"
        try:
            with self._lock:
                cur = self._conn.cursor()
                cur.execute(\"SELECT COUNT(*) FROM failed_urls\")
                result = cur.fetchone()
                return result[0] if result else 0
        except Exception:
            return 0

    def clear_failed_urls(self) -> int:
        \"\"\"Clear all failed URLs from tracking. Returns number of URLs cleared.\"\"\"
        try:
            with self._lock:
                cur = self._conn.cursor()
                cur.execute(\"DELETE FROM failed_urls\")
                count = cur.rowcount
                self._conn.commit()
                return count
        except Exception:
            return 0cheap, safe updates.

This is intentionally lightweight and keeps a simple sqlite3 schema.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import re
from typing import Iterable, List, Optional, Tuple
import shutil
import hashlib
from typing import Dict


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
        # Keep durability reasonable but not too slow. WAL provides better
        # concurrent readers/writers. Use NORMAL synchronous for speed.
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        # Keep temp tables in memory for performance
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        # Ask SQLite to automatically checkpoint the WAL after a small
        # number of pages so the -wal file doesn't grow indefinitely. The
        # value here is a trade-off: lower means more frequent checkpoints
        # (safer for crashes) but more work. 200 pages is modest.
        try:
            self._conn.execute("PRAGMA wal_autocheckpoint = 200;")
        except Exception:
            # older SQLite versions may not support this pragma; ignore
            pass
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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS fp_to_md5 (
                    fp TEXT PRIMARY KEY,
                    md5 TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS failed_urls (
                    url TEXT PRIMARY KEY,
                    failed_at INTEGER,
                    reason TEXT,
                    attempts INTEGER DEFAULT 1
                )
                """
            )
            self._conn.commit()

    def close(self) -> None:
        try:
            with self._lock:
                # Commit pending transactions, then attempt a WAL checkpoint
                # to merge the -wal into the main database file. This is
                # best-effort: if the program is killed with SIGKILL the
                # checkpoint won't run, but for normal shutdowns this helps
                # reduce the risk of leftover -wal/-shm files and lost
                # recent writes.
                try:
                    self._conn.commit()
                    # FULL checkpoint blocks until all writers finish and
                    # merges WAL to the main DB file.
                    try:
                        self._conn.execute("PRAGMA wal_checkpoint(FULL);")
                    except Exception:
                        # ignore checkpoint failures
                        pass
                finally:
                    # Always try to close the connection
                    try:
                        self._conn.close()
                    except Exception:
                        pass
        except Exception:
            pass

    def is_url_failed(self, url: str) -> bool:
        """Check if a URL has previously failed to download."""
        try:
            with self._lock:
                cur = self._conn.cursor()
                cur.execute("SELECT 1 FROM failed_urls WHERE url = ?", (url,))
                return cur.fetchone() is not None
        except Exception:
            return False

    def record_failed_url(self, url: str, reason: str = "download_failed") -> None:
        """Record a URL as failed with the failure reason."""
        try:
            import time
            with self._lock:
                cur = self._conn.cursor()
                # Insert or update the failure record
                cur.execute(
                    """
                    INSERT OR REPLACE INTO failed_urls (url, failed_at, reason, attempts)
                    VALUES (?, ?, ?, 
                        COALESCE((SELECT attempts FROM failed_urls WHERE url = ?), 0) + 1)
                    """,
                    (url, int(time.time()), reason, url)
                )
                self._conn.commit()
        except Exception:
            pass

    def remove_failed_url(self, url: str) -> None:
        """Remove a URL from the failed list (e.g., after successful retry)."""
        try:
            with self._lock:
                cur = self._conn.cursor()
                cur.execute("DELETE FROM failed_urls WHERE url = ?", (url,))
                self._conn.commit()
        except Exception:
            pass

    def get_failed_urls_count(self) -> int:
        """Get the total number of failed URLs tracked."""
        try:
            with self._lock:
                cur = self._conn.cursor()
                cur.execute("SELECT COUNT(*) FROM failed_urls")
                result = cur.fetchone()
                return result[0] if result else 0
        except Exception:
            return 0

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
        # Fetch a snapshot of rows under the lock, then yield without holding the lock
        try:
            with self._lock:
                cur = self._conn.execute("SELECT md5, path FROM md5_to_paths ORDER BY md5")
                rows = cur.fetchall()
        except Exception:
            rows = []
        for md5, path in rows:
            yield md5, path

    def get_existing_path_for_md5(self, md5: str) -> Optional[str]:
        """Return a single existing filesystem path for the given md5, or None.

        As a side-effect, prune any DB rows that reference files which no longer exist.
        """
        existing = None
        try:
            with self._lock:
                cur = self._conn.execute("SELECT path FROM md5_to_paths WHERE md5 = ?", (md5,))
                rows = [r[0] for r in cur.fetchall()]
                # check which paths exist
                to_delete = []
                for p in rows:
                    try:
                        if os.path.exists(p):
                            if not existing:
                                existing = p
                        else:
                            to_delete.append(p)
                    except Exception:
                        # ignore path check errors
                        continue
                # prune missing paths
                for p in to_delete:
                    try:
                        self._conn.execute("DELETE FROM md5_to_paths WHERE md5 = ? AND path = ?", (md5, p))
                    except Exception:
                        pass
                if to_delete:
                    try:
                        self._conn.commit()
                    except Exception:
                        pass
        except Exception:
            return existing
        return existing

    # partial-fingerprint mappings (fp -> md5)
    def get_md5_for_fp(self, fp: str) -> Optional[str]:
        with self._lock:
            cur = self._conn.execute("SELECT md5 FROM fp_to_md5 WHERE fp = ?", (fp,))
            row = cur.fetchone()
            return row[0] if row else None

    def set_fp_md5(self, fp: str, md5: str) -> None:
        with self._lock:
            try:
                self._conn.execute("INSERT OR REPLACE INTO fp_to_md5(fp, md5) VALUES(?, ?)", (fp, md5))
                self._conn.commit()
            except Exception:
                pass

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

    # High-level smart deduplication helpers
    def lookup_by_normalized_url(self, norm_url: str) -> Tuple[Optional[str], Optional[str]]:
        """Return (md5, existing_path) for a normalized URL if present and the file exists.

        Returns (None, None) when no mapping exists or mapped paths are missing.
        """
        try:
            md5 = self.get_md5_for_url(norm_url)
            if not md5:
                return None, None
            path = self.get_existing_path_for_md5(md5)
            if path:
                return md5, path
        except Exception:
            pass
        return None, None

    def find_by_etag(self, etag: str) -> Tuple[Optional[str], Optional[str]]:
        """Return (md5, existing_path) for a given ETag if present and file exists."""
        try:
            md5 = self.get_md5_for_etag(etag)
            if not md5:
                return None, None
            path = self.get_existing_path_for_md5(md5)
            if path:
                return md5, path
        except Exception:
            pass
        return None, None

    def find_by_size(self, size: int) -> Tuple[Optional[str], Optional[str]]:
        """Return first (md5, path) whose file size matches `size`.

        This is a heuristic fallback and may return false positives for coincidental sizes.
        """
        try:
            for md5, p in self.iter_md5_paths():
                try:
                    if os.path.exists(p) and os.path.getsize(p) == int(size):
                        return md5, p
                except Exception:
                    continue
        except Exception:
            pass
        return None, None

    def find_by_partial_fp(self, remote_fp: str, partial_cache: Dict[str, str], partial_size: int) -> Tuple[Optional[str], Optional[str]]:
        """Try to match a partial fingerprint to a known md5 and existing path.

        - Checks persistent fp->md5 mappings first.
        - Falls back to computing partial fingerprints for known files and caching them in `partial_cache`.
        Returns (md5, path) on match or (None, None).
        """
        if not remote_fp:
            return None, None
        try:
            mapped = self.get_md5_for_fp(remote_fp)
            if mapped:
                path = self.get_existing_path_for_md5(mapped)
                if path:
                    return mapped, path
        except Exception:
            pass

        try:
            for md5, p in self.iter_md5_paths():
                try:
                    if md5 in partial_cache:
                        local_fp = partial_cache[md5]
                    else:
                        local_fp = None
                        if os.path.exists(p):
                            with open(p, 'rb') as fh:
                                data = fh.read(partial_size)
                                local_fp = hashlib.sha256(data).hexdigest()
                                partial_cache[md5] = local_fp
                    if local_fp and local_fp == remote_fp:
                        # record mapping for faster future lookups
                        try:
                            self.set_fp_md5(remote_fp, md5)
                        except Exception:
                            pass
                        return md5, p
                except Exception:
                    continue
        except Exception:
            pass
        return None, None

    def copy_existing_to_folder(self, md5: str, folder: str, post_id: Optional[str]) -> Optional[str]:
        """Copy an existing path for `md5` into `folder` using `post_id` as filename.

        Returns the target path on success, or None on failure.
        """
        try:
            path = self.get_existing_path_for_md5(md5)
            if not path:
                return None
            _, ext = os.path.splitext(path)
            target_name = (post_id and re.sub(r"[^A-Za-z0-9._-]", "_", post_id)) or os.path.basename(path)
            target_path = os.path.join(folder, target_name + ext) if not target_name.endswith(ext) else os.path.join(folder, target_name)
            try:
                os.makedirs(os.path.dirname(target_path) or folder, exist_ok=True)
            except Exception:
                pass
            if not os.path.exists(target_path):
                shutil.copy2(path, target_path)
                try:
                    self.add_path_for_md5(md5, target_path)
                except Exception:
                    pass
            return target_path
        except Exception:
            return None

    def dedupe_after_download(self, md5: str, dst: str, norm_url: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """After downloading a file at `dst`, check if an existing file for `md5` already exists.

        If an existing file exists and differs from `dst`, `dst` will be removed and
        the function returns (True, existing_path). Otherwise the function records
        `dst` in the index and returns (False, dst).
        """
        try:
            existing = self.get_existing_path_for_md5(md5)
            if existing and os.path.abspath(existing) != os.path.abspath(dst):
                # remove duplicate
                try:
                    os.remove(dst)
                except Exception:
                    pass
                # ensure url mapping exists (caller may provide norm_url)
                try:
                    if norm_url:
                        self.set_url_md5(norm_url, md5)
                except Exception:
                    pass
                return True, existing
            # No existing duplicate found: record dst
            try:
                if norm_url:
                    self.set_url_md5(norm_url, md5)
            except Exception:
                pass
            try:
                self.add_path_for_md5(md5, dst)
            except Exception:
                pass
            return False, dst
        except Exception:
            return False, dst

    def record_download(self, md5: str, norm_url: Optional[str], path: str, resp_etag: Optional[str] = None, fp: Optional[str] = None) -> None:
        """Convenience to record URL->md5, add path and optional etag/fingerprint mappings."""
        try:
            if norm_url:
                try:
                    self.set_url_md5(norm_url, md5)
                except Exception:
                    pass
            try:
                self.add_path_for_md5(md5, path)
            except Exception:
                pass
            if resp_etag:
                try:
                    self.set_etag_md5(resp_etag, md5)
                except Exception:
                    pass
            if fp:
                try:
                    self.set_fp_md5(fp, md5)
                except Exception:
                    pass
        except Exception:
            pass
