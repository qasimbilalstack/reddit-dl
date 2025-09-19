#!/usr/bin/env python3
"""Simple script to report MD5 index contents (skipped media summary).

Usage: python scripts/media_skipped.py [--db downloads/.md5_index.json]
"""
import argparse
import json
import os

p = argparse.ArgumentParser()
p.add_argument("--db", default="downloads/.md5_index.json")
args = p.parse_args()
path = args.db
if not os.path.exists(path):
    print("No MD5 DB found at", path)
    raise SystemExit(1)
with open(path, "r", encoding="utf-8") as fh:
    j = json.load(fh)
urls = j.get("url_to_md5", {})
md5s = j.get("md5_to_paths", {})
print(f"URLs in index: {len(urls)}")
print(f"Unique contents (md5): {len(md5s)}")
# Print a short sample
print("\nSample entries:")
for i, (u, m) in enumerate(urls.items()):
    print(f"{u} -> {m}")
    if i >= 20:
        break
