# Track Enricher Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate `enrich_tracks.py` — a Railway worker that polls the Notion Tracks DB every 5 minutes, downloads audio from Dropbox, extracts BPM and duration via librosa, writes them back to Notion, and logs proposed standardised filename renames.

**Architecture:** Single-file Railway worker in a new `tnh-track-enricher/` service directory. Pure logic functions (slugify, filename construction, duration format) are unit-tested independently. Notion API calls and audio analysis are validated manually via `DRY_RUN = True` against real tracks. Error handling posts Notion comments and uses an in-memory skip set — no schema changes required.

**Tech Stack:** Python 3, librosa, soundfile, requests (raw HTTP — no Notion SDK). Deployed to Railway as a worker process.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `tnh-track-enricher/enrich_tracks.py` | Create | Main worker: polling loop, Notion API, Dropbox download, audio analysis, filename proposals |
| `tnh-track-enricher/requirements.txt` | Create | Python dependencies |
| `tnh-track-enricher/Procfile` | Create | Railway process definition |
| `tnh-track-enricher/railway.toml` | Create | Railway build config |
| `tnh-track-enricher/tests/test_enrich_tracks.py` | Create | Unit tests for all pure functions |

The existing draft at `/Users/pete/enrich_tracks.py` is superseded by this plan — do not copy it verbatim. Several details differ from the spec (slugify double-hyphen collapse, Notion comment error handling, query filter completeness).

---

## Task 1: Create service directory and config files

**Files:**
- Create: `tnh-track-enricher/requirements.txt`
- Create: `tnh-track-enricher/Procfile`
- Create: `tnh-track-enricher/railway.toml`
- Create: `tnh-track-enricher/tests/__init__.py`

- [ ] **Step 1: Create the service directory structure**

```bash
mkdir -p tnh-track-enricher/tests
touch tnh-track-enricher/tests/__init__.py
```

- [ ] **Step 2: Create `requirements.txt`**

```
librosa
soundfile
requests
```

- [ ] **Step 3: Create `Procfile`**

```
worker: python enrich_tracks.py
```

- [ ] **Step 4: Create `railway.toml`**

```toml
[build]
builder = "NIXPACKS"

[deploy]
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3
```

- [ ] **Step 5: Commit**

```bash
cd tnh-track-enricher
git add requirements.txt Procfile railway.toml tests/__init__.py
git commit -m "chore: scaffold tnh-track-enricher service"
```

---

## Task 2: Unit tests for pure functions

**Files:**
- Create: `tnh-track-enricher/tests/test_enrich_tracks.py`

These functions have no external dependencies — test them before writing the implementation.

- [ ] **Step 1: Create the test file with all pure-function tests**

