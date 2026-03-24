# Roadmap: YouTube Monthly Analytics Report

## Overview

A linear, dependency-driven pipeline built in 7 phases. Each phase delivers one independently verifiable capability. The build order is dictated by hard dependencies: infrastructure secrets must exist before any module can authenticate; the shared data model must exist before any module imports it; the GitHub Actions YAML is the last artifact written, after end-to-end local validation. Phases 1-2 are one-time setup. Phases 3-6 build the four pipeline integration modules in execution order. Phase 7 wires everything together and deploys.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Infrastructure Setup** - Create Notion database and generate YouTube OAuth refresh token with all required scopes
- [ ] **Phase 2: Data Models and Project Skeleton** - Define shared AnalyticsData dataclass and project structure before any API integration begins
- [ ] **Phase 3: YouTube Data Pull** - Build headless OAuth authentication and analytics fetch module returning typed AnalyticsData
- [ ] **Phase 4: Claude Narrative Layer** - Construct prompt from AnalyticsData, call Claude API, validate 7-section report output
- [ ] **Phase 5: Notion Writer** - Write monthly report as structured Notion database page with correct schema and block chunking
- [ ] **Phase 6: Gmail Notification** - Send success notification with Notion page link; failure cannot propagate to pipeline
- [ ] **Phase 7: Orchestration and CI** - Wire all modules in main.py, validate end-to-end locally, then write GitHub Actions workflow

## Phase Details

### Phase 1: Infrastructure Setup
**Goal**: All one-time external configuration is complete and credentials are ready to populate GitHub Secrets
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03
**Success Criteria** (what must be TRUE):
  1. Running `setup_notion_db.py` creates a Notion database and prints a database ID that can be stored as a GitHub Secret
  2. Running `generate_yt_token.py` completes the OAuth browser flow and writes a refresh token to disk, confirmed to include all three scopes (youtube.readonly, yt-analytics.readonly, yt-analytics-monetary.readonly)
  3. The generating Google account is added as a test user in Google Cloud Console, so the refresh token does not expire after 7 days
  4. Using the refresh token against the YouTube Analytics API returns revenue data without 403 errors
**Plans**: TBD

### Phase 2: Data Models and Project Skeleton
**Goal**: The shared data contract and project structure are in place before any API integration is written
**Depends on**: Phase 1
**Requirements**: MODEL-01, MODEL-02, MODEL-03
**Success Criteria** (what must be TRUE):
  1. `from models import AnalyticsData` succeeds in a clean Python environment with dependencies from requirements.txt installed
  2. `AnalyticsData` dataclass has typed fields covering all data the YouTube module must produce and all data the Claude module must consume
  3. `.env.example` lists all 7 required environment variable names with descriptions; no required variable is undocumented
  4. `pip install -r requirements.txt` completes without conflict and installs pinned versions
**Plans**: TBD

### Phase 3: YouTube Data Pull
**Goal**: `youtube.py` authenticates headlessly and returns a populated AnalyticsData object covering the prior calendar month
**Depends on**: Phase 2
**Requirements**: YT-01, YT-02, YT-03, YT-04, YT-05, YT-06
**Success Criteria** (what must be TRUE):
  1. Running `youtube.py` (or calling its primary function from a test script) with real credentials produces an AnalyticsData object with no raw API dicts — all fields typed
  2. The returned data covers the correct prior calendar month derived from UTC date, not local time and not hardcoded
  3. Per-video data includes views, estimatedRevenue, and computed RPM for both the current 30-day window and the prior 30-day window, fetched via two bulk `dimensions=video` queries
  4. Territory breakdown includes top 5 countries by views and revenue via a `dimensions=country` query
  5. Video titles are present in the AnalyticsData output (fetched from Data API v3, not inferred from video IDs)
  6. No browser prompt or interactive flow appears when the module runs in a headless environment (credentials reconstructed from env vars only)
**Plans**: TBD

### Phase 4: Claude Narrative Layer
**Goal**: `claude.py` produces a complete, structured 7-section report narrative from AnalyticsData with strict data-reporter constraints enforced
**Depends on**: Phase 3
**Requirements**: CLAUDE-01, CLAUDE-02, CLAUDE-03, CLAUDE-04
**Success Criteria** (what must be TRUE):
  1. The Claude API response contains all 7 sections in order: executive summary, top 20 videos, breakout assets, anomalies, territory hotspots, RPM trend, action points
  2. The system prompt prevents inference language — no phrases like "likely", "probably", "may indicate"; action points start with a verb and reference a specific metric or asset name
  3. The data sent to Claude is pre-formatted plain text, not raw JSON; inspecting the API request confirms no raw dicts or API response objects in the payload
  4. The model string in code is an explicit pinned identifier, not a generic alias like "latest"
**Plans**: TBD

### Phase 5: Notion Writer
**Goal**: Each pipeline run creates a new, complete Notion database page containing the full report without hitting API block limits
**Depends on**: Phase 4
**Requirements**: NOTION-01, NOTION-02, NOTION-03, NOTION-04
**Success Criteria** (what must be TRUE):
  1. Running the Notion writer against a real Notion database creates a new page (not modifying any existing page) with the correct Report Month and Generated At metadata
  2. All 7 report sections appear as readable content in the Notion page with section names visible
  3. No Notion API error occurs for any text block — all content is chunked to 1,900 characters or fewer before writing
  4. The page contains a raw analytics JSON property that can be used to audit the source data
  5. The function returns a valid Notion page URL that links directly to the created report
**Plans**: TBD

### Phase 6: Gmail Notification
**Goal**: A success email containing the Notion page URL is sent on report completion; a Gmail failure cannot cause the pipeline to fail
**Depends on**: Phase 5
**Requirements**: GMAIL-01, GMAIL-02
**Success Criteria** (what must be TRUE):
  1. After a successful report write, an email arrives in the recipient inbox with the Notion page URL in the body
  2. When Gmail credentials are intentionally wrong or SMTP is unavailable, the pipeline run still exits with success status — the Gmail error is logged but does not raise
**Plans**: TBD

### Phase 7: Orchestration and CI
**Goal**: The full pipeline runs end-to-end locally via main.py, then a GitHub Actions workflow is written that will trigger it monthly without human intervention
**Depends on**: Phase 6
**Requirements**: ORCH-01, ORCH-02, ORCH-03, ORCH-04
**Success Criteria** (what must be TRUE):
  1. Running `python main.py` locally with a populated .env file completes all pipeline stages — YouTube pull, Claude narrative, Notion write, Gmail notification — and exits 0
  2. Running `python main.py` with a missing required environment variable fails immediately with a clear error message naming the missing variable, before any API call is made
  3. The GitHub Actions workflow file triggers on schedule (`cron: '30 2 1 * *'`) and on `workflow_dispatch`, confirmed by inspecting the YAML
  4. A manual `workflow_dispatch` run in GitHub Actions completes without errors and produces a new Notion report page
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Infrastructure Setup | 0/TBD | Not started | - |
| 2. Data Models and Project Skeleton | 0/TBD | Not started | - |
| 3. YouTube Data Pull | 0/TBD | Not started | - |
| 4. Claude Narrative Layer | 0/TBD | Not started | - |
| 5. Notion Writer | 0/TBD | Not started | - |
| 6. Gmail Notification | 0/TBD | Not started | - |
| 7. Orchestration and CI | 0/TBD | Not started | - |
