# reddit-dl

A minimal fork of gallery-dl focused only on Reddit extraction. Includes an example oauth:reddit configuration and examples for the provided test URLs.

Usage
1. Register a Reddit "script" app at https://www.reddit.com/prefs/apps — note client ID and client secret.
2. Create config.json based on config.example.json and fill in oauth keys.
3. Run:

You can pass one or more positional Reddit URLs. Examples:

Run against a single URL (permalink, user, or subreddit):

    python -m reddit_dl.extractor --config config.json "https://www.reddit.com/r/GreekCelebs/"

Run against multiple URLs in one invocation (space-separated):

    python -m reddit_dl.extractor --config config.json \
      "https://www.reddit.com/user/SecretKumchie/" "https://www.reddit.com/r/GreekCelebs/"

Fetch the entire history (follow pagination) for each provided URL using `--all`:

    python -m reddit_dl.extractor --config config.json --all \
      "https://www.reddit.com/user/SecretKumchie/" "https://www.reddit.com/r/GreekCelebs/"

Limit the number of posts fetched per source with `--max-posts` (useful for testing):

    python -m reddit_dl.extractor --config config.json --max-posts 100 \
      "https://www.reddit.com/user/SecretKumchie/"

Notes:
- `--all` enables pagination and will fetch pages until exhausted (or until `--max-posts` is reached).
- Multiple positional URLs are processed independently; each will create a folder under your output
  directory (default `downloads/`) named like `u_<username>` or `r_<subreddit>`.
- You can also run the module directly with `python -m reddit_dl.extractor` or install the package
  with `pip install -e .` and use the `reddit-dl` entry point.

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
