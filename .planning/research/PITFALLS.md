# Pitfalls Research: YouTube Monthly Analytics Report

**9 critical pitfalls identified — specific to this stack.**

---

## 1. OAuth Interactive Browser Flow in Headless Environment

**Severity:** CRITICAL — pipeline will silently hang

**Problem:** `InstalledAppFlow.run_local_server()` (used in existing repo scripts: `youtube_revenue_verify.py`, `youtube_mix_deep_analysis.py`) requires a browser. GitHub Actions has no browser.

**Prevention:** Use `google.oauth2.credentials.Credentials` with a pre-stored refresh token reconstructed from environment variables. See STACK.md for the exact pattern.

**Phase:** Phase 1 (token generation script) + Phase 2 (YouTube data pull)

---

## 2. Revenue Data Not Final at Month Start

**Severity:** HIGH — report will contain preliminary/incorrect revenue figures

**Problem:** YouTube finalizes revenue/RPM data 2–3 days after a period ends, with ongoing revisions for up to 30 days. Running on the 1st means the last 2–3 days of the prior month are incomplete.

**Prevention:** Set `endDate` to the 28th of the prior month, OR include explicit "preliminary data" language in the executive summary. Document this limitation prominently.

**Phase:** Phase 2 (YouTube data pull)

---

## 3. Month Boundary Timezone Ambiguity

**Severity:** HIGH — wrong date range silently pulls incorrect data

**Problem:** GitHub Actions runners use UTC. If the channel or report consumer is US/Pacific, a midnight UTC run on the 1st is still the 31st in local time. `date.today()` will give the wrong answer.

**Prevention:** Use explicit calendar arithmetic. Derive prior month start/end from the current UTC date, not local time. Example:
```python
from datetime import date, timedelta
today = date.today()  # UTC in GitHub Actions
first_of_this_month = today.replace(day=1)
last_month_end = first_of_this_month - timedelta(days=1)
last_month_start = last_month_end.replace(day=1)
```

**Phase:** Phase 2 (YouTube data pull)

---

## 4. Quota Exhaustion via Wrong API Call

**Severity:** HIGH — can exhaust entire daily quota in a single run

**Problem:** A common mistake is using `search.list` to look up video metadata by ID — it costs 100 quota units per call. `videos.list` costs 1 unit and does the same job when you have video IDs from the Analytics API.

**Prevention:** Never use `search.list`. Use `videos.list` with `id` parameter for metadata lookups. For per-video metrics, use two bulk `dimensions=video` calls (current 30d + prior 30d) rather than individual calls per video.

**Phase:** Phase 2 (YouTube data pull)

---

## 5. GitHub Actions Cron Unreliability

**Severity:** MEDIUM — scheduled runs can be delayed, skipped, or silently disabled

**Problem:** GitHub Actions scheduled jobs are best-effort and can be delayed by up to several hours under load. Repos inactive for 60+ days have their cron schedules silently disabled.

**Prevention:**
- Schedule at `30 2 1 * *` (2:30 AM UTC on the 1st) rather than midnight to avoid peak load
- Always add `workflow_dispatch:` trigger alongside `schedule:` so the report can be run manually
- Keep the repo active (any commit resets the 60-day inactivity clock)

**Phase:** Phase 6 (GitHub Actions YAML)

---

## 6. Notion 2,000-Character Block Limit

**Severity:** HIGH — Notion API will reject writes silently or with opaque errors

**Problem:** A single Notion paragraph block cannot exceed 2,000 characters. Top-20 video lists and territory breakdowns can easily exceed this.

**Prevention:** Chunk all text content into blocks of ≤1,900 characters before calling `notion.pages.create()`. Write a `chunk_text(text, max_chars=1900)` utility and use it for every section.

**Phase:** Phase 4 (Notion writer)

---

## 7. Claude Context Window Overflow from Raw JSON

**Severity:** MEDIUM — increases cost and can cause truncation

**Problem:** Raw YouTube Analytics API response JSON is verbose. A 50-country territory breakdown in JSON can consume 3,000+ tokens; the same data as formatted plain text uses ~200 tokens.

**Prevention:** Pre-format all analytics data into clean plain text or compact dicts before passing to Claude. Never send raw API responses. Strip null fields, decode country codes, round floats to 2 decimal places before the API call.

**Phase:** Phase 3 (Claude narrative layer)

---

## 8. Gmail App Password Revocation

**Severity:** MEDIUM — notification step can fail without warning

**Problem:** Google revokes App Passwords without warning when access comes from new IP ranges — GitHub Actions runners qualify as new IPs. This can cause the Gmail step to fail silently.

**Prevention:** Wrap the Gmail send in `try/except` so a failed notification does not fail the entire pipeline. Log the failure and consider the report "success" if Notion write succeeded. Consider adding a fallback notification channel.

**Phase:** Phase 5 (Gmail notification)

---

## 9. OAuth Missing Monetary Scope at Token Generation Time

**Severity:** CRITICAL — revenue/RPM data will return empty or 403 errors

**Problem:** A refresh token generated without `yt-analytics-monetary.readonly` cannot be incrementally upgraded. The token must be regenerated from scratch with all three scopes.

**Prevention:** The local token generation script (Component 7 in build order) must include all three scopes:
- `https://www.googleapis.com/auth/youtube.readonly`
- `https://www.googleapis.com/auth/yt-analytics.readonly`
- `https://www.googleapis.com/auth/yt-analytics-monetary.readonly`

Verify scope list before generating the token. There is no recovery path except full re-auth.

**Phase:** Phase 7 (OAuth token generator)

---

## 10. OAuth App in "Testing" Mode

**Severity:** HIGH — refresh tokens expire after 7 days in Testing mode

**Problem:** If the Google Cloud Console OAuth app is in "Testing" (not "Published") mode, refresh tokens expire after 7 days. The pipeline will authenticate on deploy and silently fail on the next run.

**Prevention:** Either publish the OAuth app (requires Google verification for sensitive scopes) or add the Google account as a test user in the OAuth consent screen. For internal/personal use, adding as a test user is sufficient and avoids the verification process.

**Phase:** Phase 7 (OAuth token generator)

---
*Research date: 2026-03-24*
*Sources: YouTube Analytics API docs, Google OAuth2 docs, GitHub Actions docs, Notion API docs, production code in this repo*
