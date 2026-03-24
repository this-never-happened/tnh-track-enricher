# Architecture Research

**Domain:** Automated analytics pipeline — YouTube → Claude → Notion → Gmail
**Researched:** 2026-03-24
**Confidence:** HIGH (based on official API docs, existing codebase patterns, GitHub Actions documentation)

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                   GitHub Actions (cron: 1st of month)            │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │                    main.py  (orchestrator)                 │   │
│  │   load_env() → fetch() → generate() → write() → notify()  │   │
│  └───────────────────────────────────────────────────────────┘   │
│          │              │             │             │             │
│          ▼              ▼             ▼             ▼             │
│  ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │ youtube.py   │ │claude.py │ │notion.py │ │  gmail.py    │    │
│  │ Analytics    │ │Narrative │ │DB writer │ │ Notification │    │
│  │ data fetch   │ │generator │ │          │ │              │    │
│  └──────┬───────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘    │
│         │              │             │               │            │
├─────────┴──────────────┴─────────────┴───────────────┴───────────┤
│                   External APIs / Services                        │
│  ┌────────────────┐ ┌───────────┐ ┌──────────┐ ┌─────────────┐  │
│  │ YouTube Data   │ │ Anthropic │ │  Notion  │ │  Gmail SMTP │  │
│  │ Analytics v2   │ │  Claude   │ │    API   │ │  (port 587) │  │
│  └────────────────┘ └───────────┘ └──────────┘ └─────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Communicates With |
|-----------|----------------|-------------------|
| `main.py` | Orchestrates the pipeline in order; handles top-level error catching and run logging | All modules |
| `youtube.py` | Authenticates with YouTube OAuth (headless), fetches analytics data, returns structured dict | YouTube Analytics API v2 |
| `claude.py` | Accepts structured analytics dict, sends to Claude API with system prompt, returns 7-section narrative string | Anthropic API |
| `notion.py` | Accepts narrative + metadata, writes a new page to the Notion database, returns page URL | Notion API |
| `gmail.py` | Accepts report URL + summary metadata, sends notification email via SMTP | Gmail SMTP |
| `setup_notion_db.py` | One-time script: creates the Notion database with correct schema; run manually before first pipeline execution | Notion API |
| `generate_yt_token.py` | One-time script: runs interactive OAuth browser flow locally, serializes refresh token to env-safe format; run manually, output stored as GitHub Secret | YouTube OAuth |

---

## Data Flow

### Primary Pipeline Flow

```
GitHub Actions cron trigger
        │
        ▼
main.py: validate all env vars present → abort early if any missing
        │
        ▼
youtube.py: reconstruct credentials from YOUTUBE_REFRESH_TOKEN secret
         → call YouTube Analytics API v2 (reportType=channel)
         → fetch: views, revenue, RPM, territory breakdown (last 30 days)
         → return: analytics_dict (typed Python dict, no raw API objects)
        │
        ▼
claude.py: construct prompt from analytics_dict
         → send to claude-3-5-sonnet with system prompt (strict data-reporter rules)
         → parse response: validate all 7 sections present
         → return: report_text (plain string, section-delimited)
        │
        ▼
notion.py: create new page in Notion database
         → title: "YouTube Report — {YYYY-MM}"
         → properties: month (date), generated_at (datetime), status (select: "Generated")
         → body: report_text mapped to 7 Notion blocks (one per section)
         → return: page_url
        │
        ▼
gmail.py: send notification email to NOTIFICATION_RECIPIENTS
        → subject: "YouTube Monthly Report Ready — {YYYY-MM}"
        → body: page_url + top-line metrics (views, revenue, RPM)
        │
        ▼
main.py: log success, exit 0
```

### Error Flow

```
Any step raises exception
        │
        ▼
main.py: catch exception, log with full traceback
        │
        ▼
gmail.py: send failure notification to NOTIFICATION_RECIPIENTS
        → subject: "YouTube Report FAILED — {YYYY-MM}"
        → body: which step failed, error message
        │
        ▼
exit 1  (GitHub Actions marks job as failed, triggers native failure notification)
```

---

## Recommended Project Structure

```
youtube-analytics-report/
├── main.py                  # Pipeline orchestrator — runs all steps in sequence
├── youtube.py               # YouTube Analytics API client + headless auth
├── claude.py                # Claude API client + prompt construction
├── notion.py                # Notion API writer
├── gmail.py                 # SMTP notification sender
├── models.py                # Shared dataclasses: AnalyticsData, ReportResult
├── setup_notion_db.py       # One-time Notion DB schema creation (run manually)
├── generate_yt_token.py     # One-time OAuth token generator (run locally)
├── requirements.txt         # Pinned dependencies
├── .github/
│   └── workflows/
│       └── monthly_report.yml   # GitHub Actions workflow definition
└── .env.example             # Template showing all required env vars (no values)
```

