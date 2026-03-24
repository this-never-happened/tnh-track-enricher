# Requirements: YouTube Monthly Analytics Report

**Defined:** 2026-03-24
**Core Value:** Every month, label stakeholders receive a factual, structured YouTube analytics report in Notion with zero manual intervention.

## v1 Requirements

### Infrastructure Setup

- [ ] **INFRA-01**: Notion database creation script creates the monthly reports database with correct schema and outputs database ID
- [ ] **INFRA-02**: Local OAuth token generator script produces a refresh token with all three required scopes (youtube.readonly, yt-analytics.readonly, yt-analytics-monetary.readonly)
- [ ] **INFRA-03**: OAuth app test user is configured so refresh token does not expire after 7 days

### Data Models

- [ ] **MODEL-01**: `AnalyticsData` dataclass defines the contract between pipeline stages (no raw API dicts crossing module boundaries)
- [ ] **MODEL-02**: `requirements.txt` pins all dependency versions for reproducible GitHub Actions runs
- [ ] **MODEL-03**: `.env.example` documents all 7 required environment variables

### YouTube Data Pull

- [ ] **YT-01**: Headless OAuth authenticates using refresh token from environment variables (no browser, no interactive flow)
- [ ] **YT-02**: Analytics pull fetches views, estimatedRevenue, and RPM (calculated) per video for the prior calendar month
- [ ] **YT-03**: Rolling 30-day and prior 30-day per-video data fetched via two bulk `dimensions=video` queries (not per-video calls)
- [ ] **YT-04**: Territory data fetched via `dimensions=country` for top 5 countries by views and revenue
- [ ] **YT-05**: Video titles fetched from YouTube Data API v3 (`videos.list`) to enrich video IDs
- [ ] **YT-06**: Date range uses prior calendar month derived from UTC date (not local time, not hardcoded)

### Claude Narrative Layer

- [ ] **CLAUDE-01**: System prompt enforces data-reporter constraints verbatim (no inference, no hedging language, action points start with verb referencing specific metric/asset)
- [ ] **CLAUDE-02**: All 7 report sections generated: executive summary, top 20 videos, breakout assets, anomalies, territory hotspots, RPM trend, action points
- [ ] **CLAUDE-03**: Analytics data pre-formatted as plain text before Claude API call (no raw JSON payloads)
- [ ] **CLAUDE-04**: Model string pinned explicitly in code (not a generic alias)

### Notion Writer

- [ ] **NOTION-01**: Each monthly report creates a new page in the Notion database (not updating existing pages)
- [ ] **NOTION-02**: All text content chunked to ≤1,900 characters per block before writing (Notion 2,000-char limit)
- [ ] **NOTION-03**: Page includes Report Month, Generated At timestamp, all 7 report sections, and Status property
- [ ] **NOTION-04**: Raw analytics data stored as JSON in the page for auditability

### Gmail Notification

- [ ] **GMAIL-01**: Email sent on successful report completion with Notion page link
- [ ] **GMAIL-02**: Gmail step wrapped in try/except so a notification failure does not fail the pipeline

### Orchestration

- [ ] **ORCH-01**: `main.py` validates all required environment variables on startup and fails fast with a clear error if any are missing
- [ ] **ORCH-02**: GitHub Actions workflow runs on `schedule: cron: '30 2 1 * *'` (2:30 AM UTC on the 1st)
- [ ] **ORCH-03**: GitHub Actions workflow includes `workflow_dispatch:` trigger for manual runs
- [ ] **ORCH-04**: Pipeline runs end-to-end locally before GitHub Actions YAML is written

## v2 Requirements

### Enhancements

- **ENH-01**: Email includes report summary inline (not just Notion link)
- **ENH-02**: Slack notification as alternative/addition to Gmail
- **ENH-03**: Historical comparison beyond prior 30 days (e.g., same month last year)
- **ENH-04**: Card CTR and impressions section (requires separate API call)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Multi-channel aggregation | Single channel only per spec |
| Interactive dashboard or web UI | Notion is the output surface |
| Historical backfill | Runs forward from first deployment |
| Revenue forecasting / predictions | Data reporter rules prohibit inference |
| Retention curve analysis | Not in report structure spec |
| Traffic source breakdown | Not in report structure spec |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Pending |
| INFRA-02 | Phase 1 | Pending |
| INFRA-03 | Phase 1 | Pending |
| MODEL-01 | Phase 2 | Pending |
| MODEL-02 | Phase 2 | Pending |
| MODEL-03 | Phase 2 | Pending |
| YT-01 | Phase 3 | Pending |
| YT-02 | Phase 3 | Pending |
| YT-03 | Phase 3 | Pending |
| YT-04 | Phase 3 | Pending |
| YT-05 | Phase 3 | Pending |
| YT-06 | Phase 3 | Pending |
| CLAUDE-01 | Phase 4 | Pending |
| CLAUDE-02 | Phase 4 | Pending |
| CLAUDE-03 | Phase 4 | Pending |
| CLAUDE-04 | Phase 4 | Pending |
| NOTION-01 | Phase 5 | Pending |
| NOTION-02 | Phase 5 | Pending |
| NOTION-03 | Phase 5 | Pending |
| NOTION-04 | Phase 5 | Pending |
| GMAIL-01 | Phase 6 | Pending |
| GMAIL-02 | Phase 6 | Pending |
| ORCH-01 | Phase 7 | Pending |
| ORCH-02 | Phase 7 | Pending |
| ORCH-03 | Phase 7 | Pending |
| ORCH-04 | Phase 7 | Pending |

**Coverage:**
- v1 requirements: 26 total
- Mapped to phases: 26
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-24*
*Last updated: 2026-03-24 after initial definition*
