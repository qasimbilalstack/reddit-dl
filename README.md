# Reddit-dl

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![Version](https://img.shields.io/badge/version-0.1-green.svg)](setup.py)

 focused fork of gallery-dl — that uses OAuth2 for secure API access, smart SQLite-backed deduplication to avoid re-downloading, and robust extraction across users, subreddits, and individual posts. It’s built for speed (concurrent workers + polite rate-limiting) and bandwidth efficiency (HEAD/ETag and partial-range checks), while keeping logs and output organized so your downloads stay easy to manage.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Configuration](#configuration) 
- [CLI Reference](#cli-reference)
- [Examples](#examples)
- [Output Structure](#output-structure)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Features

- **OAuth2 Authentication** - Secure Reddit API access using script app credentials
- **Smart Deduplication** - Persistent SQLite-based index prevents duplicate downloads
- **Optimized Downloads** - HEAD/ETag/partial-range checks minimize bandwidth usage
- **Gallery Support** - Automatic expansion and host-specific URL normalization
- **Flexible Output** - Organized downloads with customizable directory structure
- **Comprehensive Logging** - Detailed audit trails for all download activities
- **High performance - Parallel, rate-limited downloads for maximum speed without hammering servers.

## Installation

### Requirements

- Python 3.8 or higher
- `requests` library (automatically installed)

### Development Installation (Recommended)

For local development with editable installation:

```bash
git clone https://github.com/qasimbilalstack/reddit-dl.git
cd reddit-dl
python -m pip install -e .
```

### Direct Installation from GitHub

Install the latest version directly:

```bash
python -m pip install "git+https://github.com/qasimbilalstack/reddit-dl.git"
```

### Virtual Environment Installation

Recommended approach to avoid dependency conflicts:

```bash
# Create and activate virtual environment
python -m venv reddit-dl-env
source reddit-dl-env/bin/activate  # On Windows: reddit-dl-env\Scripts\activate

# Install reddit-dl
python -m pip install -e .
```

### Using pipx (Isolated Installation)

Install as an isolated command-line tool:

```bash
python -m pip install --user pipx
python -m pipx ensurepath
pipx install git+https://github.com/qasimbilalstack/reddit-dl.git
```

### Running Without Installation

Execute directly as a Python module:

```bash
python -m reddit_dl.extractor --config config.json <urls>
```

## Quickstart

### 1. Create Reddit Application

1. Visit [Reddit App Preferences](https://www.reddit.com/prefs/apps)
2. Click "Create App" or "Create Another App"
3. Select "script" as the application type
4. Note your **client ID** (under the app name) and **client secret**

### 2. Configure Authentication

Copy the example configuration and add your credentials:

```bash
cp config.example.json config.json
```

Edit `config.json` with your Reddit app credentials:

### 3. Start Downloading

Download media from a Reddit user:

```bash
reddit-dl --config config.json "https://www.reddit.com/user/SomeUser/"
```

Files will be saved to `downloads/` with organized subfolders and detailed logs in `downloads/logs.txt`.


## Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `client_id` | Reddit app client ID | Required |
| `client_secret` | Reddit app client secret | Required |
| `username` | Reddit username | Required |
| `password` | Reddit password | Required |
| `user_agent` | Custom user agent string | `reddit-dl/0.1` |
| `output_dir` | Download directory | `downloads` |
| `token_cache` | Path to OAuth token cache file | `~/.reddit_dl_tokens.json` |
| `max_posts` | Default maximum posts per source | Unlimited |
| `default_max_posts` | Default max posts when no --max-posts or --all | 1000 |
| `md5_save_interval` | MD5/index checkpoint frequency (downloads between saves) | 10 |
| `parallel_downloads` | Number of parallel downloads | 4 |
| `requests_per_second` | Rate limit for download requests (per second) | 4.0 |

Recommended conservative presets (choose one based on your environment):

- Gentle (very low load): `parallel_downloads: 1`, `requests_per_second: 1.0`
- Conservative (recommended): `parallel_downloads: 2`, `requests_per_second: 1.0`
- Balanced (default): `parallel_downloads: 4`, `requests_per_second: 4.0`

Configuration example all available options:

```json
{
  "extractor": {
    "reddit": {
      "oauth": {
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET",
        "username": "YOUR_REDDIT_USERNAME",
        "password": "YOUR_REDDIT_PASSWORD"
      },
      "user_agent": "reddit-dl/0.1 by YOUR_USERNAME",
  "output_dir": "downloads",
  "md5_save_interval": 10,
      "token_cache": "~/.reddit_dl_tokens.json",
      "default_max_posts": 1000,
      "parallel_downloads": 2,
      "requests_per_second": 1.0
    }
  }
}
```
```

### Security Considerations

- Store configuration files securely and never commit credentials to version control
- Consider using environment variables for sensitive data in production
- Regularly rotate Reddit application credentials
- Follow your organization's security policies for credential management

## CLI Reference

### Usage

```bash
reddit-dl [OPTIONS] URLS...
```

### Positional Arguments

**`urls`** - One or more Reddit URLs to process

Supported URL formats:
- User pages: `https://www.reddit.com/user/USERNAME/`
- Subreddits: `https://www.reddit.com/r/SUBREDDIT/`
- Individual posts: `https://www.reddit.com/r/SUBREDDIT/comments/POST_ID/`
- Shortened URLs: `https://redd.it/POST_ID`

### Options

#### General Options

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help message and exit |
| `-c, --config CONFIG` | Path to configuration JSON file |
| `--debug` | Enable debug logging output |

#### Source Selection

| Option | Description |
|--------|-------------|
| `-u, --user USER` | Reddit username(s) to fetch (comma-separated or repeat flag) |
| `-r, --subreddit SUBREDDIT` | Subreddit name(s) to fetch (comma-separated or repeat flag) |
| `-p, --postid POSTID` | Post ID(s) to fetch (comma-separated or repeat flag) |
#### Download Control

| Option | Description |
|--------|-------------|
| `--max-posts MAX_POSTS` | Maximum number of posts to fetch |
| `--all` | Fetch all available posts (follow pagination) |
| `--per-page N` | Number of posts to request per page when paginating (default: 100, max: 100) |
| `--sort {hot,new,top,rising,best}` | Listing sort order to request from Reddit (default: new) |
| `--force` | Force re-download existing files |
| `--retry-failed` | Retry previously failed downloads |

#### Performance Options

| Option | Description |
|--------|-------------|
| `--no-head-check` | Disable HEAD request optimization |
| `--partial-fingerprint` | Enable partial content fingerprinting |
| `--partial-size BYTES` | Bytes to fetch for fingerprinting (default: 65536) |
| `--save-interval N` | Save MD5 database every N updates (default: 10) |

#### Content Control

| Option | Description |
|--------|-------------|
| `--no-save-meta` | Do not write per-post metadata JSON files (saves disk and time) |
| `--comments` | Fetch comments in addition to submissions (disabled by default). Without this flag only submissions are fetched (uses /submitted/ URLs) |

## Examples

### Basic Usage

Download recent posts from a user:
```bash
reddit-dl --config config.json "https://www.reddit.com/user/SomeUser/"
# Or using the --user flag:
reddit-dl --config config.json --user SomeUser
```

Download from a subreddit:
```bash
reddit-dl --config config.json "https://www.reddit.com/r/earthporn/"
# Or using the --subreddit flag:
reddit-dl --config config.json --subreddit earthporn

# Download top posts from a subreddit:
reddit-dl --config config.json --sort top --subreddit earthporn
```

Download a specific post:
```bash
reddit-dl --config config.json "https://www.reddit.com/r/pics/comments/abc123/..."
# Or using the --postid flag:
reddit-dl --config config.json --postid abc123
```

### Advanced Usage

Download all available posts from multiple sources:
```bash
reddit-dl --config config.json --all \
  "https://www.reddit.com/user/User1/" \
  "https://www.reddit.com/r/subreddit1/" \
  "https://www.reddit.com/r/subreddit2/"
# Or using flags (can mix and match):
reddit-dl --config config.json --all \
  --user User1,User2 \
  --subreddit subreddit1,subreddit2
```

Download from multiple users and subreddits:
```bash
# Using comma-separated lists (recommended):
reddit-dl --config config.json \
  --user User1,User2,User3 \
  --subreddit pics,funny,aww \
  --postid abc123,def456

# Or using repeated flags:
reddit-dl --config config.json \
  --user User1 --user User2 \
  --subreddit pics --subreddit funny \
  --postid abc123 --postid def456
```

Limit downloads and enable debug logging:
```bash
reddit-dl --config config.json --max-posts 50 --debug \
  "https://www.reddit.com/user/SomeUser/"
# Or with flags:
reddit-dl --config config.json --max-posts 50 --debug --user SomeUser
```

Force re-download with custom fingerprinting:
```bash
reddit-dl --config config.json --force --partial-fingerprint \
  "https://www.reddit.com/user/SomeUser/"
```

Retry failed downloads from previous sessions:
```bash
reddit-dl --config config.json --retry-failed
```

Download with custom sort order and pagination:
```bash
# Download top posts with custom page size
reddit-dl --config config.json --sort top --per-page 50 \
  "https://www.reddit.com/r/earthporn/"

# Download hot posts without metadata JSON files
reddit-dl --config config.json --sort hot --no-save-meta \
  "https://www.reddit.com/user/SomeUser/"

# Download only submissions (comments disabled by default) from multiple users
reddit-dl --config config.json \
  --user User1,User2,User3
```

### Batch Processing

Process multiple URLs from a file:
```bash
# Create URL list
cat > urls.txt << EOF
https://www.reddit.com/user/User1/
https://www.reddit.com/user/User2/
https://www.reddit.com/r/subreddit1/
EOF

# Process all URLs
xargs -I {} reddit-dl --config config.json {} < urls.txt
```

Process multiple sources using flags:
```bash
# Download from multiple users and subreddits in one command (recommended):
reddit-dl --config config.json \
  --user User1,User2,User3 \
  --subreddit pics,funny,aww

# Or using repeated flags:
reddit-dl --config config.json \
  --user User1 --user User2 --user User3 \
  --subreddit pics --subreddit funny --subreddit aww

# Mix URLs and flags:
reddit-dl --config config.json \
  "https://www.reddit.com/user/SpecialUser/" \
  --subreddit earthporn,wallpapers \
  --postid abc123,def456
```
### Output Structure

Downloaded files are organized as follows:
```
downloads/
├── logs.txt                 # Comprehensive download logs
├── u_USERNAME/              # User downloads
│   ├── POST_ID.jpg         # Media files
│   ├── POST_ID.json        # Metadata
│   └── POST_ID_1.jpg       # Additional media from galleries
└── r_SUBREDDIT/            # Subreddit downloads
    ├── POST_ID.mp4
    ├── POST_ID.json
    └── ...
```

## Troubleshooting

### Common Issues

#### Command Not Found
```bash
reddit-dl: command not found
```
**Solutions:**
- Ensure virtual environment is activated: `source venv/bin/activate`
- Verify installation: `pip list | grep reddit-dl`
- Check PATH configuration for pipx installations
- Use module execution: `python -m reddit_dl.extractor`

#### Authentication Errors
```
HTTP 403: Forbidden
```
**Solutions:**
- Verify Reddit app credentials in `config.json`
- Ensure app type is set to "script" in Reddit preferences
- Check username and password are correct
- Confirm client ID and secret are accurate

#### Download Issues
```
Files appear to re-download unnecessarily
```
**Solutions:**
- Check `downloads/logs.txt` for detailed information
- Try `--no-head-check` to disable optimization
- Verify MD5 database integrity
- Use `--debug` for verbose output

#### Performance Problems
```
Downloads are slow or timing out
```
**Solutions:**
- Reduce `--max-posts` for testing
- Enable `--partial-fingerprint` for better deduplication
- Try `--no-save-meta` to reduce disk I/O
- Use `--per-page` with smaller values (e.g., 25) for better rate limiting
- Check network connectivity
- Monitor Reddit API rate limits

### Debug Mode

Enable comprehensive logging:
```bash
reddit-dl --config config.json --debug "https://www.reddit.com/user/SomeUser/"
```

This provides detailed information about:
- Authentication status
- URL processing
- File deduplication decisions
- Download progress
- Error conditions

### Log Analysis

Check `downloads/logs.txt` for audit trails:
```bash
# View recent activity
tail -f downloads/logs.txt

# Search for errors
grep -i error downloads/logs.txt

# Check specific user downloads
grep "u_SomeUser" downloads/logs.txt
```

### Getting Help

If you encounter issues:

1. Enable debug mode and check logs
2. Verify configuration against `config.example.json`
3. Test with a small `--max-posts` value
4. Check Reddit app settings and permissions
5. Review GitHub issues for similar problems
6. Create a new issue with debug output

## Contributing

We welcome contributions! Please follow these guidelines:

### Development Setup

1. Fork the repository
2. Clone your fork locally
3. Create a virtual environment
4. Install in development mode

```bash
git clone https://github.com/YOUR_USERNAME/reddit-dl.git
cd reddit-dl
python -m venv venv
source venv/bin/activate
pip install -e .
```

### Code Standards

- Follow PEP 8 style guidelines
- Add docstrings for public functions
- Include type hints where appropriate
- Write descriptive commit messages

### Testing

- Test changes with various Reddit URL types
- Verify OAuth authentication works
- Check deduplication functionality
- Test edge cases and error conditions

### Pull Request Process

1. Create a feature branch from `main`
2. Make focused, atomic commits
3. Include tests for new functionality
4. Update documentation as needed
5. Submit pull request with clear description

### Issue Reporting

When reporting bugs, include:
- Python version and operating system
- Full command used and configuration
- Complete error output with `--debug`
- Steps to reproduce the issue

## License

This project is derived from [gallery-dl](https://github.com/mikf/gallery-dl) and maintains compatibility with its licensing. The original gallery-dl project is licensed under the GNU General Public License v2.0.

### License Details

- This project: GPL-2.0 License (following gallery-dl)
- Dependencies: Various licenses (see requirements)
- Reddit API: Subject to Reddit's Terms of Service

### Attribution

Special thanks to the gallery-dl project and its contributors for providing the foundation for this focused Reddit extractor.

For complete license text, see the [LICENSE](LICENSE) file in the repository.
 
