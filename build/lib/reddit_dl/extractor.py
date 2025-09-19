"""Minimal Reddit extractor for reddit-dl

- supports unauthenticated requests or script-type OAuth2 (password grant)
- reads config JSON with oauth keys (see config.example.json)
- handles user pages, subreddits and permalink (comment/post) URLs
- collects media URLs (images, preview, direct links) and optionally downloads them
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
from typing import Dict, Optional, Set
import requests

REDDIT_OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
DEFAULT_USER_AGENT = "reddit-dl/0.1 (by /u/yourusername)"

def load_config(path: Optional[str]) -> Dict:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)

def get_oauth_token(cfg: Dict) -> Optional[str]:
    reddit_cfg = cfg.get("extractor", {}).get("reddit", {})
    oauth = reddit_cfg.get("oauth") or {}
    client_id = oauth.get("client_id")
    client_secret = oauth.get("client_secret")
    username = oauth.get("username")
    password = oauth.get("password")
    if not (client_id and client_secret and username and password):
        return None
    auth = requests.auth.HTTPBasicAuth(client_id, client_secret)
    data = {"grant_type": "password", "username": username, "password": password}
    headers = {"User-Agent": reddit_cfg.get("user_agent", DEFAULT_USER_AGENT)}
    r = requests.post(REDDIT_OAUTH_TOKEN_URL, auth=auth, data=data, headers=headers, timeout=10)
    r.raise_for_status()
    token = r.json().get("access_token")
    return token

def fetch_json(url: str, token: Optional[str], user_agent: str) -> Dict:
    headers = {"User-Agent": user_agent}
    if token:
        headers["Authorization"] = f"bearer {token}"
    # Reddit JSON endpoints: append .json where appropriate
    if not url.endswith(".json"):
        # allow passing permalink or listing URL
        if re.search(r"/comments/|/user/|/r/", url):
            url = url.rstrip("/") + ".json"
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()

def collect_media_from_post(post: Dict) -> Set[str]:
    urls = set()
    data = post.get("data", {})
    # common fields that might contain media
    for key in ("url_overridden_by_dest", "url", "media_metadata"):
        if key in data:
            if key == "media_metadata" and isinstance(data[key], dict):
                # gallery: media metadata entries
                for k, v in data[key].items():
                    if isinstance(v, dict):
                        s = v.get("s", {}).get("u")
                        if s:
                            urls.add(s)
            else:
                u = data.get(key)
                if u:
                    urls.add(u)
    # preview images
    preview = data.get("preview", {})
    images = preview.get("images", [])
    for img in images:
        source = img.get("source", {}).get("url")
        if source:
            # urls are HTML-escaped
            urls.add(source.replace("&amp;", "&"))
    return urls

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

def download_url(url: str, outdir: str) -> str:
    os.makedirs(outdir, exist_ok=True)
    filename = os.path.basename(url.split("?")[0]) or "file"
    dest = os.path.join(outdir, filename)
    try:
        with requests.get(url, stream=True, timeout=20) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        fh.write(chunk)
    except Exception:
        # on failure, write the URL to a .failed file for debugging
        failed = dest + ".failed"
        with open(failed, "w", encoding="utf-8") as fh:
            fh.write(url)
        return failed
    return dest

def main(argv=None):
    p = argparse.ArgumentParser(description="reddit-dl: download media from reddit URLs (minimal)")
    p.add_argument("urls", nargs="+", help="One or more reddit URLs (user, subreddit, permalink)")
    p.add_argument("--config", "-c", help="Path to config JSON (optional)")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    reddit_cfg = cfg.get("extractor", {}).get("reddit", {})
    user_agent = reddit_cfg.get("user_agent", DEFAULT_USER_AGENT)
    outdir = reddit_cfg.get("output_dir", "downloads")
    token = get_oauth_token(cfg)

    all_media = set()
    for url in args.urls:
        try:
            json_data = fetch_json(url, token, user_agent)
        except Exception as e:
            print(f"Failed to fetch {url}: {e}", file=sys.stderr)
            continue
        media = parse_listing(json_data)
        if not media:
            print(f"No media found for {url}")
            continue
        print(f"Found {len(media)} media items for {url}:")
        for m in media:
            print("  ", m)
        for m in media:
            dest = download_url(m, outdir)
            print(f"Downloaded {m} -> {dest}")
        all_media.update(media)

    if not all_media:
        print("No media downloaded.")

if __name__ == "__main__":
    main()