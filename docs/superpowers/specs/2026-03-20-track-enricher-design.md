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

Railway supports arbitrary process type names (not just `web`/`worker`) — `rename:` is valid and will run as an independent worker process.

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
| Artist slug | Join names with ` x ` first, then replace spaces with `-` and strip non-alphanumeric/hyphen characters from the combined string. E.g. `["Lane 8", "Sultan + Shepard", "sadhappy"]` → `Lane 8 x Sultan + Shepard x sadhappy` → `Lane-8-x-Sultan-Shepard-x-sadhappy` |
| Track slug | Replace spaces with `-`, strip non-alphanumeric/hyphen: `RnR (Lane 8 Remix)` → `RnR-Lane-8-Remix` |
| Version slug | First value from `version` multi_select (Notion API returns values in insertion order — use index 0), spaces → `-`: `Extended Mix` → `Extended-Mix`. Omit segment entirely if version is empty. |
| Extension | Preserve original (`.wav`, `.flac`, `.aiff` etc — never hardcode) |

**Construction order — step by step with a 3-artist example:**

Input: `["Lane 8", "Sultan + Shepard", "sadhappy"]`

1. Join with ` x `: `Lane 8 x Sultan + Shepard x sadhappy`
2. Replace spaces with `-`: `Lane-8-x-Sultan-+-Shepard-x-sadhappy`
3. Strip any character that is not alphanumeric or `-`: `Lane-8-x-Sultan--Shepard-x-sadhappy`
4. Collapse runs of hyphens to single `-`: `Lane-8-x-Sultan-Shepard-x-sadhappy`

Result: `Lane-8-x-Sultan-Shepard-x-sadhappy` ✓

The `+` character and surrounding spaces are normalised to a single `-` via steps 2–4. No special handling for `+` is required beyond this general rule.

**Examples:**
```
GBEWA2303320_Sultan-Shepard_RnR-Lane-8-Remix_Remix.flac
GBTNHH2500001_Lane-8-x-Sultan-Shepard-x-sadhappy_Disappear_Extended-Mix.wav
```

---

## "Filename matches" definition (used by both phases)

A filename is considered **already matching** the target format if BOTH are true:
1. The ISRC (hyphens stripped) appears in the filename (case-insensitive)
2. The filename starts with `{stripped_ISRC}_` (i.e. ISRC is the first `_`-separated segment)

If both conditions hold → log `filename OK — no rename needed` (Phase 1) or skip rename (Phase 2).
If condition 1 holds but condition 2 does not → ISRC is present but format is wrong → still log/execute the proposed rename.

This check applies equally to version-less tracks. A version-less file with the correct format (`GBTNHH2500001_Lane-8_Disappear.wav`) passes both conditions. The presence or absence of a version segment does not affect the check.

---

## Notion API

All Notion calls use raw `requests` (no SDK). This matches the pattern used across all TNH services.

**Tracks DB ID:** `795482ebef3c4830ac7e3c037deaab68` — hardcoded in both scripts.

**Rate limiting:** 0.35s sleep before every Notion API call.

**Pagination:** all DB queries paginate via `has_more` / `next_cursor`.

**Server-side DB filters:**
- Phase 1 query filter: `isrc` not empty AND `master` not empty AND (`bpm` empty OR `duration` empty)
- Phase 2 query filter: `isrc` not empty AND `master` not empty AND `bpm` not empty AND `duration` not empty
- The `_failed_ids` exclusion is applied client-side after the query (Notion cannot filter by comments)

**Posting comments:** `POST https://api.notion.com/v1/comments`
```json
{
  "parent": {"page_id": "<page_id>"},
  "rich_text": [{"type": "text", "text": {"content": "<message>"}}]
}
```
Headers: same `Authorization` + `Notion-Version: 2022-06-28` + `Content-Type: application/json` used throughout.

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

- Extract `original_filename` from the Dropbox URL path segment before the `?` query string. Dropbox share URLs have the filename embedded in the path: `https://www.dropbox.com/scl/fi/<id>/<filename>?rlkey=...&dl=0` — split on `?`, take the left part, then take the last `/`-separated segment.
- Download Dropbox file to `/tmp/<original_filename>` (convert `dl=0` → `dl=1` in the URL)
- `try/finally` guarantees temp file deletion on success or failure
- `librosa.load(path, sr=None)` — preserve native sample rate
- BPM: `librosa.beat.beat_track()` → round to nearest integer
- Duration: `librosa.get_duration(path=path)` → format as `M:SS`
- Log wall-clock time per track

### Artist name resolution

- `artist(s)` field returns relation IDs → fetch each artist page via Notion API
- Artist name is in the `artist` rich_text property (NOT the page title)
- Cache: `{page_url: artist_name}` dict, cleared each poll cycle
- Join multiple names with ` x ` before slugifying (see Filename Standard above)
- 0.35s sleep between all Notion API calls

### Error handling

On any per-track error (download failure, librosa failure, Notion write failure):
1. Log the error + full traceback to Railway logs
2. Post a Notion comment to the track page: `"enrich_tracks error [YYYY-MM-DD]: <short message>"`
3. Add the page ID to `_failed_ids` (in-memory set, lives for the process lifetime)
4. Continue to next track — never crash the loop

`_failed_ids` is NOT persisted. Railway restart clears it, which is the desired retry mechanism.

### Filename proposal (Phase 1 — log only)

After successful enrichment, log the proposed rename using the "filename matches" check above:
```
CURRENT:  Sultan-Shepard-RnR-Lane-8-Remix-GBEWA2303320.flac
PROPOSED: GBEWA2303320_Sultan-Shepard_RnR-Lane-8-Remix_Remix.flac
```

