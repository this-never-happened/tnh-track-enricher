"""
enrich_tracks.py — Railway polling worker
Polls Notion Tracks DB every 5 minutes. For tracks with ISRC set but
BPM/duration missing, downloads from Dropbox, extracts audio features
via librosa, writes back to Notion. Renames Dropbox file to proposed
ISRC-prefixed filename after enrichment.

pip install librosa soundfile requests
"""

import logging
import os
import re
import time
import traceback
from datetime import date, datetime, timezone
from urllib.parse import unquote

import requests
import librosa

# ── Config ────────────────────────────────────────────────────────────────────

DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() not in ("false", "0", "no")

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
TRACKS_DB_ID = "795482ebef3c4830ac7e3c037deaab68"
POLL_INTERVAL = 300
NOTION_SLEEP  = 0.35

DROPBOX_APP_KEY      = os.environ.get("DROPBOX_APP_KEY", "")
DROPBOX_APP_SECRET   = os.environ.get("DROPBOX_APP_SECRET", "")
DROPBOX_REFRESH_TOKEN = os.environ.get("DROPBOX_REFRESH_TOKEN", "")
DROPBOX_MEMBER_ID    = os.environ.get("DROPBOX_MEMBER_ID", "")
DROPBOX_PATH_ROOT    = os.environ.get("DROPBOX_PATH_ROOT", "")

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

SPOTIFY_CLIENT_ID     = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── State ─────────────────────────────────────────────────────────────────────

_failed_ids: set[str] = set()

_spotify_token: str = ""
_spotify_token_expiry: float = 0.0

_KEY_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

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
    track_title: str,
    version: list[str],
    original_filename: str,
) -> str:
    ext = ("." + original_filename.rsplit(".", 1)[-1]) if "." in original_filename else ""
    isrc_slug = _strip_isrc_hyphens(isrc)

    # Strip version text from title if it appears in parentheses (e.g. "Title (Extended Mix)")
    clean_title = track_title
    if version:
        for v in version:
            clean_title = re.sub(rf"\s*\({re.escape(v)}\)\s*$", "", clean_title).strip()

    track_slug = _slugify(clean_title)

    if version:
        version_slug = _slugify(version[0])
        return f"{isrc_slug}_{track_slug}_{version_slug}{ext}"
    return f"{isrc_slug}_{track_slug}{ext}"


def filename_matches(filename: str, isrc: str) -> bool:
    """Return True if filename already matches the target format."""
    stripped = _strip_isrc_hyphens(isrc)
    if stripped.lower() not in filename.lower():
        return False
    return filename.lower().startswith(f"{stripped.lower()}_")


def extract_dropbox_filename(url: str) -> str:
    """Extract filename from Dropbox share URL path (before query string), URL-decoded."""
    return unquote(url.split("?")[0].rstrip("/").split("/")[-1])


def dropbox_direct_url(url: str) -> str:
    return re.sub(r"dl=0", "dl=1", url)


def _get_dropbox_access_token() -> str | None:
    if not DROPBOX_REFRESH_TOKEN:
        return None
    r = requests.post("https://api.dropbox.com/oauth2/token", data={
        "grant_type": "refresh_token",
        "refresh_token": DROPBOX_REFRESH_TOKEN,
        "client_id": DROPBOX_APP_KEY,
        "client_secret": DROPBOX_APP_SECRET,
    }, timeout=30)
    if r.status_code == 200:
        return r.json().get("access_token")
    log.warning("Dropbox token refresh failed: %s", r.text[:200])
    return None


def _dropbox_api_headers(access_token: str) -> dict:
    h = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    if DROPBOX_MEMBER_ID:
        h["Dropbox-API-Select-User"] = DROPBOX_MEMBER_ID
    if DROPBOX_PATH_ROOT:
        h["Dropbox-API-Path-Root"] = DROPBOX_PATH_ROOT
    return h