```python
# tnh-track-enricher/tests/test_enrich_tracks.py
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# --- format_duration ---

def test_format_duration_exact_minutes():
    from enrich_tracks import format_duration
    assert format_duration(360.0) == "6:00"

def test_format_duration_with_seconds():
    from enrich_tracks import format_duration
    assert format_duration(402.5) == "6:42"

def test_format_duration_no_leading_zero_on_minutes():
    from enrich_tracks import format_duration
    assert format_duration(65.0) == "1:05"

def test_format_duration_zero_minutes():
    from enrich_tracks import format_duration
    assert format_duration(45.0) == "0:45"

def test_format_duration_rounds_down():
    from enrich_tracks import format_duration
    # truncates to whole seconds, does not round up
    assert format_duration(61.9) == "1:01"

# --- _strip_isrc_hyphens ---

def test_strip_isrc_hyphens_removes_all():
    from enrich_tracks import _strip_isrc_hyphens
    assert _strip_isrc_hyphens("GB-EWA-23-03320") == "GBEWA2303320"

def test_strip_isrc_hyphens_no_hyphens():
    from enrich_tracks import _strip_isrc_hyphens
    assert _strip_isrc_hyphens("GBEWA2303320") == "GBEWA2303320"

# --- _slugify ---

def test_slugify_spaces_to_hyphens():
    from enrich_tracks import _slugify
    assert _slugify("Lane 8") == "Lane-8"

def test_slugify_strips_special_chars():
    from enrich_tracks import _slugify
    assert _slugify("RnR (Lane 8 Remix)") == "RnR-Lane-8-Remix"

def test_slugify_collapses_double_hyphens():
    from enrich_tracks import _slugify
    # "Sultan + Shepard": spaces→hyphens → "Sultan-+-Shepard"
    # strip non-alnum/hyphen → "Sultan--Shepard"
    # collapse runs → "Sultan-Shepard"
    assert _slugify("Sultan + Shepard") == "Sultan-Shepard"

def test_slugify_three_artists_joined():
    from enrich_tracks import _slugify
    combined = "Lane 8 x Sultan + Shepard x sadhappy"
    assert _slugify(combined) == "Lane-8-x-Sultan-Shepard-x-sadhappy"

def test_slugify_no_trailing_hyphens():
    from enrich_tracks import _slugify
    result = _slugify("Track Name!")
    assert not result.endswith("-")
    assert not result.startswith("-")

# --- build_proposed_filename ---

def test_build_proposed_filename_single_artist_with_version():
    from enrich_tracks import build_proposed_filename
    result = build_proposed_filename(
        isrc="GB-EWA-23-03320",
        artist_names=["Sultan + Shepard"],
        track_title="RnR (Lane 8 Remix)",
        version=["Remix"],
        original_filename="Sultan-Shepard-RnR-Lane-8-Remix-GBEWA2303320.flac",
    )
    assert result == "GBEWA2303320_Sultan-Shepard_RnR-Lane-8-Remix_Remix.flac"

def test_build_proposed_filename_three_artists():
    from enrich_tracks import build_proposed_filename
    result = build_proposed_filename(
        isrc="GBTNHH2500001",
        artist_names=["Lane 8", "Sultan + Shepard", "sadhappy"],
        track_title="Disappear",
        version=["Extended Mix"],
        original_filename="Lane-8-x-S-S-x-sadhappy-Disappear-v19m.wav",
    )
    assert result == "GBTNHH2500001_Lane-8-x-Sultan-Shepard-x-sadhappy_Disappear_Extended-Mix.wav"

def test_build_proposed_filename_no_version():
    from enrich_tracks import build_proposed_filename
    result = build_proposed_filename(
        isrc="GBTNHH2500001",
        artist_names=["Lane 8"],
        track_title="Disappear",
        version=[],
        original_filename="Lane-8-Disappear.wav",
    )
    assert result == "GBTNHH2500001_Lane-8_Disappear.wav"

def test_build_proposed_filename_uses_first_version_only():
    from enrich_tracks import build_proposed_filename
    result = build_proposed_filename(
        isrc="GBTNHH2500001",
        artist_names=["Lane 8"],
        track_title="Disappear",
        version=["Extended Mix", "Radio Edit"],
        original_filename="Lane-8-Disappear.wav",
    )
    assert result == "GBTNHH2500001_Lane-8_Disappear_Extended-Mix.wav"

def test_build_proposed_filename_preserves_extension():
    from enrich_tracks import build_proposed_filename
    result = build_proposed_filename(
        isrc="GBTNHH2500001",
        artist_names=["Lane 8"],
        track_title="Disappear",
        version=["Extended Mix"],
        original_filename="track.aiff",
    )
    assert result.endswith(".aiff")

# --- filename_matches ---

def test_filename_matches_correct_format():
    from enrich_tracks import filename_matches
    assert filename_matches("GBEWA2303320_Sultan-Shepard_RnR_Remix.flac", "GB-EWA-23-03320") is True

def test_filename_matches_isrc_present_but_not_first():
    from enrich_tracks import filename_matches
    # ISRC appears but is not the first _ segment
    assert filename_matches("Sultan-Shepard-GBEWA2303320.flac", "GB-EWA-23-03320") is False

def test_filename_matches_no_isrc():
    from enrich_tracks import filename_matches
    assert filename_matches("Sultan-Shepard-Track.flac", "GB-EWA-23-03320") is False

def test_filename_matches_case_insensitive():
    from enrich_tracks import filename_matches
    assert filename_matches("gbewa2303320_Sultan-Shepard_Track.flac", "GB-EWA-23-03320") is True

def test_filename_matches_version_less():
    from enrich_tracks import filename_matches
    # Version-less correctly formatted file still matches
    assert filename_matches("GBTNHH2500001_Lane-8_Disappear.wav", "GBTNHH2500001") is True

# --- extract_dropbox_filename ---

def test_extract_dropbox_filename_standard_url():
    from enrich_tracks import extract_dropbox_filename
    url = "https://www.dropbox.com/scl/fi/abc123/Sultan-Shepard-Track.flac?rlkey=xyz&dl=0"
    assert extract_dropbox_filename(url) == "Sultan-Shepard-Track.flac"

def test_extract_dropbox_filename_wav():
    from enrich_tracks import extract_dropbox_filename
    url = "https://www.dropbox.com/scl/fi/abc123/Lane-8-Disappear.wav?rlkey=xyz&dl=0"
    assert extract_dropbox_filename(url) == "Lane-8-Disappear.wav"

# --- dropbox_direct_url ---

def test_dropbox_direct_url_converts_dl0_to_dl1():
    from enrich_tracks import dropbox_direct_url
    url = "https://www.dropbox.com/scl/fi/abc123/track.wav?rlkey=xyz&dl=0"
    assert dropbox_direct_url(url) == "https://www.dropbox.com/scl/fi/abc123/track.wav?rlkey=xyz&dl=1"
```