### Structure Rationale

- **Flat module structure:** Each external integration is one file. With 4 services and a single pipeline flow, nested packages add no value and obscure the call order.
- **`models.py`:** Keeps `AnalyticsData` and `ReportResult` dataclasses out of individual modules, preventing circular imports and making the data contract between pipeline steps explicit.
- **`main.py` as orchestrator:** All sequencing logic lives here. Individual modules are pure functions — they receive input, return output, raise on error. They do not call each other.
- **Setup scripts separate from pipeline:** `setup_notion_db.py` and `generate_yt_token.py` are run-once developer tools. Keeping them out of main prevents accidental invocation and makes the pipeline's actual entry point unambiguous.

---

## Architectural Patterns

### Pattern 1: Linear Pipeline with Single Orchestrator

**What:** `main.py` calls each module's primary function in sequence. Each function returns a typed result. No module imports another module.

**When to use:** Any pipeline where steps are strictly sequential, state does not need to be shared across branches, and a partial run is not useful.

**Trade-offs:** Simple to trace and debug. Cannot parallelize steps (not needed here). All sequencing is visible in one file.

**Example:**
```python
# main.py
from youtube import fetch_analytics
from claude import generate_report
from notion import write_page
from gmail import send_notification
from models import AnalyticsData

def run():
    data: AnalyticsData = fetch_analytics()
    report_text: str = generate_report(data)
    page_url: str = write_page(report_text, data.period)
    send_notification(page_url, data)

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        send_failure_notification(str(e))
        raise
```

### Pattern 2: Headless OAuth via Stored Refresh Token

**What:** OAuth credentials are reconstructed from a serialized refresh token stored as a GitHub Secret (environment variable), not from a pickle file or credentials JSON file.

**When to use:** Any time code runs in a non-interactive environment (GitHub Actions, cron, containers). The existing `youtube_token.pickle` pattern in the repo works locally but WILL FAIL in GitHub Actions — there is no browser and no persistent filesystem between runs.

**Trade-offs:** Requires one manual step to generate the token locally. Refresh tokens for YouTube OAuth do not expire unless revoked (unlike access tokens which expire in 1 hour). The token must be stored in GitHub Secrets, not committed to the repo.

**Example:**
```python
# youtube.py — headless credential reconstruction
import os, json
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

def _get_credentials() -> Credentials:
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=[
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
    )
    creds.refresh(Request())  # Exchange refresh token for access token
    return creds
```

**Token generation script (run once locally):**
```python
# generate_yt_token.py — run locally, copy output to GitHub Secret
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

flow = InstalledAppFlow.from_client_secrets_file("client_secret_*.json", SCOPES)
creds = flow.run_local_server(port=0)

print("Copy these to GitHub Secrets:")
print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")
print(f"YOUTUBE_CLIENT_ID={creds.client_id}")
print(f"YOUTUBE_CLIENT_SECRET={creds.client_secret}")
```

### Pattern 3: Fail-Fast with Structured Error Notification

**What:** Validate all required environment variables at pipeline start before calling any API. If any secret is missing, fail immediately with a clear error listing which variables are absent.

**When to use:** Always, in any pipeline relying on injected secrets. GitHub Actions occasionally fails to inject secrets (misconfigured environment, wrong branch, deleted secret). Silent failures mid-pipeline waste API quota and produce incomplete Notion pages.

**Example:**
```python
# main.py
REQUIRED_ENV_VARS = [
    "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN",
    "ANTHROPIC_API_KEY",
    "NOTION_TOKEN", "NOTION_DATABASE_ID",
    "GMAIL_APP_PASSWORD", "GMAIL_SENDER", "NOTIFICATION_RECIPIENTS",
]

def validate_env():
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(f"Missing required secrets: {', '.join(missing)}")
```

---

## GitHub Actions YAML Structure

### Single Job (Recommended)

Use a single job with sequential steps. Multiple jobs add orchestration complexity without benefit — this pipeline has no parallel branches.

```yaml
# .github/workflows/monthly_report.yml
name: YouTube Monthly Analytics Report

on:
  schedule:
    - cron: '0 6 1 * *'   # 6am UTC on 1st of every month
  workflow_dispatch:        # manual trigger for testing

jobs:
  generate-report:
    runs-on: ubuntu-latest
    timeout-minutes: 15    # fail if pipeline hangs

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run analytics pipeline
        env:
          YOUTUBE_CLIENT_ID: ${{ secrets.YOUTUBE_CLIENT_ID }}
          YOUTUBE_CLIENT_SECRET: ${{ secrets.YOUTUBE_CLIENT_SECRET }}
          YOUTUBE_REFRESH_TOKEN: ${{ secrets.YOUTUBE_REFRESH_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
          NOTION_DATABASE_ID: ${{ secrets.NOTION_DATABASE_ID }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          GMAIL_SENDER: ${{ secrets.GMAIL_SENDER }}
          NOTIFICATION_RECIPIENTS: ${{ secrets.NOTIFICATION_RECIPIENTS }}
        run: python main.py
```

