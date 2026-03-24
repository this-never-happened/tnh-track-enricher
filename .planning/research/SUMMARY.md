# Project Research Summary

**Project:** YouTube Monthly Analytics Report
**Domain:** Automated analytics pipeline — YouTube → Claude → Notion → Gmail
**Researched:** 2026-03-24
**Confidence:** HIGH

## Executive Summary

This project is a fully automated monthly reporting pipeline that pulls YouTube channel analytics, generates an AI-written narrative via Claude, writes the report to a Notion database, and sends an email notification — all triggered by a GitHub Actions cron job. The expert approach for this domain is a flat, linear pipeline with a single orchestrator (`main.py`) coordinating four thin integration modules. Each module is a pure function: it receives typed input, returns typed output, and raises on error. This keeps sequencing logic visible in one place and makes each integration independently testable.

The recommended stack is well-established and proven in the existing codebase: `google-api-python-client` for YouTube (Analytics v2 + Data API v3), `anthropic` SDK for Claude, `notion-client` for Notion, and `smtplib` with a Gmail App Password for notifications. All versions are confirmed installed in this environment. The critical pattern shift from existing local scripts is the OAuth credential approach — the `InstalledAppFlow.run_local_server()` method used throughout the current repo will silently hang in GitHub Actions and must be replaced with headless credential reconstruction from a stored refresh token.

The two biggest risks are OAuth-related and must be addressed before any other code is written: the refresh token must be generated with all three required scopes (including `yt-analytics-monetary.readonly` for revenue data), and the Google OAuth app must have the generating account added as a test user to prevent 7-day token expiration. Every other pitfall in this project is either a defensive coding practice (fail-fast env validation, chunking Notion text, wrapping Gmail in try/except) or a known API nuance (48–72 hour revenue data lag, `search.list` quota cost) that is straightforward to avoid once flagged.

## Key Findings

### Recommended Stack

All packages are confirmed installed in this environment with pinned versions. The only external API that requires special handling is YouTube OAuth — both Analytics v2 and Data API v3 are available from the same `google-api-python-client` library but must be instantiated as separate clients. Gmail notification uses `smtplib` with an App Password rather than Gmail API OAuth, which is correct for notification-only use and avoids an unnecessary second OAuth credential.

**Core technologies:**
- `google-api-python-client==2.188.0`: YouTube Analytics API v2 (metrics) + Data API v3 (video metadata) — confirmed installed, both APIs needed
- `google-auth==2.48.0` + `google-auth-oauthlib==1.2.4`: OAuth2 credential management — headless pattern required for GitHub Actions
- `anthropic>=0.40.0`: Claude API narrative generation — use `claude-sonnet-4-6`, pin model string explicitly
- `notion-client==2.7.0`: Notion database writes — confirmed installed
- `smtplib` (stdlib): Gmail SMTP notification — App Password approach, no additional install needed

### Expected Features

The YouTube Analytics API field names and metric availability are confirmed against production code in this repository. RPM is not a native API field — it is computed client-side as `estimatedRevenue / (views / 1000)`. Revenue metrics require the `yt-analytics-monetary.readonly` scope; without it, those fields return empty or 403. Card CTR and impressions require a separate API call and cannot be combined with revenue metrics.

**Must have (table stakes):**
- Views, revenue, and computed RPM per video — core data, all API fields confirmed
- Month-over-month RPM trend — requires two period queries, derive RPM for each
- Top 20 videos by views — `dimensions=video`, `metrics=views,estimatedRevenue`
- Territory breakdown (top 5 countries) — `dimensions=country`, MEDIUM confidence, needs validation

**Should have (differentiating):**
- Breakout asset detection (>50% view growth vs prior 30d) — two bulk `dimensions=video` queries, compare per-video
- Anomaly flagging (>2x or <0.5x rolling average) — same two queries, different comparison logic
- Claude-generated narrative with strict no-inference system prompt — fully automated, zero manual work

**Defer (v2+):**
- Card CTR / impressions — separate API call, low priority for executive monthly report
- Retention curves (`elapsedVideoTimeRatio`) — video-level detail, not needed for channel-level summary
- Traffic source breakdown — not in report structure requirements

### Architecture Approach

The architecture is a linear pipeline with a single orchestrator. `main.py` calls each module's primary function in sequence; no module imports another module. A shared `models.py` defines the `AnalyticsData` dataclass that passes between stages, isolating all modules from raw YouTube API response shape changes. Two one-time setup scripts (`setup_notion_db.py`, `generate_yt_token.py`) are separate from the pipeline and run manually before deployment — they must never be included in the GitHub Actions workflow.

