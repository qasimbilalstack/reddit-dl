"""User profile helpers for reddit-dl.

Provides a programmatic `fetch_user_profile` function that fetches a Reddit
user profile (requires an OAuth token) and returns a compact dict used by the
CLI and the extractor.
"""
from __future__ import annotations

from typing import Dict, List, Optional
import html as _html
from urllib.parse import urlsplit, urlunsplit
from bs4 import BeautifulSoup
import json
import requests


def _normalize_social_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
    except Exception:
        raise
    scheme = p.scheme or "https"
    if scheme not in ("http", "https"):
        scheme = "https"
    return urlunsplit(("https", p.netloc or p.path, p.path or "", "", ""))


def _clean_image_url(url: str) -> str:
    if not url:
        return url
    try:
        u = _html.unescape(url.strip())
        p = urlsplit(u)
        scheme = p.scheme or "https"
        if scheme not in ("http", "https"):
            scheme = "https"
        return urlunsplit((scheme, p.netloc, p.path, "", ""))
    except Exception:
        return url


def parse_profile_html(html: str) -> List[Dict[str, str]]:
    links: List[Dict[str, str]] = []
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return links

    seen = set()
    try:
        for ft in soup.find_all(lambda t: (t.name and t.name.lower() == "faceplate-tracker") or t.has_attr("data-faceplate-tracking-context")):
            try:
                ctx = ft.get("data-faceplate-tracking-context")
                if not ctx or not isinstance(ctx, str):
                    continue
                raw_ctx = _html.unescape(ctx)
                jctx = json.loads(raw_ctx)
                sl = jctx.get("social_link") or jctx.get("socialLink") or None
                if isinstance(sl, dict):
                    url = sl.get("url") or sl.get("link")
                    name = sl.get("name") or sl.get("title") or url or ""
                    if url and isinstance(url, str):
                        try:
                            u = _normalize_social_url(url)
                        except Exception:
                            u = None
                        if u and "reddit" not in u.lower() and u not in seen:
                            seen.add(u)
                            links.append({"url": u, "text": name})
            except Exception:
                continue
    except Exception:
        pass

    try:
        if not links:
            headings = soup.find_all(lambda tag: tag.name in ("h2", "h3") and "Social Links" in tag.get_text())
            for head in headings:
                parent = head.find_next_sibling() or head.parent
                for a in parent.find_all("a", href=True):
                    href = a["href"].strip()
                    text = a.get_text(separator=" ", strip=True) or href
                    try:
                        u = _normalize_social_url(href)
                    except Exception:
                        u = None
                    if u and "reddit" not in u.lower() and u not in seen:
                        seen.add(u)
                        links.append({"url": u, "text": text})
    except Exception:
        pass

    return links


def fetch_user_profile(username: str, token: str, user_agent: Optional[str] = None, raw_oauth: bool = False) -> dict:
    """Fetch a user's profile using a provided OAuth token.

    - `token` must be a valid bearer token (string).
    - When `raw_oauth` is True, returns the raw `/about` JSON from Reddit.
    - Otherwise returns the compact `out` dict used by the CLI/extractor.
    """
    if not token:
        raise RuntimeError("OAuth token required to fetch profile")

    headers = {"Authorization": f"bearer {token}", "User-Agent": user_agent or "reddit-profile-parser/0.1 (+https://example)"}
    resp = requests.get(f"https://oauth.reddit.com/user/{username}/about", headers=headers, timeout=15)
    resp.raise_for_status()
    j = resp.json()
    if raw_oauth:
        return j

    data = j.get("data", {})
    avatar_raw = data.get("icon_img") or data.get("subreddit", {}).get("icon_img")
    banner_raw = data.get("subreddit", {}).get("banner_img") or data.get("subreddit", {}).get("banner_background_image")

    out = {
        "display_name": data.get("name"),
        "nsfw": bool(data.get("subreddit", {}).get("over_18")),
        "bio": data.get("subreddit", {}).get("public_description") or data.get("subreddit", {}).get("description"),
        "verified": data.get("verified"),
        "has_verified_email": data.get("has_verified_email"),
        "social_links": [],
        "karma": data.get("total_karma"),
        "post_karma": data.get("link_karma"),
        "comment_karma": data.get("comment_karma"),
        "avatar_url": _clean_image_url(avatar_raw) if avatar_raw else None,
        "banner_url": _clean_image_url(banner_raw) if banner_raw else None,
        "reddit_age": None,
        "active_in_count": data.get("subreddit", {}).get("accounts_active") or data.get("subreddit", {}).get("active_user_count") or None,
    }

    # fetch HTML to extract social links
    try:
        headers_html = {"Authorization": f"bearer {token}", "User-Agent": (user_agent or "reddit-profile-parser/0.1 (+https://example)"), "Accept": "text/html"}
        resp_html = requests.get(f"https://www.reddit.com/user/{username}/", headers=headers_html, timeout=15)
        resp_html.raise_for_status()
        html = resp_html.text
        social_links = parse_profile_html(html)
    except Exception:
        social_links = []

    out["social_links"] = social_links
    try:
        domains = set()
        for s in out["social_links"]:
            try:
                p = urlsplit(s.get("url") or "")
                host = (p.hostname or p.netloc or "")
                if host and host.startswith("www."):
                    host = host[4:]
                s["domain"] = host or None
                if host:
                    domains.add(host)
            except Exception:
                s["domain"] = None
        out["social_domains"] = sorted(domains)
    except Exception:
        out["social_domains"] = []

    return out