**Key decisions:**
- Secrets are injected per-step via `env:`, not globally. This limits secret exposure to the step that needs them (though in practice all steps need them here, so the entire job is fine).
- `timeout-minutes: 15` prevents runaway charges if an API call hangs.
- `workflow_dispatch` allows manual test runs without waiting for the 1st of the month.
- `cache: 'pip'` reduces cold-start time.

### Why Not Multiple Jobs

Splitting into `fetch → generate → write → notify` jobs would require passing data between jobs via GitHub Actions artifacts. A structured analytics dict and a multi-kilobyte report text are awkward to serialize to artifacts. The pipeline is inherently sequential and completes in under 2 minutes — multiple jobs offer no value.

---

## Notion Database Relationship to Monthly Runner

The `setup_notion_db.py` script and `main.py` have a strict dependency relationship:

```
setup_notion_db.py  (run once, manually, pre-deployment)
        │
        └── creates Notion database
        └── outputs NOTION_DATABASE_ID
        └── operator copies NOTION_DATABASE_ID to GitHub Secret
                │
                ▼
        main.py (runs monthly)
                │
                └── reads NOTION_DATABASE_ID from env
                └── calls notion.py with that ID
                └── writes new page to existing database
```

`setup_notion_db.py` must define the schema precisely: page title (text), month (date), generated_at (date+time), status (select: "Generated"/"Failed"), report sections as toggle blocks or heading blocks. The monthly runner depends on this schema being stable — schema changes after initial creation require a migration script or manual Notion editing.

**Do not** run `setup_notion_db.py` in the GitHub Actions workflow. It is a one-time operation. Running it monthly would either error (if the database name already exists) or create duplicate databases.

---

## Integration Points

### External Services

| Service | Integration Pattern | Auth Pattern | Notes |
|---------|---------------------|--------------|-------|
| YouTube Analytics API v2 | `google-api-python-client` `build("youtubeAnalytics", "v2")` | OAuth 2.0 refresh token (headless) | Scopes: `youtube.readonly` + `yt-analytics.readonly`. Access token has 1hr TTL; refresh token is long-lived |
| Anthropic Claude API | `anthropic` SDK `client.messages.create()` | API key (`ANTHROPIC_API_KEY`) | Use `claude-3-5-sonnet-20241022` or later. Set `max_tokens` explicitly. System prompt is load-bearing — do not truncate |
| Notion API | `notion-client` `client.pages.create()` | Integration token (`NOTION_TOKEN`) | Database must be shared with the integration. Parent must be a `database_id`, not a `page_id` |
| Gmail SMTP | `smtplib.SMTP("smtp.gmail.com", 587)` | Gmail App Password (`GMAIL_APP_PASSWORD`) | Requires 2FA enabled on the Gmail account. Not the account password — a 16-char app-specific password generated in Google Account settings |

### Internal Module Boundaries

| Boundary | Communication | Contract |
|----------|---------------|----------|
| `main.py` → `youtube.py` | Direct function call | Returns `AnalyticsData` dataclass |
| `main.py` → `claude.py` | Direct function call | Accepts `AnalyticsData`, returns `str` (report text) |
| `main.py` → `notion.py` | Direct function call | Accepts `str` + period string, returns `str` (page URL) |
| `main.py` → `gmail.py` | Direct function call | Accepts `str` (URL) + `AnalyticsData`, returns `None` |
| All modules → `models.py` | Import only | `AnalyticsData` is the shared data contract; no module should define its own raw dict shape |

---

## Build Order

This order is dictated by dependencies, not preference:

```
1. setup_notion_db.py     ← Creates the DB; outputs NOTION_DATABASE_ID
2. generate_yt_token.py   ← Creates refresh token; outputs 3 YouTube secrets
3. models.py              ← Defines AnalyticsData dataclass; needed by all other modules
4. youtube.py             ← Needs models.py for return type
5. claude.py              ← Needs models.py for input type
6. notion.py              ← Needs models.py for metadata; needs NOTION_DATABASE_ID to exist
7. gmail.py               ← Needs models.py for summary metrics in notification body
8. main.py                ← Needs all modules above complete and testable
9. monthly_report.yml     ← Needs main.py working end-to-end; add after local test confirmed
```