- [ ] **Step 2: Run tests to confirm they all fail (module not found is expected)**

```bash
cd tnh-track-enricher
pip install librosa soundfile requests pytest
pytest tests/test_enrich_tracks.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError` or import errors — `enrich_tracks.py` doesn't exist yet.

- [ ] **Step 3: Commit the tests**

```bash
git add tests/test_enrich_tracks.py
git commit -m "test: add unit tests for enrich_tracks pure functions"
```

---

## Task 3: Implement pure functions

**Files:**
- Create: `tnh-track-enricher/enrich_tracks.py` (pure functions section only)

Write just enough to make the tests pass. No Notion calls, no librosa, no requests yet.

- [ ] **Step 1: Create `enrich_tracks.py` with the pure functions**

```python
"""
enrich_tracks.py — Railway polling worker
Polls Notion Tracks DB every 5 minutes. For tracks with ISRC set but
BPM/duration missing, downloads from Dropbox, extracts audio features
via librosa, writes back to Notion. Logs proposed filename renames
(Phase 1 — log only, no actual renames).

pip install librosa soundfile requests
"""

import logging
import os
import re
import time
import traceback
from datetime import date, datetime, timezone

import requests
import librosa

# ── Config ────────────────────────────────────────────────────────────────────

DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() not in ("false", "0", "no")

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
TRACKS_DB_ID = "795482ebef3c4830ac7e3c037deaab68"
POLL_INTERVAL = 300
NOTION_SLEEP  = 0.35

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── State ─────────────────────────────────────────────────────────────────────

_failed_ids: set[str] = set()
_artist_cache: dict[str, str] = {}

# ── Pure functions ────────────────────────────────────────────────────────────

def format_duration(seconds: float) -> str:
    """Format seconds as M:SS (no leading zero on minutes)."""
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def _strip_isrc_hyphens(isrc: str) -> str:
    return isrc.replace("-", "")


def _slugify(text: str) -> str:
    """Replace spaces with hyphens, strip non-alphanumeric/hyphen, collapse runs."""
    text = text.replace(" ", "-")
    text = re.sub(r"[^A-Za-z0-9\-]", "", text)
    text = re.sub(r"-{2,}", "-", text)
    text = text.strip("-")
    return text


def build_proposed_filename(
    isrc: str,
    artist_names: list[str],
    track_title: str,
    version: list[str],
    original_filename: str,
) -> str:
    ext = ("." + original_filename.rsplit(".", 1)[-1]) if "." in original_filename else ""
    isrc_slug = _strip_isrc_hyphens(isrc)
    artist_slug = _slugify(" x ".join(artist_names))
    track_slug = _slugify(track_title)

    if version:
        version_slug = version[0].replace(" ", "-")
        return f"{isrc_slug}_{artist_slug}_{track_slug}_{version_slug}{ext}"
    return f"{isrc_slug}_{artist_slug}_{track_slug}{ext}"


def filename_matches(filename: str, isrc: str) -> bool:
    """Return True if filename already matches the target format."""
    stripped = _strip_isrc_hyphens(isrc)
    if stripped.lower() not in filename.lower():
        return False
    return filename.lower().startswith(f"{stripped.lower()}_")


def extract_dropbox_filename(url: str) -> str:
    """Extract filename from Dropbox share URL path (before query string)."""
    return url.split("?")[0].rstrip("/").split("/")[-1]


def dropbox_direct_url(url: str) -> str:
    return re.sub(r"dl=0", "dl=1", url)
```

- [ ] **Step 2: Run the tests**

