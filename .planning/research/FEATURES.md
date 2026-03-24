# Features Research: YouTube Monthly Analytics Report

**Confidence:** HIGH (API field names verified from production code in this repo)

## Confirmed YouTube Analytics API Metrics

| Metric | Field Name | Notes |
|--------|-----------|-------|
| Views | `views` | Direct field |
| Estimated Revenue | `estimatedRevenue` | YPP only |
| Estimated Ad Revenue | `estimatedAdRevenue` | YPP only |
| Gross Revenue | `grossRevenue` | YPP only |
| CPM | `cpm` | YPP only |
| Playback-based CPM | `playbackBasedCpm` | YPP only |
| Watch Time | `estimatedMinutesWatched` | Direct field |
| Avg View Duration | `averageViewDuration` | Direct field |
| Subscribers Gained | `subscribersGained` | Direct field |
| Subscribers Lost | `subscribersLost` | Direct field |
| Card CTR | `cardClickRate` | Separate API call required |
| Card Impressions | `cardImpressions` | Separate API call required |

## Confirmed API Dimensions

| Dimension | Field Name | Notes |
|-----------|-----------|-------|
| Month | `month` | Aggregation period |
| Day | `day` | Daily granularity |
| Video | `video` | Per-video breakdown |
| Traffic Source | `insightTrafficSourceType` | Traffic source type |
| Elapsed Video Time | `elapsedVideoTimeRatio` | Retention curve |
| Country | `country` | ISO 3166-1 alpha-2 — documented but NOT yet in repo code, needs validation |

## Critical Findings

### RPM is Calculated, Not Native
RPM is not a YouTube Analytics API field. Must be computed client-side:
```
RPM = estimatedRevenue / (views / 1000)
```
Existing repo scripts already do this correctly.

### Required OAuth Scopes (all three needed on same refresh token)
- `youtube.readonly` — channel ID and metadata
- `yt-analytics.readonly` — views, watch time, traffic
- `yt-analytics-monetary.readonly` — revenue, CPM

### Card CTR / Impressions Require a Separate API Call
Cannot be combined with revenue metrics in one query. Confirmed from `tnh_channel_health.py`.

### Bulk Dimension Queries for Breakout/Anomaly Detection
Use two `dimensions=video` calls (current 30d vs prior 30d) rather than per-video calls to avoid quota exhaustion at scale.

## Report Section → API Mapping

| Report Section | API Approach |
|----------------|-------------|
| Top 20 videos (views + revenue + RPM) | `dimensions=video`, metrics: `views,estimatedRevenue`, compute RPM client-side |
| Breakout assets (>50% growth vs prior 30d) | Two queries: current 30d + prior 30d, `dimensions=video` |
| Anomalies (>2x or <0.5x rolling avg) | Same two queries, compare per-video values |
| Territory hotspots (top 5 countries) | `dimensions=country`, metrics: `views,estimatedRevenue` — MEDIUM confidence, needs validation |
| RPM trend (this month vs prior month) | Aggregate `estimatedRevenue` + `views`, compute RPM for both periods |
| Executive summary / Action points | Derived from all above sections |

## Data Latency Issue

YouTube Analytics data has a **48–72 hour lag**. Running on the 1st of the month means the last 2–3 days of the prior month may be incomplete.

**Recommendation:** Set `endDate` to the 28th of the prior month, or document the limitation explicitly in every report.

## Table Stakes vs Differentiating

### Table Stakes (must have)
- Views, revenue, RPM per video
- Month-over-month RPM trend
- Top N videos by views
- Territory breakdown

### Differentiating (this project)
- Breakout asset detection (>50% growth vs prior 30d)
- Anomaly flagging (>2x or <0.5x rolling average)
- Claude-generated narrative with strict no-inference rules
- Fully automated pipeline — zero manual work

### Out of Scope
- Card CTR / impressions (separate API call, low priority for monthly report)
- Retention curves (`elapsedVideoTimeRatio`) — video-level detail not needed for executive report
- Traffic source breakdown — not in report structure spec

---
*Research date: 2026-03-24*
*Source: YouTube Analytics API docs + production code in this repo (tnh_channel_health.py, youtube_revenue_verify.py, youtube_mix_deep_analysis.py)*