**Phase implications:**
- Phase 1 must include the one-time setup scripts and `models.py` — they are infrastructure, not features
- GitHub Actions YAML is the last thing written, not the first. Wire up locally before committing the workflow
- `claude.py` can be built and tested independently with a hardcoded `AnalyticsData` fixture before YouTube auth is working

---

## Anti-Patterns

### Anti-Pattern 1: Using pickle-based token storage in GitHub Actions

**What people do:** Reuse the `youtube_token.pickle` pattern that works locally (serialize credentials with `pickle`, load from file path).

**Why it's wrong:** GitHub Actions runners are ephemeral. No pickle file exists at start of run. `InstalledAppFlow.run_local_server()` will hang waiting for a browser callback that never comes, eventually timing out. This is exactly the pattern used in the existing local scripts in this repo.

**Do this instead:** Reconstruct `google.oauth2.credentials.Credentials` directly from `refresh_token`, `client_id`, `client_secret` environment variables, then call `.refresh(Request())` to get a short-lived access token at runtime.

### Anti-Pattern 2: Passing raw API response objects between pipeline stages

**What people do:** Return the raw YouTube API response dict from `youtube.py` and pass it directly to `claude.py` and `notion.py`.

**Why it's wrong:** Raw API responses change shape when Google updates their API. Coupling all downstream modules to the YouTube API's dict structure means a minor API change can break `claude.py` and `notion.py` even though they don't call YouTube at all. It also makes the Claude prompt construction messy.

**Do this instead:** Map the raw API response to an `AnalyticsData` dataclass in `youtube.py`. This is the boundary. All other modules work with `AnalyticsData`, not YouTube API internals.

### Anti-Pattern 3: Letting Claude infer or hallucinate metrics

**What people do:** Provide partial data and ask Claude to "fill in" missing sections or estimate trends.

**Why it's wrong:** The system prompt explicitly prohibits inference. Claude will hallucinate plausible-sounding numbers if given permission to infer. Stakeholders receiving fabricated revenue figures is a trust-destroying failure mode.

**Do this instead:** Validate that all 7 required data fields are present in `AnalyticsData` before calling Claude. If any are missing, fail the pipeline with a clear error rather than sending incomplete data. The system prompt should be treated as immutable — enforce it in code review.

### Anti-Pattern 4: Running setup_notion_db.py in the GitHub Actions workflow

**What people do:** Include the DB creation script in the workflow YAML for "idempotency."

**Why it's wrong:** Creating a database is not idempotent in Notion's API — it creates a new database each time. Running it monthly produces a new orphaned database every month, with no reports in the previous databases.

**Do this instead:** Run it once locally, copy the `NOTION_DATABASE_ID` to GitHub Secrets, and never include it in the workflow YAML.

### Anti-Pattern 5: Hardcoding the report month

**What people do:** Set `REPORT_MONTH = "2026-03"` in the script.

**Why it's wrong:** This requires a code change every month, defeating the purpose of automation.

**Do this instead:** Derive the report period from `datetime.now()` at runtime:
```python
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

def report_period() -> tuple[str, str]:
    """Returns (start_date, end_date) for the previous calendar month."""
    today = date.today()
    first_of_month = today.replace(day=1)
    end = first_of_month - relativedelta(days=1)
    start = end.replace(day=1)
    return start.isoformat(), end.isoformat()
```

---

## Scaling Considerations

This pipeline processes one channel, one month, once. It does not need to scale.

| Concern | Current Scope | If Multi-Channel Later |
|---------|---------------|------------------------|
| API quota | One YouTube API call per run — well within free quota | Each additional channel is one more call; still no quota concern below ~50 channels |
| Claude token cost | ~2,000 input tokens per report — negligible | Cost scales linearly with channels; still cheap at 10 channels |
| Notion rate limits | One page write per run — no concern | `notion-client` handles rate limit retry by default |
| Runtime | Under 2 minutes — well within 15min timeout | At 10 channels, sequential execution is still fine |

---

## Sources

- Google OAuth 2.0 for Server Applications: https://developers.google.com/identity/protocols/oauth2/web-server
- YouTube Analytics API v2 reference: https://developers.google.com/youtube/analytics/reference/rest/v2/reports/query
- `google.oauth2.credentials.Credentials` class (headless pattern): https://google-auth.readthedocs.io/en/master/reference/google.oauth2.credentials.html
- GitHub Actions: secrets in workflows: https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions
- GitHub Actions: schedule trigger: https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule
- Notion API: create page in database: https://developers.notion.com/reference/post-page
- Gmail SMTP with App Passwords: https://support.google.com/accounts/answer/185833
- Existing local auth pattern (this repo): `/Users/pete/youtube_mix_analysis.py` — shows pickle-based flow that must NOT be used in Actions

---
*Architecture research for: YouTube Analytics automated reporting pipeline (Python + GitHub Actions)*
*Researched: 2026-03-24*