def rename_dropbox_file(share_url: str, new_filename: str) -> str | None:
    """Rename the Dropbox file to new_filename in the same directory. Returns new path on success."""
    log.info("Dropbox rename: starting for %s", new_filename)
    try:
        access_token = _get_dropbox_access_token()
    except Exception:
        log.warning("Dropbox token fetch exception:\n%s", traceback.format_exc())
        return None
    if not access_token:
        log.warning("Dropbox rename skipped — no access token")
        return None

    headers = _dropbox_api_headers(access_token)

    try:
        r = requests.post(
            "https://api.dropboxapi.com/2/sharing/get_shared_link_metadata",
            headers=headers,
            json={"url": share_url},
            timeout=30,
        )
        log.info("Dropbox metadata status: %d", r.status_code)
        if r.status_code != 200:
            log.warning("Dropbox metadata fetch failed: %s", r.text[:300])
            return None

        meta = r.json()
        current_path = meta.get("path_display") or meta.get("path_lower")

        # Team accounts omit path from shared link metadata — resolve via file ID first
        if not current_path:
            file_id = meta.get("id")
            log.info("Dropbox: file ID from shared link metadata: %s", file_id)
            if file_id:
                r_meta = requests.post(
                    "https://api.dropboxapi.com/2/files/get_metadata",
                    headers=headers,
                    json={"path": file_id},
                    timeout=30,
                )
                log.info("Dropbox get_metadata status: %d", r_meta.status_code)
                if r_meta.status_code == 200:
                    current_path = r_meta.json().get("path_display") or r_meta.json().get("path_lower")
                    log.info("Dropbox: resolved path via file ID: %s", current_path)
                else:
                    log.warning("Dropbox get_metadata failed: %s", r_meta.text[:300])

        # Fall back to search if file ID lookup didn't resolve
        if not current_path:
            filename = meta.get("name") or extract_dropbox_filename(share_url)
            log.info("Dropbox: searching for filename %r", filename)
            r_search = requests.post(
                "https://api.dropboxapi.com/2/files/search_v2",
                headers=headers,
                json={"query": filename, "options": {"filename_only": True, "max_results": 10}},
                timeout=30,
            )
            if r_search.status_code != 200:
                log.warning("Dropbox search failed: %s", r_search.text[:300])
                return None
            matches = r_search.json().get("matches", [])
            for m in matches:
                file_meta = m.get("metadata", {}).get("metadata", {})
                if file_meta.get("name") == filename:
                    current_path = file_meta.get("path_display") or file_meta.get("path_lower")
                    break
            if not current_path:
                # Metadata name may be stale after a prior rename — try searching for the target name
                log.info("Dropbox: searching for already-renamed target %r", new_filename)
                r_search2 = requests.post(
                    "https://api.dropboxapi.com/2/files/search_v2",
                    headers=headers,
                    json={"query": new_filename, "options": {"filename_only": True, "max_results": 10}},
                    timeout=30,
                )
                if r_search2.status_code == 200:
                    for m in r_search2.json().get("matches", []):
                        file_meta = m.get("metadata", {}).get("metadata", {})
                        if file_meta.get("name") == new_filename:
                            current_path = file_meta.get("path_display") or file_meta.get("path_lower")
                            break
            if not current_path:
                log.warning("Dropbox: could not resolve path for %r or %r", filename, new_filename)
                return None

        parent = current_path.rsplit("/", 1)[0]
        new_path = f"{parent}/{new_filename}"

        if current_path == new_path:
            log.info("Dropbox file already has correct name: %s", new_filename)
            return new_path

        log.info("Renaming Dropbox file: %s -> %s", current_path, new_path)
        r2 = requests.post(
            "https://api.dropboxapi.com/2/files/move_v2",
            headers=headers,
            json={"from_path": current_path, "to_path": new_path, "autorename": False},
            timeout=30,
        )
        log.info("Dropbox move status: %d", r2.status_code)
        if r2.status_code == 200:
            log.info("Dropbox rename OK: %s", new_filename)
            return new_path
        log.warning("Dropbox move failed: %s", r2.text[:300])
        return None
    except Exception:
        log.warning("Dropbox rename exception:\n%s", traceback.format_exc())
        return None


