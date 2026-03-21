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
