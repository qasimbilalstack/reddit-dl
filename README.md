# reddit-dl

A minimal fork of gallery-dl focused only on Reddit extraction. Includes an example oauth:reddit configuration and examples for the provided test URLs.

Usage
1. Register a Reddit "script" app at https://www.reddit.com/prefs/apps — note client ID and client secret.
2. Create config.json based on config.example.json and fill in oauth keys.
3. Run:

    python -m reddit_dl.extractor --config config.json "https://www.reddit.com/r/GreekCelebs/"

Example config (config.example.json)

```json
{
  "extractor": {
    "reddit": {
      "oauth": {
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET",
        "username": "YOUR_REDDIT_USERNAME",
        "password": "YOUR_REDDIT_PASSWORD"
      }
    }
  }
}
```

Test URLs:
- https://www.reddit.com/user/SecretKumchie/
- https://www.reddit.com/r/GreekCelebs/
- https://www.reddit.com/user/ressaxxx/comments/1nhy77z/front_or_back/

License: see original gallery-dl for licensing. This repo is intended as a focused extractor for Reddit.

## Changes: SQLite MD5 index

This version of `reddit-dl` replaces the previous JSON-backed MD5 index with a small
SQLite-backed index (WAL mode) so updates are cheap and durable. The new index file is
created next to the old JSON index as:

```
downloads/.md5_index.json.sqlite
```

Why SQLite?

- WAL-enabled SQLite provides safe, concurrent-friendly updates from multiple threads
  without rewriting a large JSON file on each update.
- It's lightweight, widely available, easy to inspect, and requires no external services.

What changed in behaviour

- On first run the extractor attempts to migrate an existing `downloads/.md5_index.json`
  into the new sqlite DB. The migration is a no-op if the sqlite DB already contains
  entries.
- The index stores three mappings:
  - `url_to_md5` (normalized media URL -> md5)
  - `md5_to_paths` (md5 -> set of local file paths)
  - `etag_to_md5` (HTTP ETag -> md5)
- Updates now go directly into SQLite. Periodic JSON writes are replaced by lightweight
  WAL checkpointing; the CLI option `--save-interval` remains available and controls
  how often the extractor performs a checkpoint (for compatibility).

Inspecting the SQLite DB

- VS Code: install a SQLite extension (e.g. "SQLite" or "SQLite Viewer") and open
  `downloads/.md5_index.json.sqlite` to browse tables and run queries.
- CLI (sqlite3 client):

```
sqlite3 downloads/.md5_index.json.sqlite ".schema"
sqlite3 downloads/.md5_index.json.sqlite "SELECT url, md5 FROM url_to_md5 LIMIT 10;"
sqlite3 downloads/.md5_index.json.sqlite "SELECT md5, path FROM md5_to_paths LIMIT 10;"
```

Compatibility and safety

- The migration preserves the original JSON index file (it is **not** deleted)
  so you can verify the sqlite DB before removing the JSON file manually.
- `md5_to_paths` uses a composite primary key (md5, path) to prevent duplicate entries.

Next improvements you may want

- Move to a content-addressed store: place canonical files under
  `downloads/content/<md5><ext>` and hardlink into per-post folders. This saves
  disk space and simplifies md5->path mapping.
- For multi-process or higher scale usage consider a specialized KV store (LMDB,
  RocksDB) or a centralized service depending on your deployment.

If you'd like, I can implement the content-addressed store, add a small DB-export
utility, or remove the legacy JSON after verifying the migration.