No Dropbox API calls in Phase 1.

### DRY_RUN

`DRY_RUN = True` at module level (never change the default).
- `True`: log proposed Notion PATCH, do not execute. Filename proposal logging is always performed regardless of `DRY_RUN`.
- `False`: execute PATCH to write `bpm` and `duration`

### Polling loop

```
while True:
    clear _artist_cache
    log ISO timestamp + count of tracks returned from Notion query (pre-_failed_ids filter)
    for each track:
        skip if page_id in _failed_ids
        process_track()  # errors caught, logged, added to _failed_ids
    sleep 300s
```

---

## Phase 2 — `rename_tracks.py`

### Trigger condition

Process a track only when ALL are true:
- `isrc` is not empty
- `master` (Dropbox URL) is not empty
- `bpm` is populated AND `duration` is populated (enrichment complete)
- Current Dropbox filename does NOT match the target format (per "filename matches" definition above)
- Page ID is not in `_failed_ids`

### Per-track flow

1. Resolve artist names (same cache pattern as Phase 1, cache cleared each poll cycle)
2. Build proposed filename using confirmed standard
3. Apply "filename matches" check — if already correct, log `filename OK` and skip (no Dropbox calls made)
4. Get fresh Dropbox access token via `get_dropbox_access_token()` — called once here, reused for all Dropbox calls in steps 5–8
5. Normalise the `master` URL to `dl=0` form (strip any `dl=1`) before any Dropbox API call — the stored value in Notion is always `dl=0`, but normalise defensively. Call `POST /sharing/get_shared_link_metadata` with the normalised URL → extract `path_display` (full Dropbox path including folder)
6. Construct `new_path` = same folder as `path_display` + proposed filename
7. Call `POST /files/move_v2` with `from_path` = `path_display`, `to_path` = `new_path`
8. Call `POST /sharing/create_shared_link_with_settings` on `new_path` to get a fresh share URL. If Dropbox returns `shared_link_already_exists`, call `POST /sharing/list_shared_links` with `{"path": new_path}` and use the first URL returned.
9. PATCH Notion `master` field with new share URL
10. Post Notion comment: `"Renamed: old_name.flac → new_name.flac"`

All Dropbox calls use a fresh access token (one `get_dropbox_access_token()` call per track).

### Partial failure handling

If step 7 (move) succeeds but step 8/9 (Notion update) fails:
- Log the error with explicit note: `"File renamed in Dropbox but Notion master URL not updated — manual fix required"`
- Post Notion comment with same message (this error comment is always posted regardless of DRY_RUN, since the move already happened)
- Add to `_failed_ids` to prevent re-processing

Note: when `DRY_RUN = True`, step 7 is never executed, so this partial failure path is unreachable.

### Error handling (all other failures)

Same pattern as Phase 1:
1. Log error + full traceback
2. Post Notion comment: `"rename_tracks error [YYYY-MM-DD]: <short message>"`
3. Add page ID to `_failed_ids`
4. Continue to next track

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

Fresh token fetched once per track — never expires. If `get_dropbox_access_token()` fails (network error or returns `None`), treat as a per-track error: log, post Notion comment, add to `_failed_ids`, skip track.

All Dropbox API calls must include:
- `Authorization: Bearer <access_token>`
- `Dropbox-API-Select-User: <DROPBOX_MEMBER_ID>`
- `Dropbox-API-Path-Root: <DROPBOX_PATH_ROOT>`

`DROPBOX_PATH_ROOT` value format (JSON string as required by Dropbox team namespace API):
```
{".tag": "namespace_id", "namespace_id": "2628699171"}
```
This value is already set in `tnh-invoice-portal` Railway env vars — copy it verbatim.

### DRY_RUN

`DRY_RUN = True` at module level (never change the default).
- `True`: log proposed rename + Notion update, do not execute any Dropbox or Notion writes
- `False`: execute full flow

### Polling loop

```
while True:
    clear _artist_cache
    log ISO timestamp + count of tracks returned from Notion query (pre-_failed_ids filter)
    for each track:
        skip if page_id in _failed_ids
        process_track()  # errors caught, logged, added to _failed_ids
    sleep 300s
```

---

## Environment Variables

| Variable | Phase | Notes |
|----------|-------|-------|
| `NOTION_TOKEN` | 1 + 2 | Existing — used across all services |
| `DROPBOX_APP_KEY` | 2 | Existing — copy from `tnh-invoice-portal` |
| `DROPBOX_APP_SECRET` | 2 | Existing — copy from `tnh-invoice-portal` |
| `DROPBOX_REFRESH_TOKEN` | 2 | Existing — copy from `tnh-invoice-portal` |
| `DROPBOX_MEMBER_ID` | 2 | Existing — copy from `tnh-invoice-portal` |
| `DROPBOX_PATH_ROOT` | 2 | Existing — copy from `tnh-invoice-portal`. Format: `{".tag": "namespace_id", "namespace_id": "2628699171"}` |

No new credentials required. Tracks DB ID (`795482ebef3c4830ac7e3c037deaab68`) is hardcoded in both scripts.

**`_failed_ids` scoping:** each script maintains its own independent in-memory `_failed_ids` set. A failure in Phase 1 (`enrich_tracks.py`) does NOT affect Phase 2's skip list, and vice versa.

---

## Dependencies

Both scripts use raw `requests` for all HTTP calls (Notion API + Dropbox API). No SDK.

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
- Renaming files to a different folder (in-place only)
- Moving files between team namespaces
