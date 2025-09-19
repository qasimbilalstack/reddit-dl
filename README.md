# reddit-dl

A minimal fork of gallery-dl focused only on Reddit extraction. Includes an example oauth:reddit configuration and examples for the provided test URLs.

Usage
1. Register a Reddit "script" app at https://www.reddit.com/prefs/apps — note client ID and client secret.
2. Create config.json based on config.example.json and fill in oauth keys.
3. Run:

You can pass one or more positional Reddit URLs. Examples:

Run against a single URL (permalink, user, or subreddit):

  reddit-dl --config config.json "https://www.reddit.com/r/GreekCelebs/"

Run against multiple URLs in one invocation (space-separated):

    reddit-dl --config config.json \
      "https://www.reddit.com/user/SecretKumchie/" "https://www.reddit.com/r/GreekCelebs/"

Fetch the entire history (follow pagination) for each provided URL using `--all`:

    reddit-dl --config config.json --all \
      "https://www.reddit.com/user/SecretKumchie/" "https://www.reddit.com/r/GreekCelebs/"

Limit the number of posts fetched per source with `--max-posts` (useful for testing):

    reddit-dl --config config.json --max-posts 100 \
      "https://www.reddit.com/user/SecretKumchie/"

Notes:
- `--all` enables pagination and will fetch pages until exhausted (or until `--max-posts` is reached).
- Multiple positional URLs are processed independently; each will create a folder under your output
  directory (default `downloads/`) named like `u_<username>` or `r_<subreddit>`.
-- You can also run the module directly with `python -m reddit_dl.extractor` or install the package
  with `pip install -e .` and use the `reddit-dl` entry point.

Installation
------------

Install locally in editable mode (recommended during development):

```bash
python -m pip install -e .
```

Install from the GitHub repository (latest commit):

```bash
python -m pip install "git+https://github.com/qasimbilalstack/reddit-dl.git"
```

Use a virtual environment or pipx for isolation:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .

# or with pipx
python -m pip install --user pipx
python -m pipx ensurepath
pipx install --editable .
```

Command-line usage
------------------

The extractor exposes the following CLI signature (long form):

```
reddit-dl: download media from reddit URLs (minimal)

positional arguments:
  urls                  One or more reddit URLs (user, subreddit, permalink)

options:
  -h, --help                    show this help message and exit
  --config CONFIG, -c CONFIG    Path to config JSON (optional)
  --retry-failed                Retry previously failed downloads from the output directory
  --max-posts MAX_POSTS         Maximum number of posts to fetch (when paginating).
  --all                         Fetch all posts by following pagination until exhausted.
  --force                       Force re-download even if MD5/index indicates file exists.
  --no-head-check               Disable HEAD-based checks (enabled by default)
  --save-interval SAVE_INTERVAL Persist md5 DB every N md5 updates (default: 10)
  --partial-fingerprint         Enable optional partial-range fingerprinting to strengthen skip heuristics
  --partial-size PARTIAL_SIZE   Number of bytes to fetch for partial fingerprint (default: 65536)
  --debug                       Enable debug logging
```

You can run the same via the installed entry point `reddit-dl` or directly with the module:

```bash
reddit-dl --config config.json --max-posts 50 "https://www.reddit.com/user/SomeUser/"
# or
python -m reddit_dl.extractor --config config.json --all "https://www.reddit.com/r/SomeSub/"
```

Most commonly used options:
- `--config CONFIG` : Path to `config.json` containing OAuth keys.
- `--max-posts N` : Limit number of posts fetched per source (useful for testing).
- `--all` : Follow pagination and fetch the entire history for each source.
- `--force` : Force re-download even if dedupe indicates file exists.
- `--no-head-check` : Skip HEAD/ETag checks (may cause unnecessary downloads).
- `--partial-fingerprint` / `--partial-size` : Enable partial-range fingerprinting heuristics.
- `--debug` : Enable verbose debug logging.


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


License: see original gallery-dl for licensing. This repo is intended as a focused extractor for Reddit.
