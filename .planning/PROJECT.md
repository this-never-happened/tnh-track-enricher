# YouTube Monthly Analytics Report

## What This Is

An automated Python pipeline that runs on the 1st of each month via GitHub Actions. It pulls data from the YouTube Analytics API for a single monetized channel, generates a structured 7-section report via Claude API (narrative only, no inference), writes each report as a new page in a Notion database, and sends a Gmail notification. Built for label stakeholders — executives and clients who need clear, factual performance data monthly without manual effort.

## Core Value

Every month, label stakeholders receive a factual, structured YouTube analytics report in Notion with zero manual intervention.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] GitHub Actions cron triggers the pipeline on the 1st of each month
- [ ] YouTube Analytics API pull covers: views, revenue, RPM, territory breakdown, rolling 30-day averages
- [ ] Report contains all 7 sections in order: executive summary, top 20 videos, breakout assets, anomalies, territory hotspots, RPM trend, action points
- [ ] Claude API generates narrative with strict data-reporter constraints (no inference, no hedging language)
- [ ] Each monthly report is written as a new page in a Notion database
- [ ] Gmail notification sent on report completion
- [ ] OAuth refresh token works non-interactively in GitHub Actions (no browser prompts)
- [ ] Notion database schema supports all 7 report sections plus metadata (month, generated timestamp, status)

### Out of Scope

- Multi-channel aggregation — single channel only
- Interactive dashboard or web UI — Notion is the output surface
- Historical backfill — runs forward from first deployment
- Revenue forecasting or trend predictions — data reporter rules prohibit inference

## Context

- Stack: Python 3.11, google-api-python-client, anthropic SDK, notion-client, smtplib, GitHub Actions
- All credentials stored as GitHub Secrets / environment variables (7 vars defined)
- YouTube channel is fully monetized (YPP) — revenue and RPM data available via API
- Claude API system prompt has hard constraints: no cause inference, no hedging language, action points must start with a verb and reference a specific metric/asset
- Report audience is label stakeholders (executives/clients) — tone must be polished and unambiguous
- Build order defined: Notion DB creation → YouTube pull → Claude narrative → Notion writer → Gmail → GitHub Actions → OAuth token generator

## Constraints

- **Tech stack**: Python 3.11 only — no Node, no other runtimes
- **Auth**: YouTube OAuth must work headlessly (refresh token pre-generated, stored as secret)
- **Claude API**: System prompt rules are non-negotiable — enforced verbatim as specified
- **Scheduling**: GitHub Actions cron only — no external schedulers
- **Secrets**: All credentials via environment variables — nothing hardcoded

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Notion database (not standalone pages) | Each month = one queryable row; sortable and archivable | — Pending |
| Claude for narrative only, not data processing | Keeps data layer deterministic; Claude adds structure/language | — Pending |
| smtplib for Gmail (not Gmail API) | Simpler auth via app password; sufficient for notification-only use | — Pending |
| Refresh token pre-generated locally | GitHub Actions can't do browser OAuth; token stored as secret | — Pending |

---
*Last updated: 2026-03-24 after initialization*
