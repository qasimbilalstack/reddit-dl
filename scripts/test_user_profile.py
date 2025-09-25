#!/usr/bin/env python3
"""Simple Reddit user profile parser.

Usage:
  - Parse a local saved HTML file: `python scripts/test_user_profile.py --file scripts/reddit_user_bio_exmple/OceanwavemER.txt`
  - Fetch live page (optional): `python scripts/test_user_profile.py --user OceanwavemER`

This script extracts: display name, NSFW flag, bio/description, social links, karma and reddit age (when available in the markup), and active community count.

Dependencies: beautifulsoup4, requests (requests only required for live fetch)
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Dict, List, Optional
import os
import sys
from urllib.parse import urlsplit, urlunsplit
from reddit_dl import user_profile
import requests


def parse_profile_html(html: str) -> List[Dict[str, str]]:
    # Delegate to shared implementation
    return user_profile.parse_profile_html(html)


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def get_oauth_token_from_config(config_path: str, headers: dict | None = None) -> str:
    # Accept None config_path: discover conventional locations or build cfg from env vars
    cfg = None
    if config_path:
        try:
            cfg = load_config(config_path)
        except Exception:
            cfg = None

    if cfg is None:
        # Try conventional locations: ./config.json then ~/config.json
        try:
            local_cfg_path = os.path.join(os.getcwd(), "config.json")
            home_cfg_path = os.path.expanduser("~/config.json")
            for pth in (local_cfg_path, home_cfg_path):
                try:
                    if pth and os.path.exists(pth):
                        cfg = load_config(pth)
                        break
                except Exception:
                    continue
        except Exception:
            cfg = None

    try:
        from reddit_dl.extractor import get_oauth_token as _lib_get_oauth_token
        token = _lib_get_oauth_token(cfg or {})
        if not token:
            raise RuntimeError("Could not obtain token via reddit_dl.extractor.get_oauth_token")
        return token
    except Exception as e:
        raise RuntimeError("Unable to obtain OAuth token via reddit_dl.extractor.get_oauth_token. Ensure your config or environment contains valid Reddit OAuth credentials.") from e


def get_profile_with_token(token: str, target_user: str) -> dict:
    # Delegate to shared implementation (raw oauth JSON)
    return user_profile.fetch_user_profile(target_user, token=token, raw_oauth=True)


def fetch_user_profile(username: str, config_path: Optional[str] = None, token: Optional[str] = None, user_agent: Optional[str] = None, raw_oauth: bool = False) -> dict:
    # Acquire token if not provided then delegate to shared module
    token_local = token
    if not token_local:
        try:
            token_local = get_oauth_token_from_config(config_path, headers={"User-Agent": user_agent} if user_agent else None)
        except Exception:
            token_local = None

    if raw_oauth:
        return user_profile.fetch_user_profile(username, token=token_local, user_agent=user_agent, raw_oauth=True)
    return user_profile.fetch_user_profile(username, token=token_local, user_agent=user_agent, raw_oauth=False)


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch Reddit user profile (OAuth-first).")
    # Minimal CLI for programmatic use by reddit_dl.extractor
    p.add_argument("--user", "-u", required=True, help="Reddit username to fetch")
    p.add_argument("--config", help="Path to config.json containing oauth credentials")
    p.add_argument("--raw-oauth", action="store_true", help="Print the full OAuth JSON response and exit")
    p.add_argument("--pretty", action="store_true", help="Pretty-print human readable output instead of JSON")
    p.add_argument("--user-agent", help="Custom User-Agent to use for requests")

    args = p.parse_args()

    # For extractor integration we default to OAuth API flow. Attempt to obtain a token.
    ua = args.user_agent or None
    headers = {"User-Agent": ua} if ua else None
    try:
        token = get_oauth_token_from_config(args.config, headers=headers)
        profile_json = get_profile_with_token(token, args.user)
    except Exception as e:
        print(f"OAuth fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

    if args.raw_oauth:
        print(json.dumps(profile_json, indent=2, ensure_ascii=False))
        return

    # Build the compact output via shared helper (uses token acquired above)
    try:
        out = user_profile.fetch_user_profile(args.user, token=token, user_agent=ua, raw_oauth=False)
    except Exception as e:
        print(f"Failed to build profile output: {e}", file=sys.stderr)
        sys.exit(1)

    # Output JSON by default; pretty-print if requested
    if args.pretty:
        print("Display name:", out.get("display_name"))
        print("NSFW:", out.get("nsfw"))
        print("Bio:", out.get("bio"))
        print("Verified:", out.get("verified"))
        print("Has verified email:", out.get("has_verified_email"))
        print("Social links:")
        for s in out.get("social_links", []) or []:
            try:
                print("  -", s.get("text") or s.get("url"), "->", s.get("url"))
            except Exception:
                print("  -", s)
        print("Karma:", out.get("karma"))
        print("Post karma:", out.get("post_karma"))
        print("Comment karma:", out.get("comment_karma"))
        print("Avatar:", out.get("avatar_url"))
        print("Banner:", out.get("banner_url"))
    else:
        print(json.dumps(out, ensure_ascii=False))
    return


if __name__ == "__main__":
    main()
