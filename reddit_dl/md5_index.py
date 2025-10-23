"""Simplified MD5-only index for reddit-dl deduplication.

Tracks only MD5 hashes of downloaded content to prevent duplicate downloads.
No paths, no complex logic - just MD5 hash tracking.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from typing import Optional


class Md5Index:
    """Simple MD5 hash tracker to prevent duplicate downloads."""
    
    def __init__(self, sqlite_path: str) -> None:
        self.path = sqlite_path
        d = os.path.dirname(sqlite_path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        self._create_tables()

    def _create_tables(self) -> None:
        """Create simple md5_hashes table."""
        with self._lock:
            cur = self._conn.cursor()
            # Single table: just track MD5 hashes we've seen
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS md5_hashes (
                    md5 TEXT PRIMARY KEY
                )
                """
            )
            # Optional: track failed URLs to avoid re-attempting
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS failed_urls (
                    url TEXT PRIMARY KEY
                )
                """
            )
            self._conn.commit()

    def has_md5(self, md5: str) -> bool:
        """Check if this MD5 hash has been seen before."""
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT 1 FROM md5_hashes WHERE md5 = ? LIMIT 1",
                    (md5,)
                )
                return cur.fetchone() is not None
        except Exception:
            return False

    def add_md5(self, md5: str) -> None:
        """Add MD5 hash to the index."""
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR IGNORE INTO md5_hashes (md5) VALUES (?)",
                    (md5,)
                )
                self._conn.commit()  # Immediate commit for concurrent safety
        except Exception:
            pass

    def dedupe_after_download(self, md5: str, filepath: str) -> bool:
        """Check if MD5 exists. If yes, delete the file and return True. If no, add MD5 and return False.
        
        Args:
            md5: The MD5 hash of the downloaded file
            filepath: Path to the downloaded file
            
        Returns:
            True if duplicate (file deleted), False if new (MD5 added to index)
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Check if MD5 already exists
            if self.has_md5(md5):
                # Duplicate! Delete the file
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        logger.debug(f"🗑️  Deleted duplicate: {os.path.basename(filepath)} (MD5: {md5[:8]}...)")
                    return True
                except Exception as e:
                    logger.error(f"❌ Failed to delete duplicate {filepath}: {e}")
                    return True  # Still mark as duplicate even if delete failed
            else:
                # New MD5! Add to index
                self.add_md5(md5)
                return False
        except Exception as e:
            logger.error(f"💥 Error in dedupe_after_download: {e}")
            return False

    def is_url_failed(self, url: str) -> bool:
        """Check if URL previously failed."""
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT 1 FROM failed_urls WHERE url = ? LIMIT 1",
                    (url,)
                )
                return cur.fetchone() is not None
        except Exception:
            return False

    def add_failed_url(self, url: str) -> None:
        """Mark URL as failed."""
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR IGNORE INTO failed_urls (url) VALUES (?)",
                    (url,)
                )
                self._conn.commit()
        except Exception:
            pass

    def remove_failed_url(self, url: str) -> None:
        """Remove URL from failed list (e.g., after successful retry)."""
        try:
            with self._lock:
                self._conn.execute(
                    "DELETE FROM failed_urls WHERE url = ?",
                    (url,)
                )
                self._conn.commit()
        except Exception:
            pass

    def get_failed_urls_count(self) -> int:
        """Get count of failed URLs."""
        try:
            with self._lock:
                cur = self._conn.execute("SELECT COUNT(*) FROM failed_urls")
                result = cur.fetchone()
                return result[0] if result else 0
        except Exception:
            return 0

    def checkpoint(self) -> None:
        """Force WAL checkpoint to persist changes."""
        try:
            with self._lock:
                self._conn.commit()
                self._conn.execute("PRAGMA wal_checkpoint(FULL);")
        except Exception:
            pass

    def close(self) -> None:
        """Close database connection."""
        try:
            self.checkpoint()
            self._conn.close()
        except Exception:
            pass

    def get_stats(self) -> dict:
        """Get statistics about the index."""
        try:
            with self._lock:
                cur = self._conn.execute("SELECT COUNT(*) FROM md5_hashes")
                md5_count = cur.fetchone()[0]
                
                cur = self._conn.execute("SELECT COUNT(*) FROM failed_urls")
                failed_count = cur.fetchone()[0]
                
                return {
                    'total_md5s': md5_count,
                    'failed_urls': failed_count
                }
        except Exception:
            return {'total_md5s': 0, 'failed_urls': 0}

    def clear_all(self) -> None:
        """Clear all data from the index."""
        try:
            with self._lock:
                self._conn.execute("DELETE FROM md5_hashes")
                self._conn.execute("DELETE FROM failed_urls")
                self._conn.commit()
        except Exception:
            pass
