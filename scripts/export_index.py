#!/usr/bin/env python3
"""Export the sqlite MD5 index to JSON or CSV for inspection.

Usage: python scripts/export_index.py --db downloads/.md5_index.json.sqlite --out outdir [--format json|csv]
"""
import argparse
import json
import os
import csv
import sqlite3
from typing import List, Tuple


def rows(conn: sqlite3.Connection, sql: str) -> List[Tuple]:
    cur = conn.execute(sql)
    return cur.fetchall()


def export_json(conn: sqlite3.Connection, outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    # url_to_md5
    urows = rows(conn, "SELECT url, md5 FROM url_to_md5")
    with open(os.path.join(outdir, "url_to_md5.json"), "w", encoding="utf-8") as fh:
        json.dump({u: m for (u, m) in urows}, fh, ensure_ascii=False, indent=2)

    # md5_to_paths
    mrows = rows(conn, "SELECT md5, path FROM md5_to_paths")
    mdict = {}
    for md5, p in mrows:
        mdict.setdefault(md5, []).append(p)
    with open(os.path.join(outdir, "md5_to_paths.json"), "w", encoding="utf-8") as fh:
        json.dump(mdict, fh, ensure_ascii=False, indent=2)

    # etag_to_md5
    erows = rows(conn, "SELECT etag, md5 FROM etag_to_md5")
    with open(os.path.join(outdir, "etag_to_md5.json"), "w", encoding="utf-8") as fh:
        json.dump({e: m for (e, m) in erows}, fh, ensure_ascii=False, indent=2)


def export_csv(conn: sqlite3.Connection, outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "url_to_md5.csv"), "w", newline='', encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["url", "md5"])
        for u, m in rows(conn, "SELECT url, md5 FROM url_to_md5"):
            w.writerow([u, m])

    with open(os.path.join(outdir, "md5_to_paths.csv"), "w", newline='', encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["md5", "path"])
        for md5, p in rows(conn, "SELECT md5, path FROM md5_to_paths"):
            w.writerow([md5, p])

    with open(os.path.join(outdir, "etag_to_md5.csv"), "w", newline='', encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["etag", "md5"])
        for e, m in rows(conn, "SELECT etag, md5 FROM etag_to_md5"):
            w.writerow([e, m])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="downloads/.md5_index.json.sqlite")
    p.add_argument("--out", default="out_index")
    p.add_argument("--format", choices=("json", "csv"), default="json")
    args = p.parse_args()

    if not os.path.exists(args.db):
        print("DB not found:", args.db)
        raise SystemExit(1)

    conn = sqlite3.connect(args.db)
    try:
        if args.format == "json":
            export_json(conn, args.out)
        else:
            export_csv(conn, args.out)
    finally:
        conn.close()

    print("Exported index to:", args.out)


if __name__ == '__main__':
    main()
