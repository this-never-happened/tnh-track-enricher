# Track Enricher Service — Design Spec

**Date:** 2026-03-20
**Status:** Approved
**Service:** `tnh-track-enricher` (new standalone Railway service)

---

## Overview

A Railway worker service that enriches TNH Notion Tracks records with BPM and duration extracted from Dropbox audio files, and standardises Dropbox filenames to a confirmed naming convention. Built in two phases: Phase 1 enriches metadata and logs proposed renames; Phase 2 executes the renames.

---

## Service Structure

```
tnh-track-enricher/
  enrich_tracks.py      ← Phase 1 worker (audio analysis + Notion writes)
  rename_tracks.py      ← Phase 2 worker (Dropbox renames — not yet built)
  requirements.txt
  Procfile              ← worker: python enrich_tracks.py
  railway.toml
```

When Phase 2 is ready, Procfile gains a second line:
```
worker: python enrich_tracks.py
rename: python rename_tracks.py
```

Matches the `tnh-label-costs` single-file worker pattern. Each script does one thing; they share env vars and the same Railway service.

---

## Filename Standard (Confirmed)

```
{ISRC}_{Artist-Slug}_{Track-Slug}_{Version-Slug}.{ext}
```

**Construction rules:**

| Segment | Rule |
|---------|------|
| ISRC | Strip all hyphens: `GB-EWA-23-03320` → `GBEWA2303320` |
| Artist slug | Join names with ` x `, replace spaces with `-`, strip non-alphanumeric/hyphen: `Lane 8 x Sultan + Shepard` → `Lane-8-x-Sultan-Shepard` |
| Track slug | Replace spaces with `-`, strip non-alphanumeric/hyphen: `RnR (Lane 8 Remix)` → `RnR-Lane-8-Remix` |
| Version slug | First value from `version` multi_select, spaces → `-`: `Extended Mix` → `Extended-Mix`. Omit segment entirely if version is empty. |
| Extension | Preserve original (`.wav`, `.flac`, `.aiff` etc — never hardcode) |

**Examples:**
```
GBEWA2303320_Sultan-Shepard_RnR-Lane-8-Remix_Remix.flac
GBTNHH2500001_Lane-8-x-Sultan-Shepard-x-sadhappy_Disappear_Extended-Mix.wav
```

---

## Phase 1 — `enrich_tracks.py`

### Trigger condition

Process a track only when ALL are true:
- `isrc` is not empty
- `master` (Dropbox URL) is not empty
- `bpm` is empty OR `duration` is empty
- Page ID is not in the in-memory `_failed_ids` skip set

### Notion fields

| Field | Direction | Type | Notes |
|-------|-----------|------|-------|
| `track` | READ | title | Track name |
| `isrc` | READ | rich_text | |
| `bpm` | READ/WRITE | number | Integer, e.g. `123` |
| `duration` | READ/WRITE | rich_text | Format `M:SS`, e.g. `6:42` — no leading zero on minutes |
| `master` | READ | url | Dropbox share link |
| `version` | READ | multi_select | Array of strings |
| `artist(s)` | READ | relation | Array of Notion page IDs |

### Audio analysis

- Download Dropbox file to `/tmp/<original_filename>` (convert `dl=0` → `dl=1`)
- `try/finally` guarantees temp file deletion on success or failure
- `librosa.load(path, sr=None)` — preserve native sample rate
- BPM: `librosa.beat.beat_track()` → round to nearest integer
- Duration: `librosa.get_duration(path=path)` → format as `M:SS`
- Log wall-clock time per track

### Artist name resolution

- `artist(s)` field returns relation IDs → fetch each artist page via Notion API
- Artist name is in the `artist` rich_text property (NOT the page title)
- Cache: `{page_url: artist_name}` dict, cleared each poll cycle
- Join multiple names with ` x `: `Lane 8 x Sultan + Shepard`
- 0.35s sleep between all Notion API calls

### Error handling

On any per-track error (download failure, librosa failure, Notion write failure):
1. Log the error + full traceback to Railway logs
2. Post a Notion comment to the track page: `"enrich_tracks error [YYYY-MM-DD]: <short message>"`
3. Add the page ID to `_failed_ids` (in-memory set, lives for the process lifetime)
4. Continue to next track — never crash the loop

