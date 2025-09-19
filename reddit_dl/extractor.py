"""Minimal Reddit extractor for reddit-dl

- supports unauthenticated requests or script-type OAuth2 (password grant)
- reads config JSON with oauth keys (see config.example.json)
- handles user pages, subreddits and permalink (comment/post) URLs
- collects media URLs (images, preview, direct links) and optionally downloads them
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import re
import sys
from typing import Dict, Optional, Set, Iterable, Tuple
from reddit_dl.md5_index import Md5Index
import threading
import time
import hashlib
import shutil
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

REDDIT_OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
DEFAULT_USER_AGENT = "reddit-dl/0.1 (by /u/yourusername)"

# simple in-memory token cache: {client_id: (token, expires_at)}
_TOKEN_CACHE = {}


class CustomHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Custom formatter for better help text alignment and spacing."""
    
    def __init__(self, prog, indent_increment=2, max_help_position=24, width=None):
        super().__init__(prog, indent_increment, max_help_position, width)
    
    def _format_action_invocation(self, action):
        if not action.option_strings:
            default = self._get_default_metavar_for_positional(action)
            metavar, = self._metavar_formatter(action, default)(1)
            return metavar
        else:
            parts = []
            # if the Optional doesn't take a value, format is: -s, --long
            if action.nargs == 0:
                parts.extend(action.option_strings)
            # if the Optional takes a value, format is: -s ARGS, --long ARGS
            else:
                default = self._get_default_metavar_for_optional(action)
                args_string = self._format_args(action, default)
                for option_string in action.option_strings:
                    parts.append('%s %s' % (option_string, args_string))
            return ', '.join(parts)


# Disk-backed token cache helpers
def _default_token_cache_path() -> str:
    # allow override via env var
    return os.environ.get("REDDIT_TOKEN_CACHE") or os.path.expanduser("~/.reddit_dl_tokens.json")


def _load_token_cache_file(path: Optional[str] = None) -> Dict[str, Dict]:
    path = path or _default_token_cache_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return {}