def create_dropbox_share_link(new_path: str) -> str | None:
    """Create a shared link for the file at new_path. Returns the share URL or None."""
    try:
        access_token = _get_dropbox_access_token()
    except Exception:
        log.warning("Dropbox token fetch exception:\n%s", traceback.format_exc())
        return None
    if not access_token:
        return None

    headers = _dropbox_api_headers(access_token)
    r = requests.post(
        "https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings",
        headers=headers,
        json={"path": new_path},
        timeout=30,
    )
    if r.status_code == 200:
        url = r.json().get("url", "")
        log.info("New share link: %s", url)
        return url
    # Already shared — fetch the existing link
    if r.status_code == 409 and "shared_link_already_exists" in r.text:
        data = r.json().get("error", {}).get("shared_link_already_exists", {})
        url = data.get("metadata", {}).get("url", "")
        if url:
            log.info("Existing share link: %s", url)
            return url
        # Fall back to list_shared_links
        r2 = requests.post(
            "https://api.dropboxapi.com/2/sharing/list_shared_links",
            headers=headers,
            json={"path": new_path, "direct_only": True},
            timeout=30,
        )
        if r2.status_code == 200:
            links = r2.json().get("links", [])
            if links:
                url = links[0].get("url", "")
                log.info("Fetched existing share link: %s", url)
                return url
    log.warning("Failed to create share link: %s", r.text[:300])
    return None


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



# ── Spotify helpers ───────────────────────────────────────────────────────────

def get_spotify_token() -> str:
    global _spotify_token, _spotify_token_expiry
    if time.monotonic() < _spotify_token_expiry - 60:
        return _spotify_token
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "client_credentials",
            "client_id": SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        },
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    _spotify_token = data["access_token"]
    _spotify_token_expiry = time.monotonic() + data["expires_in"]
    log.info("Spotify token refreshed (expires in %ds)", data["expires_in"])
    return _spotify_token


def _spotify_get(url: str, **kwargs) -> requests.Response:
    """GET with automatic token injection and 429 backoff."""
    for attempt in range(3):
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {get_spotify_token()}"},
            timeout=15,
            **kwargs,
        )
        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", 5))
            log.warning("Spotify rate limited — sleeping %ds", retry_after)
            time.sleep(retry_after)
            continue
        return r
    r.raise_for_status()
    return r


