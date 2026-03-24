# Stack Research: YouTube Monthly Analytics Report

**Confidence:** HIGH (versions confirmed from locally installed packages in this repo)

## Confirmed Installed Versions (from this environment)

| Package | Version | Purpose |
|---------|---------|---------|
| `google-api-python-client` | 2.188.0 | YouTube Analytics API v2 + Data API v3 |
| `google-auth` | 2.48.0 | OAuth2 credential management |
| `google-auth-oauthlib` | 1.2.4 | OAuth2 flow (local token generation only) |
| `notion-client` | 2.7.0 | Notion API writes |
| `anthropic` | Not installed locally — use latest stable (~0.40.x) | Claude API narrative generation |

## API Distinction: YouTube Analytics v2 vs YouTube Data API v3

**Critical — these are two separate APIs:**

| API | Purpose | Key Endpoints |
|-----|---------|--------------|
| YouTube Analytics API v2 | Revenue, RPM, watch time, territory, per-video metrics | `reports.query` |
| YouTube Data API v3 | Video metadata, titles, thumbnails, channel info | `videos.list`, `channels.list` |

Both are available via `googleapiclient.discovery.build()`. Both needed: Analytics for metrics, Data for video titles to include in the report.

```python
analytics = build("youtubeAnalytics", "v2", credentials=creds)
youtube = build("youtube", "v3", credentials=creds)
```

## Headless OAuth Pattern (GitHub Actions)

**Do NOT use:** `InstalledAppFlow.run_local_server()` — hangs silently in CI.

**Use instead:**
```python
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

creds = Credentials(
    token=None,
    refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
    token_uri="https://oauth2.googleapis.com/token",
    client_id=os.environ["YOUTUBE_CLIENT_ID"],
    client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
    scopes=[
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
        "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
    ],
)
creds.refresh(Request())
```

## Gmail via smtplib

```python
import smtplib
from email.mime.text import MIMEText

# Uses Gmail App Password — no OAuth needed
smtp = smtplib.SMTP("smtp.gmail.com", 587)
smtp.starttls()
smtp.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
```

**Rationale:** App Password approach is simpler than Gmail API OAuth for notification-only use. No additional credentials or scopes required.

## Anthropic SDK

Use `anthropic.Anthropic()` client. Default to `claude-sonnet-4-6` (latest capable model as of 2026).

```python
import anthropic
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
```

**Note:** Pin the model string explicitly in the script — do not use a generic alias that could resolve to a different model across runs.

## Notion Client

```python
from notion_client import Client

notion = Client(auth=os.environ["NOTION_API_KEY"])
```

Version 2.7.0 confirmed. Use `notion.pages.create()` for new monthly report pages, `notion.databases.create()` for one-time setup.

## GitHub Actions Python Setup

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.11"
- run: pip install -r requirements.txt
```

**requirements.txt** (pin versions for reproducibility):
```
google-api-python-client==2.188.0
google-auth==2.48.0
google-auth-oauthlib==1.2.4
notion-client==2.7.0
anthropic>=0.40.0
```

## What NOT to Use

| Avoid | Use Instead | Reason |
|-------|------------|--------|
| `search.list` for video metadata | `videos.list` | `search.list` costs 100 quota units; `videos.list` costs 1 |
| `InstalledAppFlow.run_local_server()` | `Credentials(refresh_token=...)` | Browser flow hangs in GitHub Actions |
| `youtube-data-api` (PyPI) | `google-api-python-client` | Unofficial wrapper with stale maintenance |
| Gmail API OAuth | smtplib + App Password | Unnecessary complexity for notifications |

---
*Research date: 2026-03-24*
*Versions confirmed via pip list in this environment*