**Major components:**
1. `main.py` — pipeline orchestrator; validates env vars at start, sequences all steps, handles failure notification
2. `youtube.py` — headless OAuth auth, fetches analytics and video metadata, returns typed `AnalyticsData`
3. `claude.py` — constructs prompt from `AnalyticsData`, calls Claude API, validates 7-section response
4. `notion.py` — writes report to Notion database as structured blocks, returns page URL
5. `gmail.py` — sends success or failure notification via SMTP; wrapped in try/except so it cannot fail the pipeline
6. `models.py` — shared `AnalyticsData` dataclass; defines the data contract between all modules
7. `setup_notion_db.py` — one-time Notion DB schema creation (run manually pre-deployment)
8. `generate_yt_token.py` — one-time OAuth flow run locally to produce refresh token for GitHub Secrets

### Critical Pitfalls

1. **Interactive OAuth in headless environment** — Replace `InstalledAppFlow.run_local_server()` (used throughout existing repo scripts) with `google.oauth2.credentials.Credentials(refresh_token=...)` reconstructed from env vars. This is CRITICAL: the existing pattern will silently hang in GitHub Actions.

2. **Missing monetary OAuth scope at token generation time** — The refresh token must include `yt-analytics-monetary.readonly` or revenue fields return empty/403 with no recovery path except full re-auth. Generate the token once, correctly, with all three scopes verified before the browser flow runs.

3. **OAuth app in "Testing" mode causing 7-day token expiration** — Add the generating Google account as a test user in Google Cloud Console. In Testing mode, refresh tokens expire after 7 days; the pipeline authenticates on deploy and silently fails on next run.

4. **Notion 2,000-character block limit** — Write a `chunk_text(text, max_chars=1900)` utility and apply it to every section before writing to Notion. Top-20 video lists will exceed this limit without chunking, causing opaque API errors.

5. **Revenue data latency (48–72 hour lag)** — Set `endDate` to the 28th of the prior month, or explicitly document "preliminary data" in the report for the last 2–3 days of the period. Running on the 1st means the prior month's end data is not final.

## Implications for Roadmap

The build order is dictated by hard dependencies, not preference. The architecture research makes this explicit: setup scripts must run before GitHub Secrets exist; `models.py` must exist before any integration module; the GitHub Actions YAML is the last artifact written, after end-to-end local testing. This maps directly to a 7-phase build order.

### Phase 1: Infrastructure Setup (One-Time)
**Rationale:** Nothing else can be built until the Notion database exists and its ID is known, and until OAuth secrets are captured. These are blocking prerequisites, not features.
**Delivers:** NOTION_DATABASE_ID for GitHub Secrets; YouTube OAuth refresh token (with all 3 scopes) for GitHub Secrets; Google Cloud project configured with both YouTube APIs enabled; OAuth app with test user added
**Addresses:** Token generation with complete scope list (pitfall 2), OAuth app Testing mode (pitfall 3)
**Avoids:** Having to regenerate tokens mid-build when scope gaps are discovered later

### Phase 2: Data Models and Project Skeleton
**Rationale:** `models.py` is imported by all other modules; it must exist first to enable parallel development of integration modules and to establish the typed data contract before any module makes an API call.
**Delivers:** `models.py` with `AnalyticsData` dataclass; `requirements.txt` with pinned versions; `.env.example` listing all 9 required secrets; project directory structure
**Uses:** All stack packages (defines what data flows between them)
**Avoids:** Raw API response coupling (architecture anti-pattern 2)

### Phase 3: YouTube Data Pull
**Rationale:** The pipeline's data source; all downstream phases depend on real analytics data. Build and validate this module before building anything that consumes its output.
**Delivers:** `youtube.py` — headless OAuth auth + Analytics v2 + Data API v3 fetch returning `AnalyticsData`; `generate_yt_token.py` one-time script (may already have token from Phase 1 but script is documented here)
**Implements:** Headless OAuth pattern (architecture pattern 2), bulk `dimensions=video` queries
**Avoids:** `InstalledAppFlow` in headless environment (pitfall 1), `search.list` quota exhaustion (pitfall 4), revenue data latency (pitfall 2 — set endDate to 28th), timezone ambiguity (pitfall 3)

### Phase 4: Claude Narrative Layer
**Rationale:** Once real `AnalyticsData` flows from Phase 3, Claude integration can be built and validated with live data. Can be prototyped earlier with a fixture, but final validation requires real data.
**Delivers:** `claude.py` — prompt construction from `AnalyticsData`, Claude API call, 7-section response validation; system prompt with strict no-inference rules
**Uses:** `anthropic>=0.40.0`, `claude-sonnet-4-6` (model pinned explicitly)
**Avoids:** Claude hallucinating metrics (architecture anti-pattern 3), raw JSON context overflow (pitfall 7)

### Phase 5: Notion Writer
**Rationale:** Depends on report text from Phase 4 and the database ID from Phase 1. Build after Claude output is validated so real report text can be used to test block limits.
**Delivers:** `notion.py` — creates new monthly page with correct schema, maps 7 report sections to Notion blocks, returns page URL; `chunk_text()` utility
**Uses:** `notion-client==2.7.0`
**Avoids:** 2,000-character Notion block limit (pitfall 6), running `setup_notion_db.py` in the workflow (architecture anti-pattern 4)