def spotify_track_by_isrc(isrc: str) -> dict | None:
    r = _spotify_get(
        "https://api.spotify.com/v1/search",
        params={"q": f"isrc:{isrc}", "type": "track", "limit": 1},
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    items = r.json().get("tracks", {}).get("items", [])
    return items[0] if items else None


def spotify_audio_features(track_id: str) -> dict | None:
    r = _spotify_get(f"https://api.spotify.com/v1/audio-features/{track_id}")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def format_key(key_int: int, mode_int: int) -> str:
    if key_int == -1:
        return ""
    return f"{_KEY_NAMES[key_int]} {'major' if mode_int == 1 else 'minor'}"


def query_spotify_candidates() -> list[dict]:
    """Query tracks with ISRC set but key field empty."""
    url = f"https://api.notion.com/v1/databases/{TRACKS_DB_ID}/query"
    pages: list[dict] = []
    cursor = None
    while True:
        payload: dict = {
            "filter": {
                "and": [
                    {"property": "isrc", "rich_text": {"is_not_empty": True}},
                    {"property": "key",  "rich_text": {"is_empty": True}},
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


def write_spotify_fields(page_id: str, bpm: int, key: str) -> None:
    props: dict = {"bpm": {"number": bpm}}
    if key:
        props["key"] = {"rich_text": [{"type": "text", "text": {"content": key}}]}
    if DRY_RUN:
        log.info("[DRY RUN] Would PATCH %s → bpm=%d, key=%s", page_id, bpm, key or "(none)")
    else:
        _notion_sleep_patch(f"https://api.notion.com/v1/pages/{page_id}", {"properties": props})
        log.info("Wrote Spotify fields: bpm=%d, key=%s", bpm, key or "(none)")


def process_spotify_track(track: dict) -> None:
    name = track["track"] or track["page_id"]
    log.info("── Spotify: %s | ISRC: %s", name, track["isrc"])

    spotify_track = spotify_track_by_isrc(track["isrc"])
    if not spotify_track:
        log.info("No Spotify match for ISRC %s — skipping", track["isrc"])
        return

    features = spotify_audio_features(spotify_track["id"])
    if not features:
        log.info("No audio features for Spotify ID %s — skipping", spotify_track["id"])
        return

    bpm = int(round(features["tempo"]))
    key = format_key(features["key"], features["mode"])
    log.info("Spotify result: bpm=%d, key=%s", bpm, key or "(no key detected)")
    write_spotify_fields(track["page_id"], bpm, key)


def query_rename_candidates() -> list[dict]:
    """Query 50 least-recently-edited enriched tracks for rename check per cycle.

    Sorted ascending by last_edited_time so renamed tracks rotate to the bottom
    and unprocessed tracks bubble up — cycling through the full database across
    multiple poll cycles without timing out.
    """
    url = f"https://api.notion.com/v1/databases/{TRACKS_DB_ID}/query"
    payload: dict = {
        "filter": {
            "and": [
                {"property": "isrc",     "rich_text": {"is_not_empty": True}},
                {"property": "master",   "url":       {"is_not_empty": True}},
                {"property": "bpm",      "number":    {"is_not_empty": True}},
                {"property": "duration", "rich_text": {"is_not_empty": True}},
            ]
        },
        "sorts": [{"timestamp": "last_edited_time", "direction": "ascending"}],
        "page_size": 50,
    }
    data = _notion_sleep_post(url, payload)
    return data.get("results", [])


def query_no_isrc_candidates() -> list[dict]:
    """Query tracks that have a Dropbox master but no ISRC and need BPM/duration."""
    url = f"https://api.notion.com/v1/databases/{TRACKS_DB_ID}/query"
    payload = {
        "filter": {
            "and": [
                {"property": "master", "url":       {"is_not_empty": True}},
                {"property": "isrc",   "rich_text": {"is_empty": True}},
                {"or": [
                    {"property": "bpm",      "number":    {"is_empty": True}},
                    {"property": "duration", "rich_text": {"is_empty": True}},
                ]},
            ]
        },
        "sorts": [{"timestamp": "last_edited_time", "direction": "ascending"}],
        "page_size": 20,
    }
    data = _notion_sleep_post(url, payload)
    return data.get("results", [])


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
        "key":         rich_text("key"),
        "master":      (props.get("master", {}).get("url") or "").strip(),
        "version":     [o["name"] for o in props.get("version", {}).get("multi_select", [])],
    }


def write_master_url(page_id: str, url: str) -> None:
    payload = {"properties": {"master": {"url": url}}}
    if DRY_RUN:
        log.info("[DRY RUN] Would update master URL for %s -> %s", page_id, url)
    else:
        _notion_sleep_patch(f"https://api.notion.com/v1/pages/{page_id}", payload)
        log.info("Updated Notion master URL: %s", url)


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

    original_filename = extract_dropbox_filename(track["master"])
    local_path = None

    try:
        local_path = download_dropbox_file(track["master"])
        bpm, duration = analyse_audio(local_path)
        write_bpm_duration(track["page_id"], bpm, duration)
        log.info("Result — BPM=%d, duration=%s", bpm, duration)

        proposed = build_proposed_filename(
            track["isrc"], track["track"], track["version"], original_filename
        )
        if original_filename == proposed:
            log.info("Filename OK — no rename needed: %s", original_filename)
        elif DRY_RUN:
            log.info("[DRY RUN] Would rename: %s -> %s", original_filename, proposed)
        else:
            log.info("CURRENT:  %s", original_filename)
            log.info("PROPOSED: %s", proposed)
            new_path = rename_dropbox_file(track["master"], proposed)
            if new_path:
                new_url = create_dropbox_share_link(new_path)
                if new_url:
                    write_master_url(track["page_id"], new_url)

    finally:
        if local_path:
            try:
                os.remove(local_path)
            except OSError:
                log.warning("Could not delete temp file: %s", local_path)


# ── Poll cycle ────────────────────────────────────────────────────────────────

def poll_cycle() -> None:
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

    # Rename-only pass: catch enriched tracks whose Dropbox file wasn't renamed yet
    try:
        rename_pages = query_rename_candidates()
    except Exception:
        log.warning("Rename-candidate query failed:\n%s", traceback.format_exc())
        rename_pages = []

    for page in rename_pages:
        if page["id"].replace("-", "") in _failed_ids:
            continue
        try:
            track = extract_track_fields(page)
            original_filename = extract_dropbox_filename(track["master"])
            proposed = build_proposed_filename(
                track["isrc"], track["track"], track["version"], original_filename
            )
            if original_filename == proposed:
                continue
            log.info("Rename-only: %s -> %s", original_filename, proposed)
            if not DRY_RUN:
                new_path = rename_dropbox_file(track["master"], proposed)
                if new_path:
                    new_url = create_dropbox_share_link(new_path)
                    if new_url:
                        write_master_url(track["page_id"], new_url)
            else:
                log.info("[DRY RUN] Would rename: %s -> %s", original_filename, proposed)
        except Exception:
            log.error("Rename-only error for %s:\n%s", page["id"], traceback.format_exc())

    # Spotify pass: fill key + override BPM for tracks with ISRC but no key yet
    if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
        try:
            spotify_pages = query_spotify_candidates()
        except Exception:
            log.warning("Spotify candidate query failed:\n%s", traceback.format_exc())
            spotify_pages = []

        if spotify_pages:
            log.info("Spotify enrichment candidates: %d", len(spotify_pages))

        for page in spotify_pages:
            if page["id"].replace("-", "") in _failed_ids:
                continue
            try:
                track = extract_track_fields(page)
                process_spotify_track(track)
            except Exception:
                page_id = page["id"].replace("-", "")
                log.error("Spotify error for %s:\n%s", page_id, traceback.format_exc())
                _failed_ids.add(page_id)
    else:
        log.debug("Spotify credentials not set — skipping Spotify pass")

    # No-ISRC pass: enrich BPM/duration for tracks with a master link but no ISRC yet
    try:
        no_isrc_pages = query_no_isrc_candidates()
    except Exception:
        log.warning("No-ISRC query failed:\n%s", traceback.format_exc())
        no_isrc_pages = []

    if no_isrc_pages:
        log.info("No-ISRC tracks to enrich: %d", len(no_isrc_pages))

    for page in no_isrc_pages:
        if page["id"].replace("-", "") in _failed_ids:
            continue
        local_path = None
        try:
            track = extract_track_fields(page)
            name = track["track"] or track["page_id"]
            log.info("── (no ISRC) %s", name)
            local_path = download_dropbox_file(track["master"])
            bpm, duration = analyse_audio(local_path)
            write_bpm_duration(track["page_id"], bpm, duration)
            log.info("Result — BPM=%d, duration=%s", bpm, duration)
        except Exception:
            page_id = page["id"].replace("-", "")
            log.error("No-ISRC error for %s:\n%s", page_id, traceback.format_exc())
            _failed_ids.add(page_id)
        finally:
            if local_path:
                try:
                    os.remove(local_path)
                except OSError:
                    log.warning("Could not delete temp file: %s", local_path)


def main() -> None:
    log.info("enrich_tracks v2 starting — DRY_RUN=%s, interval=%ds", DRY_RUN, POLL_INTERVAL)
    token = _get_dropbox_access_token()
    if token:
        log.info("Dropbox token OK")
    else:
        log.warning("Dropbox token FAILED — renames will be skipped")
    while True:
        poll_cycle()
        log.info("Sleeping %ds...", POLL_INTERVAL)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
