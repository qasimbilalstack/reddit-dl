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