```bash
pytest tests/test_enrich_tracks.py -v
```

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add enrich_tracks.py
git commit -m "feat: add enrich_tracks pure functions (format_duration, slugify, filename)"
```

---

## Task 4: Implement Notion API helpers

**Files:**
- Modify: `tnh-track-enricher/enrich_tracks.py` (append Notion section)

No unit tests for API calls — these are validated manually via `DRY_RUN = True`.

- [ ] **Step 1: Add Notion helpers to `enrich_tracks.py` after the pure functions section**

```python
# ── Notion helpers ────────────────────────────────────────────────────────────

def _notion_sleep_post(url: str, payload: dict) -> dict:
    time.sleep(NOTION_SLEEP)
    r = requests.post(url, headers=NOTION_HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def _notion_sleep_get(url: str) -> dict:
    time.sleep(NOTION_SLEEP)
    r = requests.get(url, headers=NOTION_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def _notion_sleep_patch(url: str, payload: dict) -> dict:
    time.sleep(NOTION_SLEEP)
    r = requests.patch(url, headers=NOTION_HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def post_notion_comment(page_id: str, message: str) -> None:
    """Post a comment to a Notion page. Never raises — logs on failure."""
    try:
        _notion_sleep_post(
            "https://api.notion.com/v1/comments",
            {
                "parent": {"page_id": page_id},
                "rich_text": [{"type": "text", "text": {"content": message}}],
            },
        )
    except Exception:
        log.warning("Failed to post Notion comment to %s:\n%s", page_id, traceback.format_exc())


def get_artist_name(page_url: str) -> str:
    """Fetch artist name from a Notion artist page (uses cache)."""
    if page_url in _artist_cache:
        return _artist_cache[page_url]

    # Extract bare page ID from URL: last path segment, remove slug prefix
    page_id = page_url.rstrip("/").split("/")[-1].split("?")[0]
    if "-" in page_id:
        page_id = page_id.split("-")[-1]

    data = _notion_sleep_get(f"https://api.notion.com/v1/pages/{page_id}")
    props = data.get("properties", {})

    # Artist name is in the "artist" rich_text property, NOT the page title
    rich_text = props.get("artist", {}).get("rich_text", [])
    name = "".join(t.get("plain_text", "") for t in rich_text).strip()

    if not name:
        # Fallback to title only if artist property is empty
        title_parts = props.get("Name", props.get("title", {})).get("title", [])
        name = "".join(t.get("plain_text", "") for t in title_parts).strip() or "Unknown"
        log.warning("Artist property empty for %s, fell back to title: %s", page_url, name)

    _artist_cache[page_url] = name
    return name


def query_tracks() -> list[dict]:
    """Query Notion for tracks needing enrichment. Server-side filter + paginated."""
    url = f"https://api.notion.com/v1/databases/{TRACKS_DB_ID}/query"
    pages: list[dict] = []
    cursor = None

    while True:
        payload: dict = {
            "filter": {
                "and": [
                    {"property": "isrc",   "rich_text": {"is_not_empty": True}},
                    {"property": "master", "url":       {"is_not_empty": True}},
                    {"or": [
                        {"property": "bpm",      "number":    {"is_empty": True}},
                        {"property": "duration", "rich_text": {"is_empty": True}},
                    ]},
                ]
            },
            "page_size": 100,
        }
        if cursor:
            payload["start_cursor"] = cursor

        data = _notion_sleep_post(url, payload)
        pages.extend(data.get("results", []))

        if data.get("has_more"):
            cursor = data["next_cursor"]
        else:
            break

    return pages


def extract_track_fields(page: dict) -> dict:
    """Parse fields from a Notion track page."""
    props = page.get("properties", {})

    def rich_text(key: str) -> str:
        return "".join(t.get("plain_text", "") for t in props.get(key, {}).get("rich_text", [])).strip()

    def title(key: str) -> str:
        return "".join(t.get("plain_text", "") for t in props.get(key, {}).get("title", [])).strip()

    return {
        "page_id":     page["id"],
        "track":       title("track") or rich_text("track"),
        "isrc":        rich_text("isrc"),
        "bpm":         props.get("bpm", {}).get("number"),
        "duration":    rich_text("duration"),
        "master":      (props.get("master", {}).get("url") or "").strip(),
        "version":     [o["name"] for o in props.get("version", {}).get("multi_select", [])],
        "artist_urls": [
            f"https://www.notion.so/{r['id'].replace('-', '')}"
            for r in props.get("artist(s)", {}).get("relation", [])
        ],
    }


def write_bpm_duration(page_id: str, bpm: int, duration: str) -> None:
    payload = {
        "properties": {
            "bpm":      {"number": bpm},
            "duration": {"rich_text": [{"type": "text", "text": {"content": duration}}]},
        }
    }
    if DRY_RUN:
        log.info("[DRY RUN] Would PATCH %s → bpm=%d, duration=%s", page_id, bpm, duration)
    else:
        _notion_sleep_patch(f"https://api.notion.com/v1/pages/{page_id}", payload)
        log.info("Wrote to Notion: bpm=%d, duration=%s", bpm, duration)
```

- [ ] **Step 2: Re-run tests to confirm nothing broke**

```bash
pytest tests/test_enrich_tracks.py -v
```

Expected: All tests still pass.

- [ ] **Step 3: Commit**

```bash
git add enrich_tracks.py
git commit -m "feat: add Notion API helpers (query, extract fields, write, comments)"
```

---

## Task 5: Implement audio analysis and per-track processing

**Files:**
- Modify: `tnh-track-enricher/enrich_tracks.py` (append remaining sections)

- [ ] **Step 1: Add Dropbox download, audio analysis, and `process_track` to `enrich_tracks.py`**

```python
# ── Dropbox download ──────────────────────────────────────────────────────────

def download_dropbox_file(url: str) -> str:
    """Download file to /tmp/<filename>. Returns local path."""
    filename = extract_dropbox_filename(url)
    local_path = f"/tmp/{filename}"
    log.info("Downloading %s ...", filename)
    r = requests.get(dropbox_direct_url(url), timeout=120, stream=True)
    r.raise_for_status()
    with open(local_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    return local_path


# ── Audio analysis ────────────────────────────────────────────────────────────

def analyse_audio(path: str) -> tuple[int, str]:
    """Return (bpm, duration_str). Logs wall-clock time."""
    t0 = time.monotonic()
    y, sr = librosa.load(path, sr=None)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = int(round(float(tempo) if not hasattr(tempo, "__len__") else float(tempo[0])))
    duration = format_duration(librosa.get_duration(path=path))
    log.info("Analysis done in %.1fs — BPM=%d, duration=%s", time.monotonic() - t0, bpm, duration)
    return bpm, duration


# ── Per-track processing ──────────────────────────────────────────────────────

def process_track(track: dict) -> None:
    name = track["track"] or track["page_id"]
    log.info("── %s | ISRC: %s", name, track["isrc"])

    # Resolve artist names
    artist_names: list[str] = []
    for url in track["artist_urls"]:
        try:
            artist_names.append(get_artist_name(url))
        except Exception:
            log.warning("Could not resolve artist %s:\n%s", url, traceback.format_exc())

    original_filename = extract_dropbox_filename(track["master"])
    local_path = None

    try:
        local_path = download_dropbox_file(track["master"])
        bpm, duration = analyse_audio(local_path)
        write_bpm_duration(track["page_id"], bpm, duration)
        log.info("Result — BPM=%d, duration=%s", bpm, duration)

        # Filename proposal (log only — no API calls)
        proposed = build_proposed_filename(
            track["isrc"], artist_names, track["track"], track["version"], original_filename
        )
        if filename_matches(original_filename, track["isrc"]):
            log.info("Filename OK — no rename needed: %s", original_filename)
        else:
            log.info("CURRENT:  %s", original_filename)
            log.info("PROPOSED: %s", proposed)

    finally:
        if local_path:
            try:
                os.remove(local_path)
            except OSError:
                log.warning("Could not delete temp file: %s", local_path)


# ── Poll cycle ────────────────────────────────────────────────────────────────

def poll_cycle() -> None:
    global _artist_cache
    _artist_cache = {}

    log.info("=== Poll cycle: %s ===", datetime.now(timezone.utc).isoformat())

    try:
        pages = query_tracks()
    except Exception:
        log.error("Notion query failed:\n%s", traceback.format_exc())
        return

    queued = [p for p in pages if p["id"].replace("-", "") not in _failed_ids]
    log.info("Tracks queued: %d (of %d returned)", len(queued), len(pages))

    for page in queued:
        try:
            track = extract_track_fields(page)
            process_track(track)
        except Exception:
            page_id = page["id"].replace("-", "")
            name = (
                "".join(
                    t.get("plain_text", "")
                    for t in page.get("properties", {})
                    .get("track", {})
                    .get("title", [])
                ) or page_id
            )
            tb = traceback.format_exc()
            log.error("Error processing '%s':\n%s", name, tb)
            short_msg = tb.strip().splitlines()[-1][:200]
            post_notion_comment(
                page_id,
                f"enrich_tracks error [{date.today()}]: {short_msg}",
            )
            _failed_ids.add(page_id)
            continue


def main() -> None:
    log.info("enrich_tracks starting — DRY_RUN=%s, interval=%ds", DRY_RUN, POLL_INTERVAL)
    while True:
        poll_cycle()
        log.info("Sleeping %ds...", POLL_INTERVAL)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run all tests**

```bash
pytest tests/test_enrich_tracks.py -v
```

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add enrich_tracks.py
git commit -m "feat: add audio analysis, per-track processing, and polling loop"
```

---

## Task 6: Manual validation with DRY_RUN = True

Validate against real Notion data before deploying.

- [ ] **Step 1: Set `NOTION_TOKEN` and run one cycle**

```bash
cd tnh-track-enricher
NOTION_TOKEN=your_token python enrich_tracks.py
```

Expected log output after first cycle:
```
=== Poll cycle: 2026-03-20T...Z ===
Tracks queued: N (of N returned)
── <track name> | ISRC: <isrc>
Downloading <filename> ...
Analysis done in X.Xs — BPM=NNN, duration=M:SS
[DRY RUN] Would PATCH <page_id> → bpm=NNN, duration=M:SS
CURRENT:  <original_filename>
PROPOSED: <isrc>_<artist>_<track>_<version>.<ext>
```

- [ ] **Step 2: Check a known track manually**

Pick a track where you know the BPM. Confirm the logged BPM is within ±5 of expected. Confirm duration format is `M:SS` with no leading zero on minutes.

- [ ] **Step 3: Verify filename proposals look correct**

Review 5–10 proposed filenames against the standard:
```
{ISRC}_{Artist-Slug}_{Track-Slug}_{Version-Slug}.{ext}
```

Check: ISRC first, `_` as separator, hyphens within segments, correct extension.

- [ ] **Step 4: Simulate an error to test comment posting**

Temporarily corrupt the `master` URL of a test track in Notion by changing the domain to something invalid (e.g. `https://invalid.example.com/...`) — keep the URL non-empty so the track still passes the server-side filter and reaches `process_track`. Restart the script and confirm:
- A Notion comment appears on the track page with `"enrich_tracks error [date]: ..."`
- The track is skipped on the next poll cycle (check logs — it should not appear again)
- The loop continues processing other tracks

Restore the URL after testing.

- [ ] **Step 5: Commit validation notes**

```bash
git commit --allow-empty -m "chore: phase 1 manually validated with DRY_RUN=True"
```

---

## Task 7: Deploy to Railway

- [ ] **Step 1: Create the Railway service**

In the Railway dashboard: New Project → Deploy from GitHub repo → select or create `tnh-track-enricher`. Set root directory to `tnh-track-enricher/` if working from a monorepo, or push `tnh-track-enricher/` as its own repo.

- [ ] **Step 2: Set environment variables in Railway**

Required for Phase 1:
- `NOTION_TOKEN` — copy from another service

- [ ] **Step 3: Deploy and monitor first cycle**

Trigger a deploy. Watch Railway logs for the first poll cycle output. Confirm it matches the local dry-run output.

- [ ] **Step 4: Enable live writes via Railway env var**

In Railway dashboard, add environment variable:
```
DRY_RUN=false
```

No code change needed — `DRY_RUN` reads from env, defaults to `true` if unset. Railway will redeploy automatically.

Monitor logs to confirm BPM/duration values are written to Notion. Spot-check 2–3 tracks in Notion to confirm the fields are populated.

---

## What's Next

Phase 2 (`rename_tracks.py`) gets its own plan once Phase 1 is validated in production. It will require:
- `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`, `DROPBOX_MEMBER_ID`, `DROPBOX_PATH_ROOT` (copy from `tnh-invoice-portal`)
- Dropbox `/sharing/get_shared_link_metadata` → `/files/move_v2` → `/sharing/create_shared_link_with_settings`
- Notion `master` URL update after rename
- See spec: `docs/superpowers/specs/2026-03-20-track-enricher-design.md`