### Phase 6: Gmail Notification
**Rationale:** Depends on page URL from Phase 5. Build last among integration modules; it is the lowest-risk step and failure must not propagate upward.
**Delivers:** `gmail.py` — success and failure notification emails via SMTP, wrapped in try/except
**Uses:** `smtplib` (stdlib), Gmail App Password
**Avoids:** Gmail App Password revocation killing the pipeline (pitfall 8 — wrap in try/except, treat Notion success as overall success)

### Phase 7: Orchestration and CI
**Rationale:** `main.py` and the GitHub Actions YAML are written last — after all modules are individually tested — because they wire everything together. The workflow YAML is the final artifact, deployed only after confirmed local end-to-end run.
**Delivers:** `main.py` — env validation, pipeline sequencing, fail-fast error handling, failure notification; `.github/workflows/monthly_report.yml` — schedule + workflow_dispatch trigger, 15-minute timeout, pip cache
**Avoids:** Silent mid-pipeline failures from missing secrets (architecture pattern 3), cron unreliability without manual trigger (pitfall 5), hardcoded report month (architecture anti-pattern 5)

### Phase Ordering Rationale

- Phase 1 before everything: OAuth tokens and Notion DB ID are GitHub Secrets — without them, no module can be tested against real APIs. Discovering a scope gap in Phase 3 would require scrapping the token and restarting.
- Phase 2 before integration modules: `models.py` is a shared import. Building it first prevents circular dependency issues and forces the data contract to be specified before any API call is designed around it.
- Phases 3–6 in pipeline order: Each module's output is the next module's input. Building in pipeline order means each phase can be tested with real data from the previous phase.
- Phase 7 last: The GitHub Actions workflow is the deployment artifact. Adding it before end-to-end local success risks committing a broken workflow that triggers on the 1st of next month with no easy test cycle.

### Research Flags

Phases with well-documented patterns (skip additional research):
- **Phase 2** — Standard Python dataclass pattern; no research needed
- **Phase 4** — Anthropic SDK is straightforward; prompt engineering is project-specific, not researchable
- **Phase 6** — Gmail SMTP with App Password is fully documented and trivial
- **Phase 7** — GitHub Actions YAML structure is documented in ARCHITECTURE.md; no surprises expected

Phases that may benefit from validation during implementation:
- **Phase 3** — Territory dimension (`dimensions=country`) is documented in the API but not yet used in this repo's production code. Mark as MEDIUM confidence; validate with a test query before building the full report section around it.
- **Phase 5** — Notion block structure for 7 sections needs hands-on testing. The 2,000-character limit and block type choices (heading vs. toggle vs. paragraph) are best confirmed against a real Notion database before finalising the schema.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All package versions confirmed via pip list in this environment; patterns verified against production code in this repo |
| Features | HIGH | API field names verified from production scripts (`tnh_channel_health.py`, `youtube_revenue_verify.py`); one MEDIUM item: country dimension not yet in repo code |
| Architecture | HIGH | Based on official API docs, existing codebase patterns, GitHub Actions documentation; build order is dependency-driven |
| Pitfalls | HIGH | All 10 pitfalls sourced from official docs or confirmed failure modes in the existing local scripts |

**Overall confidence:** HIGH

### Gaps to Address

- **Country dimension validation:** `dimensions=country` is documented but not used in existing repo code. Run a test query in Phase 3 before building the territory report section. If it returns data, proceed. If it returns a 400 or empty result, drop territory from v1.
- **Notion block type selection:** The report requires 7 named sections. During Phase 5, decide whether to use heading blocks (always visible) vs. toggle blocks (collapsible) before writing `notion.py`. This is a UX decision, not a technical risk.
- **Claude system prompt finalization:** The exact wording of the no-inference rules is project-specific and will need iteration. Leave prompt content for Phase 4 authoring; do not try to specify it in the roadmap.

## Sources

### Primary (HIGH confidence)
- YouTube Analytics API v2 reference: https://developers.google.com/youtube/analytics/reference/rest/v2/reports/query
- Google OAuth 2.0 for Server Applications: https://developers.google.com/identity/protocols/oauth2/web-server
- `google.oauth2.credentials.Credentials` (headless pattern): https://google-auth.readthedocs.io/en/master/reference/google.oauth2.credentials.html
- GitHub Actions schedule trigger: https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule
- GitHub Actions secrets: https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions
- Notion API create page: https://developers.notion.com/reference/post-page
- Gmail SMTP App Passwords: https://support.google.com/accounts/answer/185833
- Production code in this repo: `tnh_channel_health.py`, `youtube_revenue_verify.py`, `youtube_mix_deep_analysis.py`

### Secondary (MEDIUM confidence)
- pip list output from this environment — package version confirmation
- Existing `youtube_token.pickle` pattern in repo — confirms what NOT to do in GitHub Actions

### Tertiary (MEDIUM — needs validation)
- YouTube Analytics API `dimensions=country` — documented but not yet confirmed against live data in this repo's context

---
*Research completed: 2026-03-24*
*Ready for roadmap: yes*
