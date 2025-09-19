# reddit-dl

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![Version](https://img.shields.io/badge/version-0.1-green.svg)](setup.py)

A focused Reddit media extractor and downloader built as a streamlined gallery-dl fork. Features OAuth2 authentication, intelligent deduplication, and comprehensive media extraction from Reddit users, subreddits, and individual posts.

## Table of Contents

- [Installation](#installation)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [CLI Reference](#cli-reference)
- [Examples](#examples)
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

### 3. Start Downloading

Download media from a Reddit user:

```bash
reddit-dl --config config.json "https://www.reddit.com/user/SomeUser/"
```

Files will be saved to `downloads/` with organized subfolders and detailed logs in `downloads/logs.txt`.


### Advanced Configuration Options

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
      "max_posts": 100,
      "save_interval": 10
    }
  }
}
```

### Configuration Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `client_id` | Reddit app client ID | Required |
| `client_secret` | Reddit app client secret | Required |
| `username` | Reddit username | Required |
| `password` | Reddit password | Required |
| `user_agent` | Custom user agent string | `reddit-dl/0.1` |
| `output_dir` | Download directory | `downloads` |
| `max_posts` | Default maximum posts per source | Unlimited |
| `save_interval` | MD5 database save frequency | 10 |

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
| `--force` | Force re-download existing files |
| `--retry-failed` | Retry previously failed downloads |

#### Performance Options

| Option | Description |
|--------|-------------|
| `--no-head-check` | Disable HEAD request optimization |
| `--partial-fingerprint` | Enable partial content fingerprinting |
| `--partial-size BYTES` | Bytes to fetch for fingerprinting (default: 65536) |
| `--save-interval N` | Save MD5 database every N updates (default: 10) |

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
 