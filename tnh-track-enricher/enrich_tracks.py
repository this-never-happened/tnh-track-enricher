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

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── State ─────────────────────────────────────────────────────────────────────

_failed_ids: set[str] = set()

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
    track_slug = _slugify(track_title)

    if version:
        version_slug = version[0].replace(" ", "-")
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


def rename_dropbox_file(share_url: str, new_filename: str) -> bool:
    """Rename the Dropbox file to new_filename in the same directory. Returns True on success."""
    log.info("Dropbox rename: starting for %s", new_filename)
    try:
        access_token = _get_dropbox_access_token()
    except Exception:
        log.warning("Dropbox token fetch exception:\n%s", traceback.format_exc())
        return False
    if not access_token:
        log.warning("Dropbox rename skipped — no access token")
        return False

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
            return False

        meta = r.json()
        current_path = meta.get("path_display") or meta.get("path_lower")

        # Team accounts often omit path from shared link metadata — fetch via file ID
        if not current_path:
            file_id = meta.get("id")
            if not file_id:
                log.warning("Dropbox: no path or id in metadata response: %s", meta)
                return False
            # File IDs are namespace-independent; Path-Root AND Select-User cause not_found
            log.info("Dropbox: looking up file ID %s", file_id)
            headers_bare = {
                "Authorization": headers["Authorization"],
                "Content-Type": "application/json",
            }
            r_meta = requests.post(
                "https://api.dropboxapi.com/2/files/get_metadata",
                headers=headers_bare,
                json={"path": file_id},
                timeout=30,
            )
            if r_meta.status_code != 200:
                log.warning("Dropbox file metadata fetch failed: %s", r_meta.text[:300])
                return False
            file_meta = r_meta.json()
            current_path = file_meta.get("path_display") or file_meta.get("path_lower")
            if not current_path:
                log.warning("Dropbox: no path in file metadata: %s", file_meta)
                return False

        parent = current_path.rsplit("/", 1)[0]
        new_path = f"{parent}/{new_filename}"

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
            return True
        log.warning("Dropbox move failed: %s", r2.text[:300])
        return False
    except Exception:
        log.warning("Dropbox rename exception:\n%s", traceback.format_exc())
        return False


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
        if filename_matches(original_filename, track["isrc"]):
            log.info("Filename OK — no rename needed: %s", original_filename)
        elif DRY_RUN:
            log.info("[DRY RUN] Would rename: %s -> %s", original_filename, proposed)
        else:
            log.info("CURRENT:  %s", original_filename)
            log.info("PROPOSED: %s", proposed)
            rename_dropbox_file(track["master"], proposed)

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
