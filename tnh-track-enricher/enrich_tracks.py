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

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
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