`_failed_ids` is NOT persisted. Railway restart clears it, which is the desired retry mechanism.

### Filename proposal (Phase 1 — log only)

After successful enrichment, log the proposed rename:
```
CURRENT:  Sultan-Shepard-RnR-Lane-8-Remix-GBEWA2303320.flac
PROPOSED: GBEWA2303320_Sultan-Shepard_RnR-Lane-8-Remix_Remix.flac
```

If ISRC (hyphens stripped) already appears in the filename AND it closely matches the target format, log `filename OK — no rename needed` and skip.

No Dropbox API calls in Phase 1.

### DRY_RUN

`DRY_RUN = True` at module level (never change the default).
- `True`: log proposed Notion PATCH, do not execute
- `False`: execute PATCH to write `bpm` and `duration`

### Polling loop

```
while True:
    log ISO timestamp + track count
    for each track:
        process_track()  # errors caught, logged, skipped
    sleep 300s
```

---

## Phase 2 — `rename_tracks.py`

### Trigger condition

Process a track only when ALL are true:
- `bpm` is populated AND `duration` is populated (enrichment complete)
- Current Dropbox filename does NOT already match the target format
- Page ID is not in `_failed_ids`

### What it does

1. Resolve artist names (same cache pattern as Phase 1)
2. Build proposed filename using confirmed standard
3. Check if rename needed (ISRC present + format matches → skip)
4. Get fresh Dropbox access token via refresh token
5. Call `POST /files/move_v2` — rename in-place, same folder
6. Update `master` URL in Notion to reflect new filename
7. Post Notion comment: `"Renamed: old_name.flac → new_name.flac"`

### Dropbox authentication

Lifted directly from `tnh-invoice-portal/app.py` — no new auth work:

```python
def get_dropbox_access_token():
    r = requests.post('https://api.dropbox.com/oauth2/token', data={
        'grant_type': 'refresh_token',
        'refresh_token': DROPBOX_REFRESH_TOKEN,
        'client_id': DROPBOX_APP_KEY,
        'client_secret': DROPBOX_APP_SECRET,
    })
    return r.json().get('access_token')
```

Fresh token fetched per API call — never expires.

All Dropbox API calls must include `Dropbox-API-Select-User: DROPBOX_MEMBER_ID` and `Dropbox-API-Path-Root: DROPBOX_PATH_ROOT` headers for team namespace access.

### DRY_RUN

Same pattern — `DRY_RUN = True` default. Logs proposed rename + Notion update without executing.

---

## Environment Variables

| Variable | Phase | Source |
|----------|-------|--------|
| `NOTION_TOKEN` | 1 + 2 | Existing — used across all services |
| `DROPBOX_APP_KEY` | 2 | Existing — `tnh-invoice-portal` |
| `DROPBOX_APP_SECRET` | 2 | Existing — `tnh-invoice-portal` |
| `DROPBOX_REFRESH_TOKEN` | 2 | Existing — `tnh-invoice-portal` |
| `DROPBOX_MEMBER_ID` | 2 | Existing — `tnh-invoice-portal` |
| `DROPBOX_PATH_ROOT` | 2 | Existing — `tnh-invoice-portal` |

No new credentials required.

---

## Dependencies

```
librosa
soundfile
requests
```

```bash
pip install librosa soundfile requests
```

---

## Deployment

Local test first — no Procfile or Railway config until Phase 1 is validated.

Deploy sequence:
1. Test `enrich_tracks.py` locally with `DRY_RUN = True`
2. Validate proposed BPM/duration values + filename proposals against known tracks
3. Set `DRY_RUN = False`, re-test against a single track
4. Create `tnh-track-enricher` Railway service, set `NOTION_TOKEN` env var
5. Deploy — monitor Railway logs for first poll cycle
6. Phase 2: build `rename_tracks.py`, test locally, add to Procfile, deploy

---

## What's Out of Scope

- Actual Dropbox renames in Phase 1 (log only)
- Any Dropbox API calls in Phase 1
- Persistent retry tracking across process restarts (use Railway restart to retry)
- Renaming files in a different folder (in-place only)