def _save_token_cache_file(cache: Dict[str, Dict], path: Optional[str] = None) -> None:
    path = path or _default_token_cache_path()
    try:
        d = os.path.dirname(path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
    except Exception:
        pass


# Simple token-bucket rate limiter for downloads (tokens per second)
class TokenBucket:
    def __init__(self, rate: float = 4.0) -> None:
        self.rate = float(rate)
        self.capacity = float(max(1.0, rate))
        self._tokens = float(self.capacity)
        self._last = time.time()
        self._lock = threading.Lock()

    def _add_tokens(self) -> None:
        now = time.time()
        elapsed = now - self._last
        if elapsed <= 0:
            return
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last = now

    def consume(self, tokens: float = 1.0) -> bool:
        with self._lock:
            self._add_tokens()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait_for_token(self, tokens: float = 1.0) -> None:
        while True:
            if self.consume(tokens=tokens):
                return
            time.sleep(0.01)

def load_config(path: Optional[str]) -> Dict:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _default_md5_db_path(outdir: str) -> str:
    return os.path.join(outdir, ".md5_index.json")


def normalize_media_url(url: str) -> str:
    """Normalize media URLs to reduce token/query churn.

    Rules:
    - For known media hosts (i.redd.it, media.redgifs.com) strip the entire query string.
    - For preview.redd.it strip the ephemeral 's' param (which is a content-hash signature) but keep others.
    - For other hosts, strip common ephemeral params (s, sig, signature, token, expires, ttl, key, st, se)
      and remove utm_* parameters.
    """
    try:
        p = urlsplit(url)
        host = (p.netloc or "").lower()
        # host-specific rules
        if host.endswith("i.redd.it") or host.endswith("media.redgifs.com") or host.endswith("redgifs.com"):
            # strip query and fragment
            return urlunsplit((p.scheme, p.netloc, p.path, "", ""))

        # preview.redd.it: strip entire query (the 's' signature is ephemeral)
        if host.endswith("preview.redd.it"):
            return urlunsplit((p.scheme, p.netloc, p.path, "", ""))

        # generic cleanup: drop known ephemeral params and utm_ params
        ephemeral = {"s", "sig", "signature", "token", "expires", "ttl", "key", "st", "se"}
        # parse query list safely
        qlist = parse_qsl(p.query or "", keep_blank_values=True)
        filtered = []
        for (k, v) in qlist:
            lk = k.lower()
            if lk.startswith("utm_"):
                continue
            if lk in ephemeral:
                continue
            filtered.append((k, v))
        if filtered:
            newq = urlencode(filtered, doseq=True)
            return urlunsplit((p.scheme, p.netloc, p.path, newq, p.fragment or ""))
        # nothing left to change
        return urlunsplit((p.scheme, p.netloc, p.path, "", p.fragment or ""))
    except Exception:
        return url


def load_md5_db(path: str) -> Dict:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
                # normalize url keys to avoid token/query churn
                raw_map = raw.get("url_to_md5", {}) if isinstance(raw, dict) else {}
                raw_paths = raw.get("md5_to_paths", {}) if isinstance(raw, dict) else {}
                new_map: Dict[str, str] = {}
                new_paths: Dict[str, list] = {}
                for url, md5 in list(raw_map.items()):
                    try:
                        norm = normalize_media_url(url)
                    except Exception:
                        norm = url
                    # prefer the first md5 seen for a normalized URL
                    if norm in new_map:
                        # if md5 differs, still merge path lists under both md5 entries
                        if new_map[norm] != md5:
                            # add paths for this md5 if present
                            for p in raw_paths.get(md5, []):
                                new_paths.setdefault(md5, []).append(p)
                        continue
                    new_map[norm] = md5
                    # dedupe paths for this md5
                    seen = set()
                    for p in raw_paths.get(md5, []):
                        if p in seen:
                            continue
                        seen.add(p)
                        new_paths.setdefault(md5, []).append(p)
                # preserve any existing etag_to_md5 mappings
                raw_etags = raw.get("etag_to_md5", {}) if isinstance(raw, dict) else {}
                migrated = {"url_to_md5": new_map, "md5_to_paths": new_paths, "etag_to_md5": raw_etags}
                # save migrated DB back to path for future runs
                try:
                    save_md5_db(migrated, path)
                except Exception:
                    pass
                return migrated
    except Exception:
        pass
    # structure: {"url_to_md5": {url: md5}, "md5_to_paths": {md5: [paths]}}
    return {"url_to_md5": {}, "md5_to_paths": {}}


def migrate_and_normalize_md5_db(path: str) -> None:
    """Read existing md5 db, normalize all URL keys and save back. Safe to call repeatedly."""
    try:
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        raw_map = raw.get("url_to_md5", {}) if isinstance(raw, dict) else {}
        raw_paths = raw.get("md5_to_paths", {}) if isinstance(raw, dict) else {}
        new_map: Dict[str, str] = {}
        new_paths: Dict[str, list] = {}
        for url, md5 in list(raw_map.items()):
            try:
                norm = normalize_media_url(url)
            except Exception:
                norm = url
            # if collision (different md5 for same normalized URL) just keep first md5 and merge paths
            if norm in new_map and new_map[norm] != md5:
                # merge paths for this md5
                for p in raw_paths.get(md5, []):
                    new_paths.setdefault(md5, []).append(p)
                continue
            new_map[norm] = md5
            # dedupe paths
            seen = set()
            for p in raw_paths.get(md5, []):
                if p in seen:
                    continue
                seen.add(p)
                new_paths.setdefault(md5, []).append(p)

        # preserve any existing etag_to_md5 mappings
        raw_etags = raw.get("etag_to_md5", {}) if isinstance(raw, dict) else {}
        migrated = {"url_to_md5": new_map, "md5_to_paths": new_paths, "etag_to_md5": raw_etags}
        save_md5_db(migrated, path)
    except Exception:
        pass


def save_md5_db(db: Dict, path: str) -> None:
    try:
        d = os.path.dirname(path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
        # Ensure url keys are normalized before persisting to disk
        out = dict(db)
        try:
            raw_map = out.get("url_to_md5", {}) if isinstance(out, dict) else {}
            new_map: Dict[str, str] = {}
            for url, md5 in list(raw_map.items()):
                try:
                    norm = normalize_media_url(url)
                except Exception:
                    norm = url
                # prefer the first md5 seen for a normalized URL
                if norm in new_map:
                    continue
                new_map[norm] = md5
            out["url_to_md5"] = new_map
            # also dedupe md5_to_paths lists before writing
            try:
                raw_paths = out.get("md5_to_paths", {}) if isinstance(out, dict) else {}
                new_paths = {}
                for md5, paths in raw_paths.items():
                    seen = set()
                    lst = []
                    for p in paths:
                        if p in seen:
                            continue
                        seen.add(p)
                        lst.append(p)
                    if lst:
                        new_paths[md5] = lst
                out["md5_to_paths"] = new_paths
            except Exception:
                pass
        except Exception:
            # fall back to writing original db on error
            out = db
        # include etag_to_md5 if present
        try:
            if isinstance(db, dict) and "etag_to_md5" in db:
                out["etag_to_md5"] = db.get("etag_to_md5", {})
        except Exception:
            pass
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def compute_md5(path: str, chunk_size: int = 8192) -> Optional[str]:
    try:
        h = hashlib.md5()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(chunk_size), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def head_check(url: str, user_agent: str) -> Tuple[Optional[int], Optional[str]]:
    """Perform a HEAD request and return (content_length, etag) if available."""
    try:
        headers = {"User-Agent": user_agent}
        # do not send Authorization to CDNs
        r = requests.head(url, headers=headers, allow_redirects=True, timeout=10)
        r.raise_for_status()
        cl = r.headers.get("content-length")
        etag = r.headers.get("etag")
        try:
            if cl:
                cl = int(cl)
        except Exception:
            cl = None
        return cl, etag
    except Exception:
        return None, None

def get_oauth_token(cfg: Dict) -> Optional[str]:
    """Obtain an OAuth2 token from Reddit.

    Supports two modes:
    - password grant (script apps): requires client_id, client_secret, username, password
    - client_credentials grant: requires client_id and client_secret only (falls back to this)

    Tokens are cached in-memory until they expire.
    Returns access_token string or None if credentials are not provided or on error.
    """
    reddit_cfg = cfg.get("extractor", {}).get("reddit", {})
    oauth = reddit_cfg.get("oauth") or {}
    # allow environment variable overrides for secrets (safer than committing to config)
    client_id = os.environ.get("REDDIT_CLIENT_ID") or oauth.get("client_id")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET") or oauth.get("client_secret")
    username = os.environ.get("REDDIT_USERNAME") or oauth.get("username")
    password = os.environ.get("REDDIT_PASSWORD") or oauth.get("password")
    user_agent = os.environ.get("REDDIT_USER_AGENT") or reddit_cfg.get("user_agent", DEFAULT_USER_AGENT)

    if not (client_id and client_secret):
        return None

    import time

    # First, try in-memory cache
    cached = _TOKEN_CACHE.get(client_id)
    if cached:
        token, expires_at = cached
        if time.time() < expires_at - 10:
            return token

    # Next, try disk-backed cache
    token_cache_path = os.environ.get("REDDIT_TOKEN_CACHE") or reddit_cfg.get("token_cache")
    disk_cache = _load_token_cache_file(token_cache_path)
    entry = disk_cache.get(client_id)
    if isinstance(entry, dict):
        token = entry.get("access_token")
        expires_at = entry.get("expires_at")
        try:
            if token and float(expires_at) and time.time() < float(expires_at) - 10:
                # prime in-memory cache
                _TOKEN_CACHE[client_id] = (token, float(expires_at))
                return token
        except Exception:
            pass

    auth = requests.auth.HTTPBasicAuth(client_id, client_secret)
    headers = {"User-Agent": user_agent}

    if username and password:
        data = {"grant_type": "password", "username": username, "password": password}
    else:
        # fallback to application-only token
        data = {"grant_type": "client_credentials"}

    try:
        r = requests.post(REDDIT_OAUTH_TOKEN_URL, auth=auth, data=data, headers=headers, timeout=10)
        r.raise_for_status()
    except Exception as exc:
        # don't crash the whole program on token failure; return None so we fall back to unauthenticated
        logging.getLogger(__name__).warning("Failed to obtain OAuth token: %s", exc)
        logging.getLogger(__name__).info("Hint: create a Reddit app and set REDDIT_CLIENT_ID/SECRET in env or config.json")
        return None

    j = r.json()
    token = j.get("access_token")
    expires_in = j.get("expires_in") or 0
    try:
        expires_in = int(expires_in)
    except Exception:
        expires_in = 0

    if token:
        expires_at = time.time() + max(expires_in, 300)
        _TOKEN_CACHE[client_id] = (token, expires_at)
        # save to disk cache as well
        try:
            path = os.environ.get("REDDIT_TOKEN_CACHE") or reddit_cfg.get("token_cache")
            disk_cache = _load_token_cache_file(path)
            disk_cache[client_id] = {"access_token": token, "expires_at": expires_at}
            _save_token_cache_file(disk_cache, path)
        except Exception:
            pass
        return token
    return None

def fetch_json(url: str, token: Optional[str], user_agent: str) -> Dict:
    headers = {"User-Agent": user_agent}
    if token:
        headers["Authorization"] = f"bearer {token}"
    # Reddit JSON endpoints: append .json where appropriate
    if not url.endswith(".json"):
        # allow passing permalink or listing URL
        if re.search(r"/comments/|/user/|/r/", url):
            url = url.rstrip("/") + ".json"

    # If we have a bearer token, use the OAuth API host which accepts bearer tokens
    if token:
        url = re.sub(r"^https?://(www\.)?reddit\.com", "https://oauth.reddit.com", url, flags=re.I)

    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()

def collect_media_from_post(post: Dict) -> Set[str]:
    urls = []
    data = post.get("data", {})

    # Priority 1: secure_media/media providers (special-case RedGIFs -> media.redgifs.com/*.mp4)
    try:
        sm = data.get("secure_media") or data.get("media")
        if isinstance(sm, dict):
            oembed = sm.get("oembed")
            if isinstance(oembed, dict):
                # First, if provider is redgifs (or thumbnail indicates media.redgifs), construct direct mp4
                provider = (oembed.get("provider_url") or "").lower()
                thumb = oembed.get("thumbnail_url") or sm.get("thumbnail_url")
                # if we see redgifs provider or a media.redgifs thumbnail
                if ("redgifs.com" in provider) or (thumb and "media.redgifs.com" in thumb):
                    try:
                        # attempt to get an id from either the thumbnail or the iframe/watch URL
                        from urllib.parse import urlparse

                        if thumb and isinstance(thumb, str) and "media.redgifs.com" in thumb:
                            p = urlparse(thumb)
                            name = os.path.basename(p.path)
                            name_base = re.sub(r"(-poster|-thumbnail)\.[a-zA-Z0-9]+$", "", name)
                            mp4 = f"{p.scheme}://{p.netloc}/{name_base}.mp4"
                            return {mp4}
                        # fall back: try parsing iframe/watch URL in oembed.html or data['url']
                        html_iframe = oembed.get("html") or ""
                        m = re.search(r"redgifs\.com/(?:watch|ifr)/([A-Za-z0-9_-]+)", html_iframe)
                        if m:
                            idpart = m.group(1)
                            mp4 = f"https://media.redgifs.com/{idpart}.mp4"
                            return {mp4}
                        # final fallback: try any video-like field
                        for k in ("url", "video_url", "fallback_url", "thumbnail_url"):
                            v = oembed.get(k) or sm.get(k)
                            if v and isinstance(v, str) and v.startswith("http"):
                                return {v.replace("&amp;", "&")}
                    except Exception:
                        pass
    except Exception:
        pass

    # Priority 2: reddit_video_preview fallback (direct reddit MP4)
    try:
        rv = data.get("preview", {}).get("reddit_video_preview")
        if isinstance(rv, dict):
            fb = rv.get("fallback_url")
            if fb:
                return {fb.replace("&amp;", "&")}
    except Exception:
        pass

    # Priority 3: direct fields (sometimes contain direct links)
    for key in ("url_overridden_by_dest", "url"):
        u = data.get(key)
        if u and isinstance(u, str):
            # If the direct link is a reddit gallery permalink and we have media_metadata,
            # prefer to expand and return the gallery item URLs instead of the gallery link.
            try:
                if "/gallery/" in u or u.rstrip("/").endswith("/gallery"):
                    mm = data.get("media_metadata")
                    if isinstance(mm, dict) and mm:
                        out = set()
                        for k, v in mm.items():
                            if isinstance(v, dict):
                                src = None
                                s_field = v.get("s") or {}
                                if isinstance(s_field, dict):
                                    src = s_field.get("u") or s_field.get("url")
                                if not src:
                                    p_field = v.get("p") or []
                                    try:
                                        best = None
                                        best_w = 0
                                        for item in p_field:
                                            if isinstance(item, dict):
                                                w = int(item.get("x") or item.get("width") or 0)
                                                if w > best_w:
                                                    best_w = w
                                                    best = item.get("u")
                                        if best:
                                            src = best
                                    except Exception:
                                        src = None
                                if src:
                                    out.add(src.replace("&amp;", "&"))
                        if out:
                            return out
            except Exception:
                pass
            return {u.replace("&amp;", "&")}

    # Priority 4: galleries -> return highest-resolution image per gallery item (if no video found)
    try:
        mm = data.get("media_metadata")
        if isinstance(mm, dict) and mm:
            out = set()
            for k, v in mm.items():
                if isinstance(v, dict):
                    src = None
                    s_field = v.get("s") or {}
                    if isinstance(s_field, dict):
                        src = s_field.get("u") or s_field.get("url")
                    if not src:
                        p_field = v.get("p") or []
                        try:
                            best = None
                            best_w = 0
                            for item in p_field:
                                if isinstance(item, dict):
                                    w = int(item.get("x") or item.get("width") or 0)
                                    if w > best_w:
                                        best_w = w
                                        best = item.get("u")
                            if best:
                                src = best
                        except Exception:
                            src = None
                    if src:
                        out.add(src.replace("&amp;", "&"))
            if out:
                return out
    except Exception:
        pass

    # Priority 5: preview images (last resort)
    try:
        preview = data.get("preview", {})
        images = preview.get("images", [])
        for img in images:
            source = img.get("source", {}).get("url")
            if source:
                return {source.replace("&amp;", "&")}
    except Exception:
        pass

    return set()


def _download_parallel(urls: Iterable[str], outdir: str, token: Optional[str], user_agent: str, concurrency: int = 4, rate: float = 4.0) -> Dict[str, str]:
    """Download a collection of URLs in parallel with a TokenBucket rate limiter.

    Returns a mapping url -> destination path (or .failed path).
    """
    results: Dict[str, str] = {}
    limiter = TokenBucket(rate=rate)

    def worker(u: str) -> Tuple[str, str]:
        # Wait for permission to make a request
        limiter.wait_for_token()
        dst = download_url(u, outdir, token=token, user_agent=user_agent)
        return u, dst

    with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as ex:
        futures = {ex.submit(worker, u): u for u in urls}
        for fut in as_completed(futures):
            try:
                u, dst = fut.result()
            except Exception as e:
                u = futures.get(fut)
                dst = os.path.join(outdir, _sanitize_filename((u or "file")) + ".failed")
                with open(dst, "w", encoding="utf-8") as fh:
                    fh.write(f"{u}\n{str(e)}\n")
            results[u] = dst
    return results

def parse_listing(json_data: Dict) -> Set[str]:
    media = set()
    if isinstance(json_data, dict) and "data" in json_data and "children" in json_data["data"]:  # listing
        for child in json_data["data"]["children"]:
            media.update(collect_media_from_post(child))
    elif isinstance(json_data, list):
        # permalink JSON responses are lists: [post, comments]
        for item in json_data:
            if isinstance(item, dict) and "data" in item and "children" in item["data"]:
                for child in item["data"]["children"]:
                    media.update(collect_media_from_post(child))
    return media

def _sanitize_filename(name: str) -> str:
    # keep only safe characters
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def get_source_name(url: str) -> str:
    """Derive a short folder-friendly source name from a subreddit or user URL.

    Examples:
      https://www.reddit.com/r/GreekCelebs/ -> r_GreekCelebs
      https://www.reddit.com/user/ressaxxx/ -> u_ressaxxx
    """
    try:
        from urllib.parse import urlparse

        p = urlparse(url)
        path = (p.path or "").strip("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and parts[0].lower() in ("r", "user", "u"):
            key = parts[0].lower()
            name = parts[1]
            if key == "user":
                key = "u"
            return _sanitize_filename(f"{key}_{name}")
        # fallback: use hostname and first path element
        first = parts[0] if parts else p.hostname or "reddit"
        return _sanitize_filename(f"src_{first}")
    except Exception:
        return "src_unknown"


def extract_posts(json_data: Dict) -> Iterable[Dict]:
    """Return an iterable of post (child) dicts from a listing or permalink JSON.

    Each returned item is the child dict that contains the 'data' key.
    """
    posts = []
    if isinstance(json_data, dict) and "data" in json_data and "children" in json_data["data"]:
        for child in json_data["data"]["children"]:
            posts.append(child)
    elif isinstance(json_data, list):
        for item in json_data:
            if isinstance(item, dict) and "data" in item and "children" in item["data"]:
                for child in item["data"]["children"]:
                    posts.append(child)
    return posts


def fetch_posts_with_pagination(url: str, token: Optional[str], user_agent: str, paginate: bool = False, max_posts: Optional[int] = None, per_page: int = 100) -> Tuple[list, int]:
    """Fetch posts for a listing URL, optionally following pagination.

    - If `paginate` is False the function will fetch the single JSON page for `url` and
      return its posts (preserves previous behavior).
    - If `paginate` is True the function will request pages with `limit=per_page`
      and follow the `after` token until exhausted or `max_posts` is reached.

    Permalink URLs (those containing '/comments/') are always fetched only once and
    returned as before.
    """
    from urllib.parse import urlsplit, urlunsplit

    # permalink: do not paginate
    if re.search(r"/comments/", url):
        j = fetch_json(url, token, user_agent)
        return list(extract_posts(j)), 1

    # If not asked to paginate, preserve existing single-request behavior
    if not paginate:
        j = fetch_json(url, token, user_agent)
        return list(extract_posts(j)), 1

    # Build a base .json URL without querystring
    parts = urlsplit(url)
    path = (parts.path or "").rstrip("/")
    base_json = urlunsplit((parts.scheme or "https", parts.netloc or "www.reddit.com", path + ".json", "", ""))

    posts = []
    after = None
    per_page = int(per_page or 100)
    pages_fetched = 0
    while True:
        q = f"limit={per_page}"
        if after:
            q = q + f"&after={after}"
        page_url = base_json + "?" + q
        j = fetch_json(page_url, token, user_agent)
        pages_fetched += 1
        new_posts = list(extract_posts(j))
        if new_posts:
            posts.extend(new_posts)

        # check after token
        try:
            after = j.get("data", {}).get("after")
        except Exception:
            after = None

        # stop conditions
        if not after:
            break
        if max_posts and len(posts) >= int(max_posts):
            break

    if max_posts:
        return posts[: int(max_posts)], pages_fetched
    return posts, pages_fetched


def download_url(url: str, outdir: str, token: Optional[str] = None, user_agent: str = DEFAULT_USER_AGENT, filename: Optional[str] = None, target_path: Optional[str] = None) -> str:
    """Download a URL into outdir. Returns path to file or path to .failed file on failure.

    Adds User-Agent and Authorization headers when available. Tries to derive a filename from the URL
    or from Content-Disposition header.
    """
    os.makedirs(outdir, exist_ok=True)
    parsed = None
    try:
        from urllib.parse import urlparse, unquote

        parsed = urlparse(url)
    except Exception:
        parsed = None

    # default filename from URL path
    default_name = None
    url_ext = ""
    if parsed and parsed.path:
        default_name = os.path.basename(parsed.path)
        url_ext = os.path.splitext(default_name)[1] or ""
    if not default_name:
        default_name = "file"
    default_name = _sanitize_filename(unquote(default_name))

    # if a filename base (post id) was provided, use it (append extension from URL if present)
    if target_path:
        # honor explicit target path (used by retry to restore original destination)
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
        except Exception:
            pass
        dest = target_path
    elif filename:
        fname = _sanitize_filename(filename)
        if url_ext:
            dest = os.path.join(outdir, fname + url_ext)
        else:
            dest = os.path.join(outdir, fname)
    else:
        dest = os.path.join(outdir, default_name)

    headers = {"User-Agent": user_agent}

    # decide whether to include Authorization header: only send bearer token to reddit API/domains
    try:
        host = parsed.netloc.lower() if parsed else ""
    except Exception:
        host = ""
    if token and host and ("reddit.com" in host):
        headers["Authorization"] = f"bearer {token}"

    # add a Referer for reddit-hosted images which sometimes reject requests without it
    if host.endswith("preview.redd.it") or host.endswith("i.redd.it"):
        headers.setdefault("Referer", "https://www.reddit.com/")

    # unescape HTML entities (Reddit preview URLs often contain &amp;)
    url = url.replace("&amp;", "&")

    import time
    attempts = 3
    backoff = 1.0
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            with requests.get(url, stream=True, timeout=25, headers=headers) as r:
                try:
                    r.raise_for_status()
                except Exception as exc:
                    # write failed file with status info
                    failed = dest + ".failed"
                    with open(failed, "w", encoding="utf-8") as fh:
                        fh.write(f"{url}\nHTTP {r.status_code}\n{str(exc)}\n")
                        try:
                            fh.write(r.text[:2000])
                        except Exception:
                            pass
                    return failed

                # If the response is HTML (Reddit often returns an HTML page when blocked),
                # treat it as a failure and write a .failed file instead of saving it as binary.
                content_type = r.headers.get("content-type", "").lower()
                if "text/html" in content_type or "application/xhtml+xml" in content_type:
                    failed = dest + ".failed"
                    try:
                        body = r.text
                    except Exception:
                        body = "(unable to read response body)"
                    with open(failed, "w", encoding="utf-8") as fh:
                        fh.write(f"{url}\nHTTP {r.status_code}\nHTML response detected (content-type: {content_type})\n")
                        fh.write(body[:2000])
                    return failed

                # try to get filename from Content-Disposition
                cd = r.headers.get("content-disposition") or r.headers.get("Content-Disposition")
                if cd:
                    # support both filename*=UTF-8'' and plain filename
                    m = re.search(r"filename\*=[Uu][Tt][Ff]-8''([^;\n]+)", cd)
                    if m:
                        try:
                            fname = _sanitize_filename(unquote(m.group(1)))
                            dest = os.path.join(outdir, fname)
                        except Exception:
                            pass
                    else:
                        m2 = re.search(r'filename="?([^";]+)"?', cd)
                        if m2:
                            try:
                                fname = _sanitize_filename(unquote(m2.group(1)))
                                dest = os.path.join(outdir, fname)
                            except Exception:
                                pass

                # ensure unique filename if multiple files with same name exist
                base, ext = os.path.splitext(dest)
                i = 1
                while os.path.exists(dest):
                    dest = f"{base}_{i}{ext}"
                    i += 1

                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            fh.write(chunk)
                return dest
        except Exception as exc:
            last_exc = exc
            # if it's the last attempt, attempt redgifs mobile fallback once before writing .failed
            if attempt == attempts:
                try:
                    # if this was media.redgifs.com/<id>.mp4, try <id>-mobile.mp4
                    from urllib.parse import urlparse

                    p = urlparse(url)
                    if p.netloc and p.netloc.endswith("media.redgifs.com") and p.path.endswith(".mp4"):
                        name = os.path.basename(p.path)
                        base = name[:-4]
                        mobile_name = f"{base}-mobile.mp4"
                        mobile_url = f"{p.scheme}://{p.netloc}/{mobile_name}"
                        # try once
                        try:
                            with requests.get(mobile_url, stream=True, timeout=25, headers=headers) as r2:
                                r2.raise_for_status()
                                # write to same dest (ensuring unique name)
                                with open(dest, "wb") as fh2:
                                    for chunk in r2.iter_content(chunk_size=8192):
                                        if chunk:
                                            fh2.write(chunk)
                                return dest
                        except Exception:
                            pass
                except Exception:
                    pass
                failed = dest + ".failed"
                with open(failed, "w", encoding="utf-8") as fh:
                    fh.write(f"{url}\n{str(exc)}\n")
                return failed
            # otherwise sleep and retry
            time.sleep(backoff)
            backoff *= 2
            continue
    return dest

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="reddit-dl",
        description="reddit-dl: download media from reddit URLs (minimal)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --config config.json --user spez
  %(prog)s --config config.json --subreddit pics,funny
  %(prog)s --config config.json --user user1,user2 --subreddit r1,r2
  %(prog)s --config config.json "https://reddit.com/user/spez/"
        """.strip()
    )
    p.add_argument("urls", nargs="*", help="One or more reddit URLs (user, subreddit, permalink)")
    p.add_argument("--subreddit", "-r", action="append", help="Subreddit name(s) (comma-separated or repeat flag)")
    p.add_argument("--user", "-u", action="append", help="Reddit username(s) (comma-separated or repeat flag)")
    p.add_argument("--postid", "-p", action="append", help="Post ID(s) (comma-separated or repeat flag)")
    p.add_argument("--config", "-c", help="Path to config JSON file")
    p.add_argument("--retry-failed", action="store_true", help="Retry previously failed downloads")
    p.add_argument("--max-posts", type=int, default=None, help="Maximum number of posts to fetch")
    p.add_argument("--all", action="store_true", help="Fetch all posts by following pagination")
    p.add_argument("--force", action="store_true", help="Force re-download even if file exists")
    p.add_argument("--no-head-check", dest="head_check", action="store_false", help="Disable HEAD-based checks")
    p.add_argument("--save-interval", type=int, default=10, help="Persist md5 DB every N updates (default: 10)")
    p.add_argument("--partial-fingerprint", action="store_true", help="Enable partial-range fingerprinting")
    p.add_argument("--partial-size", type=int, default=65536, help="Bytes for partial fingerprint (default: 65536)")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    reddit_cfg = cfg.get("extractor", {}).get("reddit", {})
    user_agent = reddit_cfg.get("user_agent", DEFAULT_USER_AGENT)
    outdir = reddit_cfg.get("output_dir", "downloads")
    token = get_oauth_token(cfg)

    all_media = set()
    # configure logging
    log_level = logging.DEBUG if getattr(args, "debug", False) else logging.INFO
    # Omit the logger name to keep logs compact (no __main__ prefix)
    logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)-7s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    # Also write logs to a file under the output directory for persistence
    try:
        os.makedirs(outdir, exist_ok=True)
        log_path = os.path.join(outdir, "logs.txt")
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s : %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        # dedicated file-only logger so we can emit verbose messages to file without cluttering console
        file_logger = logging.getLogger("reddit_file")
        file_logger.setLevel(log_level)
        file_logger.addHandler(file_handler)
        file_logger.propagate = False
    except Exception:
        pass
    stats = {
        "pages_fetched": 0,
        "posts_processed": 0,
        "media_attempted": 0,
        "media_downloaded": 0,
        "media_skipped": 0,
        "media_failed": 0,
        "recovered": 0,
        "bytes_downloaded": 0,
        "start_time": time.time(),
    }
    # MD5 index for deduplication (SQLite-backed)
    md5_db_path = _default_md5_db_path(outdir)
    md5_sql_path = md5_db_path + ".sqlite"
    # migrate existing JSON index into sqlite if present
    try:
        idx = Md5Index(md5_sql_path)
    except Exception:
        idx = None
    # Note: legacy JSON->SQLite migration removed. If you need to import an old
    # `.md5_index.json` file, run a one-time migration tool separately.

    # control periodic persistence (sqlite commits are immediate; save_interval kept for compatibility)
    downloads_since_save = 0
    save_interval = int(args.save_interval or 10)
    partial_enabled = bool(args.partial_fingerprint)
    partial_size = int(args.partial_size or 65536)
    # cache for partial fingerprints of local files for this run: md5 -> fingerprint
    _partial_cache: Dict[str, str] = {}
    # If user asked to retry existing .failed files, process them first
    if args.retry_failed:
        # ensure outdir exists and scan for .failed files
        os.makedirs(outdir, exist_ok=True)
        failed_files = []
        # walk recursively so .failed files in per-post folders are found
        for root, _, files in os.walk(outdir):
            for fname in files:
                if fname.endswith(".failed"):
                    failed_files.append(os.path.join(root, fname))
        if failed_files:
            logging.getLogger(__name__).info("Retrying %d failed downloads from %s...", len(failed_files), outdir)
            for fpath in failed_files:
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        url = fh.readline().strip()
                except Exception:
                    continue
                if not url:
                    continue
                # infer original destination path: sibling without .failed
                orig = None
                if fpath.endswith(".failed"):
                    candidate = fpath[:-7]
                    if os.path.exists(candidate):
                        # file already exists; remove the failed marker
                        try:
                            os.remove(fpath)
                            stats["recovered"] += 1
                            logging.getLogger(__name__).info("Already present, removed failed marker: %s", candidate)
                        except Exception:
                            pass
                        continue
                    else:
                        orig = candidate
                # otherwise, fallback to writing into top-level outdir preserving previous behavior
                target = orig or os.path.join(outdir, os.path.basename(url))
                fname = os.path.basename(target)
                try:
                    from urllib.parse import urlparse

                    hostname = (urlparse(url).hostname or "") if url else ""
                    parts = hostname.split('.') if hostname else []
                    host = '.'.join(parts[-2:]) if len(parts) >= 2 else (hostname or 'unknown')
                except Exception:
                    host = 'unknown'
                logging.getLogger(__name__).info("Retrying: %s | %s", host, fname)
                try:
                    logging.getLogger('reddit_file').info(f"Retrying : {url} -> {target}")
                except Exception:
                    pass
                dest = download_url(url, outdir, token=token, user_agent=user_agent, target_path=target)
                if dest.endswith(".failed"):
                    logging.getLogger(__name__).warning("Still failed: %s | %s", host, os.path.basename(dest))
                    try:
                        logging.getLogger('reddit_file').warning(f"Still failed: {url} -> {dest}")
                    except Exception:
                        pass
                else:
                    logging.getLogger(__name__).info("Recovered: %s | %s", host, os.path.basename(dest))
                    try:
                        logging.getLogger('reddit_file').info(f"Recovered: {url} -> {dest}")
                    except Exception:
                        pass
                    stats["recovered"] += 1
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass

    # concurrency/rate can be set in config or via env vars
    concurrency = int(os.environ.get("REDDIT_DL_CONCURRENCY") or reddit_cfg.get("concurrency") or 4)
    rate = float(os.environ.get("REDDIT_DL_RATE") or reddit_cfg.get("rate") or 4.0)

    # Normalize and expand explicit flags into canonical reddit URLs
    urls_to_process = list(args.urls or [])
    # --user values map to https://www.reddit.com/user/<user>/
    if getattr(args, "user", None):
        for user_arg in args.user:
            # Support comma-separated values
            for u in user_arg.split(','):
                if u.strip():
                    uname = u.strip().lstrip("/@ ")
                    urls_to_process.append(f"https://www.reddit.com/user/{uname}/")
    # --subreddit values map to https://www.reddit.com/r/<subreddit>/
    if getattr(args, "subreddit", None):
        for sub_arg in args.subreddit:
            # Support comma-separated values
            for r in sub_arg.split(','):
                if r.strip():
                    rname = r.strip().lstrip("/ r")
                    urls_to_process.append(f"https://www.reddit.com/r/{rname}/")
    # --postid values map to https://www.reddit.com/comments/<postid>/
    if getattr(args, "postid", None):
        for post_arg in args.postid:
            # Support comma-separated values
            for pid in post_arg.split(','):
                if pid.strip():
                    pid_clean = pid.strip()
                    # if full id like t3_xxx given, accept the suffix
                    if pid_clean.startswith("t3_"):
                        pid_clean = pid_clean[3:]
                    urls_to_process.append(f"https://www.reddit.com/comments/{pid_clean}/")

    for url in urls_to_process:
        # decide whether to paginate
        paginate = bool(args.all or args.max_posts)
        try:
            posts, pages = fetch_posts_with_pagination(url, token, user_agent, paginate=paginate, max_posts=args.max_posts, per_page=100)
            stats["pages_fetched"] += pages
        except Exception as e:
            logging.getLogger(__name__).warning("Failed to fetch %s: %s", url, e)
            continue

        source_name = get_source_name(url)
        source_dir = os.path.join(outdir, source_name)
        os.makedirs(source_dir, exist_ok=True)
        # Cleanup any previously-saved per-post JSON files that are actually comments
        # (comments can appear in some listing responses and produce noisy "No media" messages).
        try:
            for fname in os.listdir(source_dir):
                if not fname.endswith('.json'):
                    continue
                fpath = os.path.join(source_dir, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8') as fh:
                        doc = json.load(fh)
                    # Heuristic: comment objects often have 'body' and 'link_id'/'parent_id'
                    if isinstance(doc, dict) and ('body' in doc and (doc.get('link_id') or doc.get('parent_id'))):
                        try:
                            os.remove(fpath)
                            try:
                                logging.getLogger('reddit_file').info(f"Removed comment metadata (no media) : {fpath}")
                            except Exception:
                                pass
                        except Exception:
                            pass
                except Exception:
                    # ignore unreadable files
                    continue
        except Exception:
            pass
        if not posts:
            logging.getLogger(__name__).info("No posts found for %s", url)
            continue

        logger = logging.getLogger(__name__)
        logger.info("Found %d posts for %s", len(posts), url)
        logger.info("Saving metadata and media to %s", source_dir)
        stats["posts_processed"] += len(posts)

        # For each post, optionally save post JSON and download its media into the source root
        # (metadata and media files will be placed directly under `source_dir`).
        # Avoid writing per-post JSON for comment nodes (they produce noisy "No media" lines).
        post_urls_map = {}
        for child in posts:
            pdata = child.get("data", {})
            post_id = pdata.get("id") or pdata.get("name") or None
            if not post_id:
                # skip anomalous entries
                continue

            # collect media for this post
            media_urls = collect_media_from_post(child)

            # Heuristic: only write per-post metadata JSON when the item looks like a submission
            # that could have media. This avoids creating JSON files for comment nodes.
            looks_like_submission = False
            try:
                # common submission keys indicating possible media or a submission
                if any(k in pdata for k in ("url", "url_overridden_by_dest", "media_metadata", "secure_media", "preview", "is_gallery")):
                    looks_like_submission = True
                # also treat items with 'link_id' pointing to a post as comments -> skip
                if pdata.get("link_id") and pdata.get("parent_id") and pdata.get("author") and not pdata.get("is_submitter"):
                    # likely a comment; don't treat as submission
                    looks_like_submission = False
            except Exception:
                looks_like_submission = bool(media_urls)

            meta_path = None
            if looks_like_submission:
                meta_path = os.path.join(source_dir, f"{_sanitize_filename(post_id)}.json")
                try:
                    with open(meta_path, "w", encoding="utf-8") as fh:
                        json.dump(pdata, fh, ensure_ascii=False, indent=2)
                except Exception as e:
                    logging.getLogger(__name__).warning("Failed to write metadata for %s: %s", post_id, e)

            if media_urls:
                # store mapping post_id -> (urls, meta_path) so we can delete meta on skip
                post_urls_map[post_id] = (list(media_urls), meta_path)

        # Download media: either parallel across posts and within posts, or sequential per post
        if post_urls_map:
            # Flatten tasks (prefix each url with its target folder and post_id) and download in parallel
            tasks = []
            for post_id, (urls, meta_path) in post_urls_map.items():
                for u in urls:
                    # folder will be source_dir; include meta_path for possible deletion on skip
                    tasks.append((source_dir, post_id, u, meta_path))

            # post_urls_map values are (urls, meta_path)
            # compute total_media by summing the length of each urls list
            total_media = sum(len(urls) for (urls, _meta) in post_urls_map.values())
            logging.getLogger(__name__).info("Downloading %d media files with concurrency=%s, rate=%s/s", total_media, concurrency, rate)
            stats["media_attempted"] += total_media
            # use thread pool but respect global rate limiter by each worker calling limiter
            limiter = TokenBucket(rate=rate)
            with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
                def worker_item_with_rate(item):
                    # item is (folder, post_id, url, meta_path)
                    try:
                        folder, post_id, u, meta_path = item
                    except Exception:
                        # backward compatibility: fallback to older 3-tuple
                        folder, post_id, u = item
                        meta_path = None
                    def _skipped_return(dest):
                        # when a media is skipped because it already exists, delete the per-post JSON
                        try:
                            if meta_path and os.path.exists(meta_path):
                                try:
                                    os.remove(meta_path)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        return folder, post_id, u, dest, True
                    nonlocal downloads_since_save
                    limiter.wait_for_token()
                    if args.force:
                        # bypass MD5/index skipping
                        dst = download_url(u, folder, token=token, user_agent=user_agent, filename=post_id)
                        if not dst.endswith('.failed'):
                            md5 = compute_md5(dst)
                            if md5 and idx:
                                norm_u = normalize_media_url(u)
                                try:
                                    idx.set_url_md5(norm_u, md5)
                                    idx.add_path_for_md5(md5, dst)
                                except Exception:
                                    pass
                        return folder, post_id, u, dst, False
                    # quick URL-based skip: if we've seen this URL before and it maps to an md5,
                    # and the md5 already exists in our index, skip downloading
                    norm_u = normalize_media_url(u)
                    existing_md5 = None
                    try:
                        if idx:
                            existing_md5 = idx.get_md5_for_url(norm_u)
                    except Exception:
                        existing_md5 = None

                    if existing_md5:
                        # find an existing file path for this md5; if found, copy into per-post folder
                        candidate_paths = []
                        try:
                            candidate_paths = idx.get_paths_for_md5(existing_md5) if idx else []
                        except Exception:
                            candidate_paths = []
                        found = None
                        for p in candidate_paths:
                            try:
                                if os.path.exists(p):
                                    found = p
                                    break
                            except Exception:
                                continue
                        if found:
                            # ensure the per-post file exists: if not, copy existing file into folder using post_id
                            try:
                                _, ext = os.path.splitext(found)
                                target_name = _sanitize_filename(post_id) + ext
                                target_path = os.path.join(folder, target_name)
                                if not os.path.exists(target_path):
                                    try:
                                        shutil.copy2(found, target_path)
                                        # record in sqlite
                                        try:
                                            idx.add_path_for_md5(existing_md5, target_path)
                                        except Exception:
                                            pass
                                        try:
                                            stats["recovered"] += 1
                                        except Exception:
                                            pass
                                        return _skipped_return(target_path)
                                    except Exception:
                                        return _skipped_return(found)
                                else:
                                    return _skipped_return(target_path)
                            except Exception:
                                return _skipped_return(found)
                        # No local file exists but md5 is known in the index — respect the index and skip re-download.
                        # Map URL -> md5 in sqlite and return skipped.
                        try:
                            if idx:
                                idx.set_url_md5(norm_u, existing_md5)
                        except Exception:
                            pass
                        return _skipped_return(folder)

                    cl = None
                    etag = None
                    # perform optional HEAD-based checks
                    if args.head_check:
                        try:
                            cl, etag = head_check(u, user_agent)
                        except Exception:
                            cl = None
                            etag = None

                    # If we have an ETag from HEAD, check if we've seen it before
                    if etag:
                        mapped = None
                        try:
                            if idx:
                                mapped = idx.get_md5_for_etag(etag)
                        except Exception:
                            mapped = None

                        if mapped:
                            candidate_paths = []
                            try:
                                candidate_paths = idx.get_paths_for_md5(mapped) if idx else []
                            except Exception:
                                candidate_paths = []
                            found = None
                            for p in candidate_paths:
                                try:
                                    if os.path.exists(p):
                                        found = p
                                        break
                                except Exception:
                                    continue
                            if found:
                                # map normalized URL to md5
                                try:
                                    if idx:
                                        idx.set_url_md5(norm_u, mapped)
                                except Exception:
                                    pass
                                # ensure per-post file exists; copy if necessary
                                try:
                                    _, ext = os.path.splitext(found)
                                    target_name = _sanitize_filename(post_id) + ext
                                    target_path = os.path.join(folder, target_name)
                                    if not os.path.exists(target_path):
                                        try:
                                            shutil.copy2(found, target_path)
                                            try:
                                                idx.add_path_for_md5(mapped, target_path)
                                            except Exception:
                                                pass
                                            try:
                                                stats["recovered"] += 1
                                            except Exception:
                                                pass
                                            return _skipped_return(target_path)
                                        except Exception:
                                            return _skipped_return(found)
                                    else:
                                        return _skipped_return(target_path)
                                except Exception:
                                    return _skipped_return(found)
                            # mapped md5 exists but no local path found: skip without creating any marker file
                            try:
                                if idx:
                                    idx.set_url_md5(norm_u, mapped)
                            except Exception:
                                pass
                            return _skipped_return(folder)
                    # If we don't have a URL or ETag match, and we have a Content-Length, try size-based match
                    if args.head_check and cl:
                        try:
                            # iterate known md5s and their paths
                            for md5, p in idx.iter_md5_paths():
                                try:
                                    if os.path.exists(p) and os.path.getsize(p) == cl:
                                        # found a file with same size; assume identical and map URL -> md5
                                        try:
                                            idx.set_url_md5(norm_u, md5)
                                        except Exception:
                                            pass
                                        if etag:
                                            try:
                                                idx.set_etag_md5(etag, md5)
                                            except Exception:
                                                pass
                                        return folder, post_id, u, p, True
                                except Exception:
                                    continue
                        except Exception:
                            pass

                    # Optional partial-range fingerprinting: fetch first N bytes and compare to local partials
                    if partial_enabled:
                        try:
                            remote_fp = None
                            try:
                                remote_fp = None
                                chunk = None
                                from hashlib import sha256
                                # attempt a ranged GET for the first partial_size bytes
                                headers = {"User-Agent": user_agent, "Range": f"bytes=0-{partial_size - 1}"}
                                r = requests.get(u, headers=headers, stream=True, timeout=20, allow_redirects=True)
                                if r.status_code in (200, 206):
                                    # read up to partial_size bytes
                                    data = b""
                                    for part in r.iter_content(chunk_size=8192):
                                        if not part:
                                            break
                                        data += part
                                        if len(data) >= partial_size:
                                            break
                                    if data:
                                        remote_fp = sha256(data[:partial_size]).hexdigest()
                            except Exception:
                                remote_fp = None
                            if remote_fp:
                                try:
                                    # lazily compute partial fingerprints for existing md5 files
                                    for md5, p in idx.iter_md5_paths():
                                        if md5 in _partial_cache:
                                            local_fp = _partial_cache[md5]
                                        else:
                                            local_fp = None
                                            try:
                                                if os.path.exists(p):
                                                    with open(p, "rb") as fh:
                                                        data = fh.read(partial_size)
                                                        from hashlib import sha256
                                                        local_fp = sha256(data).hexdigest()
                                                        _partial_cache[md5] = local_fp
                                            except Exception:
                                                local_fp = None
                                        if local_fp and local_fp == remote_fp:
                                            # match found
                                            try:
                                                idx.set_url_md5(norm_u, md5)
                                            except Exception:
                                                pass
                                            return _skipped_return(p)
                                except Exception:
                                    pass
                        except Exception:
                            pass

                    dst = download_url(u, folder, token=token, user_agent=user_agent, filename=post_id)
                    # if download succeeded, compute md5 and update db
                    if not dst.endswith('.failed'):
                        md5 = compute_md5(dst)
                        if md5 and idx:
                            try:
                                idx.set_url_md5(norm_u, md5)
                            except Exception:
                                pass
                            try:
                                idx.add_path_for_md5(md5, dst)
                            except Exception:
                                pass
                            # capture ETag if present in last HEAD or response headers (best-effort)
                            try:
                                _, resp_etag = head_check(u, user_agent)
                                if resp_etag:
                                    try:
                                        idx.set_etag_md5(resp_etag, md5)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                            # periodic checkpoint (optional)
                            downloads_since_save += 1
                            if downloads_since_save >= save_interval:
                                try:
                                    idx.checkpoint()
                                except Exception:
                                    pass
                                downloads_since_save = 0
                    return folder, post_id, u, dst, False

                futures = {ex.submit(worker_item_with_rate, item): item for item in tasks}
                for fut in as_completed(futures):
                    item = futures[fut]
                    try:
                        folder, post_id, url, dest, skipped = fut.result()
                    except Exception as e:
                        # item is (folder, post_id, url)
                        folder = item[0]
                        post_id = item[1] if len(item) > 2 else "?"
                        url = item[-1]
                        dest = os.path.join(folder, _sanitize_filename(url) + ".failed")
                        skipped = False
                        try:
                            with open(dest, "w", encoding="utf-8") as fh:
                                fh.write(f"{url}\n{str(e)}\n")
                        except Exception:
                            pass

                    # Pretty host label for logs (e.g., Redgifs, Redd.it)
                    try:
                        from urllib.parse import urlparse

                        hostname = (urlparse(url).hostname or "") if url else ""
                        lh = (hostname or "").lower()
                        if "redgifs" in lh:
                            host_label = "Redgifs"
                        elif "reddit" in lh or lh.endswith("redd.it") or "redd.it" in lh:
                            host_label = "Redd.it"
                        else:
                            parts = lh.split(".") if lh else []
                            if len(parts) >= 2:
                                sld = parts[-2]
                                tld = parts[-1]
                                # show .it tld as Redd.it style, otherwise drop common tlds
                                if tld == "it":
                                    host_label = f"{sld.capitalize()}.{tld}"
                                else:
                                    host_label = sld.capitalize()
                            else:
                                host_label = (lh or "Unknown").capitalize()
                    except Exception:
                        host_label = "Unknown"

                    if skipped:
                        logging.getLogger(__name__).info("[%s] [%s] Skipped %s", post_id, host_label, os.path.basename(dest))
                        # verbose file log with full URL -> dest
                        try:
                            logging.getLogger('reddit_file').info(f"[{post_id}] [{host_label}] Skipped already downloaded : {url} -> {dest}")
                        except Exception:
                            pass
                        stats["media_skipped"] += 1
                    elif dest.endswith(".failed"):
                        logging.getLogger(__name__).warning("[%s] [%s] Failed %s", post_id, host_label, os.path.basename(dest))
                        try:
                            logging.getLogger('reddit_file').warning(f"[{post_id}] [{host_label}] Failed to download : {url} -> {dest}")
                        except Exception:
                            pass
                        stats["media_failed"] += 1
                    else:
                        logging.getLogger(__name__).info("[%s] [%s] Downloaded %s", post_id, host_label, os.path.basename(dest))
                        try:
                            logging.getLogger('reddit_file').info(f"[{post_id}] [{host_label}] Downloaded from {url} -> {dest}")
                        except Exception:
                            pass
                        stats["media_downloaded"] += 1
                        try:
                            stats["bytes_downloaded"] += os.path.getsize(dest)
                        except Exception:
                            pass

        # update all_media set with each URL (post_urls_map items are post_id -> (urls, meta_path))
        for (pid, (urls, _meta)) in post_urls_map.items():
            for u in urls:
                all_media.add(u)

    if not all_media:
        logging.getLogger(__name__).info("No media downloaded.")
    # checkpoint and close sqlite-backed md5 index if present
    try:
        if idx:
            try:
                idx.checkpoint()
            except Exception:
                pass
            try:
                idx.close()
            except Exception:
                pass
    except Exception:
        pass
    elapsed = time.time() - stats["start_time"]
    logger = logging.getLogger(__name__)
    # format bytes with thousands separator via f-string to avoid logging format conflicts
    summary = (
        f"Summary:\n  Pages fetched: {stats['pages_fetched']}\n  Posts processed: {stats['posts_processed']}\n"
        f"  Media attempted: {stats['media_attempted']}\n  Media downloaded: {stats['media_downloaded']}\n"
        f"  Media failed: {stats['media_failed']}\n  Media skipped: {stats.get('media_skipped', 0)}\n"
        f"  Bytes downloaded: {stats['bytes_downloaded']:,}\n  Elapsed time: {elapsed:.1f}s"
    )
    logger.info(summary)


if __name__ == "__main__":
    main()