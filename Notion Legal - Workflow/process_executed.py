#!/usr/bin/env python3
"""
TNH Executed Agreement Processor
Polls Notion Contract Drafting database every 60 seconds.

Trigger: status == "fully executed" AND "executed agreement" URL is populated
         AND no existing "✅ Processed" comment on the record

Routing:
  licence / exclusive license  → creates Master Contract record
  everything else              → creates Side Agreement record

After creating the downstream record:
  - Renames the Google Drive file to the uniform naming convention
  - Posts a Notion comment on the Drafting record with the new record URL

Naming conventions:
  Master:  TNH-MASTER-{id} - {main_artist} - {agreement_type}
  Side:    TNH-SIDE-{id} - {royaltor} - {track_name} ({track_id}) - {agreement_type} - TNH-MASTER-{master_id}
"""

import os
import re
import time
import json
import pickle
import base64
import requests
from datetime import datetime

from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── CONFIG ────────────────────────────────────────────────────────────────────

NOTION_TOKEN   = os.environ["NOTION_TOKEN"]
NOTION_VERSION = "2022-06-28"

CONTRACT_DRAFTING_DB = "30be7b468ee780e9a4add3ede0f9808d"
MASTER_CONTRACTS_DB  = "222e7b468ee780369ca6e6a80a04c2d9"
SIDE_AGREEMENTS_DB   = "222e7b468ee7801398aed4f33fd5c78e"

POLL_INTERVAL  = 60  # seconds
RATE_LIMIT     = 0.35

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Agreement types that go to Master Contracts
MASTER_TYPES = {"licence", "exclusive license"}

# ── GOOGLE AUTH ───────────────────────────────────────────────────────────────

def get_drive_service():
    """Load credentials from LEGAL_TOKEN env var (base64-encoded pickle)."""
    token_b64 = os.environ.get("LEGAL_TOKEN")
    if not token_b64:
        raise RuntimeError("LEGAL_TOKEN environment variable not set")
    creds = pickle.loads(base64.b64decode(token_b64))
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError("Google credentials are invalid and cannot be refreshed")
    return build("drive", "v3", credentials=creds)

# ── NOTION HELPERS ────────────────────────────────────────────────────────────

def notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

def notion_get_page(page_id):
    r = requests.get(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=notion_headers()
    )
    r.raise_for_status()
    time.sleep(RATE_LIMIT)
    return r.json()

def notion_create_page(parent_db_id, properties):
    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=notion_headers(),
        json={"parent": {"database_id": parent_db_id}, "properties": properties}
    )
    r.raise_for_status()
    time.sleep(RATE_LIMIT)
    return r.json()

def notion_update_page(page_id, properties):
    r = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=notion_headers(),
        json={"properties": properties}
    )
    r.raise_for_status()
    time.sleep(RATE_LIMIT)
    return r.json()

def notion_post_comment(page_id, text):
    r = requests.post(
        "https://api.notion.com/v1/comments",
        headers=notion_headers(),
        json={
            "parent": {"page_id": page_id},
            "rich_text": [{"text": {"content": text}}]
        }
    )
    r.raise_for_status()
    time.sleep(RATE_LIMIT)

def notion_get_comments(page_id):
    r = requests.get(
        f"https://api.notion.com/v1/comments?block_id={page_id}",
        headers=notion_headers()
    )
    r.raise_for_status()
    time.sleep(RATE_LIMIT)
    return r.json().get("results", [])

class CommentCheckFailed(Exception):
    pass

def already_processed(page_id):
    """Check if a '✅ Processed' comment already exists — prevents reprocessing after restarts."""
    try:
        comments = notion_get_comments(page_id)
        for comment in comments:
            for block in comment.get("rich_text", []):
                if "✅ Processed" in block.get("text", {}).get("content", ""):
                    return True
        return False
    except Exception as e:
        raise CommentCheckFailed(f"Could not check comments: {e}") from e

def get_executed_records():
    """Query Drafting DB for fully executed records with an executed agreement URL."""
    url = f"https://api.notion.com/v1/databases/{CONTRACT_DRAFTING_DB}/query"
    payload = {
        "filter": {
            "and": [
                {"property": "status", "status": {"equals": "fully executed"}},
                {"property": "executed agreement", "url": {"is_not_empty": True}},
            ]
        }
    }
    r = requests.post(url, headers=notion_headers(), json=payload)
    r.raise_for_status()
    time.sleep(RATE_LIMIT)
    return r.json().get("results", [])

# ── DATA EXTRACTION ───────────────────────────────────────────────────────────

def get_prop_text(props, key):
    """Extract plain text from title or rich_text property."""
    prop = props.get(key, {})
    for field in ("title", "rich_text"):
        items = prop.get(field, [])
        if items:
            return "".join(i.get("plain_text", "") for i in items).strip()
    return ""

def get_prop_select(props, key):
    s = props.get(key, {}).get("select")
    return s["name"] if s else ""

def get_prop_number(props, key):
    return props.get(key, {}).get("number")

def get_prop_url(props, key):
    return props.get(key, {}).get("url", "")

def get_prop_relation(props, key):
    return [r["id"] for r in props.get(key, {}).get("relation", [])]

def get_prop_rollup_text(props, key):
    """Extract text values from a rollup property."""
    rollup = props.get(key, {}).get("rollup", {})
    arr = rollup.get("array", [])
    texts = []
    for item in arr:
        t = item.get("type")
        if t == "rich_text":
            for rt in item.get("rich_text", []):
                v = rt.get("plain_text", "")
                if v:
                    texts.append(v)
        elif t == "title":
            for rt in item.get("title", []):
                v = rt.get("plain_text", "")
                if v:
                    texts.append(v)
        elif t == "unique_id":
            uid = item.get("unique_id", {})
            prefix = uid.get("prefix", "")
            number = uid.get("number", "")
            if number:
                texts.append(f"{prefix}-{number}" if prefix else str(number))
    return ", ".join(filter(None, texts))

def get_page_title(page_id):
    """Fetch the title of any Notion page by ID."""
    try:
        page = notion_get_page(page_id)
        props = page.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                items = prop.get("title", [])
                return items[0]["plain_text"] if items else ""
    except Exception:
        pass
    return ""

def get_unique_id_str(props, key, default_prefix="TNH"):
    """Extract auto_increment_id as formatted string e.g. TNH-MASTER-12."""
    uid = props.get(key, {}).get("unique_id", {})
    if uid.get("number"):
        prefix = uid.get("prefix", default_prefix)
        return f"{prefix}-{uid['number']}"
    return None

def extract_record_data(record):
    """Extract all relevant fields from a Drafting DB record."""
    props = record["properties"]

    # Draft ID
    draft_uid = props.get("draft id", {}).get("unique_id", {})
    if draft_uid.get("number"):
        draft_id = f"{draft_uid.get('prefix', 'TNH-DRAFT')}-{draft_uid['number']}"
    else:
        draft_id = f"TNH-DRAFT-{props.get('draft id', {}).get('number', '?')}"

    # Splits — stored as decimals (0.5 = 50%), multiply by 100 for display
    raw_master  = get_prop_number(props, "master split (%)")
    raw_pub     = get_prop_number(props, "publishing split (%)")
    master_split  = round(raw_master * 100, 4) if raw_master is not None else None
    publishing_split = round(raw_pub * 100, 4) if raw_pub is not None else None

    return {
        "page_id":            record["id"],
        "draft_id":           draft_id,
        "royaltor":           get_prop_text(props, "royaltor"),
        "agreement_type":     get_prop_select(props, "agreement type"),
        "executed_url":       get_prop_url(props, "executed agreement"),
        "master_split":       master_split,        # already multiplied × 100
        "publishing_split":   publishing_split,    # already multiplied × 100
        "raw_master_split":   raw_master,          # original decimal for Notion write
        "raw_publishing_split": raw_pub,           # original decimal for Notion write
        "track_ids":          get_prop_relation(props, "track(s)"),
        "artist_ids":         get_prop_relation(props, "artist"),
        "main_artist_ids":    get_prop_relation(props, "main artist"),
        "master_contract_ids": get_prop_relation(props, "master contract"),
        "project_ids":        get_prop_relation(props, "project"),
    }

# ── NAMING ────────────────────────────────────────────────────────────────────

def build_master_name(master_id_num, main_artist_name, agreement_type):
    """TNH-MASTER-{id} - {main_artist} - {agreement_type}"""
    return f"TNH-MASTER-{master_id_num} - {main_artist_name} - {agreement_type}"

def build_side_name(side_id_num, royaltor, track_names, track_ids, agreement_type, master_id_str):
    """TNH-SIDE-{id} - {royaltor} - {track_name} ({track_id}) - {agreement_type} - {master_id}"""
    # Build track segment: "Track Name (TNH-TRACK-1), Track Name 2 (TNH-TRACK-2)"
    track_parts = []
    for name, tid in zip(track_names, track_ids):
        # track_id here is the Notion page ID — we want the TNH-TRACK-### ID from the page
        track_parts.append(f"{name} ({tid})")
    track_segment = ", ".join(track_parts) if track_parts else "Unknown Track"

    return f"TNH-SIDE-{side_id_num} - {royaltor} - {track_segment} - {agreement_type} - {master_id_str}"

# ── DRIVE RENAME ──────────────────────────────────────────────────────────────

def extract_file_id_from_url(url):
    """Extract Google Drive file ID from a docs.google.com or drive.google.com URL."""
    # Handles: /d/{id}/, /file/d/{id}/, ?id={id}
    match = re.search(r"/d/([a-zA-Z0-9_-]{10,})", url)
    if match:
        return match.group(1)
    match = re.search(r"[?&]id=([a-zA-Z0-9_-]{10,})", url)
    if match:
        return match.group(1)
    return None

def rename_drive_file(drive_service, file_url, new_name):
    """Rename a Google Drive file by its URL."""
    file_id = extract_file_id_from_url(file_url)
    if not file_id:
        print(f"  ⚠ Could not extract file ID from URL: {file_url}")
        return False
    try:
        drive_service.files().update(
            fileId=file_id,
            body={"name": new_name}
        ).execute()
        print(f"  ✅ Drive file renamed to: {new_name}")
        return True
    except Exception as e:
        print(f"  ⚠ Drive rename failed: {e}")
        return False

# ── TRACK ID RESOLUTION ───────────────────────────────────────────────────────

def get_track_info(track_page_id):
    """
    Fetch track name and TNH-TRACK-### ID from the Tracks (Canonical) DB.
    Returns (track_name, track_id_str).
    """
    try:
        page = notion_get_page(track_page_id)
        props = page.get("properties", {})
        # Title field
        name = ""
        for prop in props.values():
            if prop.get("type") == "title":
                items = prop.get("title", [])
                name = items[0]["plain_text"] if items else ""
                break
        # TNH-TRACK-### auto_increment_id
        track_id_str = get_unique_id_str(props, "track id") or get_unique_id_str(props, "id") or ""
        return name, track_id_str
    except Exception as e:
        print(f"  ⚠ Could not fetch track {track_page_id}: {e}")
        return "", ""

def get_master_id_str(master_page_id):
    """Fetch TNH-MASTER-### string from a Master Contracts page."""
    try:
        page = notion_get_page(master_page_id)
        props = page.get("properties", {})
        uid = props.get("master id", {}).get("unique_id", {})
        if uid.get("number"):
            return f"TNH-MASTER-{uid['number']}", uid["number"]
    except Exception as e:
        print(f"  ⚠ Could not fetch master contract {master_page_id}: {e}")
    return "TNH-MASTER-?", None

# ── BRANCH A: MASTER CONTRACT ─────────────────────────────────────────────────

def create_master_contract(data, main_artist_name, drive_service):
    """Create a new Master Contract record for licence / exclusive license agreements."""
    print(f"  → Branch: Master Contract")

    agreement_type = data["agreement_type"]

    # We don't know the master_id yet — Notion auto-assigns it on creation.
    # Create first, then read back the ID to build the name, then rename.
    properties = {
        "master agreement": {
            "title": [{"text": {"content": f"PENDING - {main_artist_name} - {agreement_type}"}}]
        },
        "agreement type": {
            "status": {"name": agreement_type}
        },
        "main artist": {
            "relation": [{"id": aid} for aid in data["main_artist_ids"]]
        },
        "projects": {
            "relation": [{"id": pid} for pid in data["project_ids"]]
        },
        "agreement (url)": {
            "url": data["executed_url"]
        },
        "signature status": {
            "status": {"name": "fully executed"}
        },
    }

    # Add draft_id as a number for traceability
    draft_num = data["draft_id"].split("-")[-1]
    if draft_num.isdigit():
        properties["draft id"] = {"number": int(draft_num)}

    new_page = notion_create_page(MASTER_CONTRACTS_DB, properties)
    new_page_id = new_page["id"]
    new_page_url = new_page.get("url", f"https://notion.so/{new_page_id.replace('-', '')}")

    # Read back the auto-assigned master_id
    new_props = new_page.get("properties", {})
    uid = new_props.get("master id", {}).get("unique_id", {})
    master_id_num = uid.get("number")

    if master_id_num:
        final_name = build_master_name(master_id_num, main_artist_name, agreement_type)
        # Update the title now we have the ID
        notion_update_page(new_page_id, {
            "master agreement": {
                "title": [{"text": {"content": final_name}}]
            }
        })
        print(f"  ✅ Master Contract created: {final_name}")
    else:
        final_name = f"PENDING - {main_artist_name} - {agreement_type}"
        print(f"  ⚠ Could not read back master_id — title left as PENDING")

    # Rename Drive file
    rename_drive_file(drive_service, data["executed_url"], final_name)

    return new_page_id, new_page_url, final_name

# ── BRANCH B: SIDE AGREEMENT ──────────────────────────────────────────────────

def create_side_agreement(data, track_names, track_id_strs, master_id_str, drive_service):
    """Create a new Side Agreement record for all non-licence agreement types."""
    print(f"  → Branch: Side Agreement")

    agreement_type = data["agreement_type"]
    royaltor = data["royaltor"]

    # Build properties
    properties = {
        "agreement": {
            "title": [{"text": {"content": "PENDING"}}]  # Updated after we get side_id
        },
        "agreement type": {
            "select": {"name": agreement_type}
        },
        "artist": {
            "relation": [{"id": aid} for aid in data["artist_ids"]]
        },
        "track(s)": {
            "relation": [{"id": tid} for tid in data["track_ids"]]
        },
        "projects": {
            "relation": [{"id": pid} for pid in data["project_ids"]]
        },
        "signed agreement": {
            "url": data["executed_url"]
        },
        "signature status": {
            "status": {"name": "fully executed"}
        },
    }

    # Splits — write back as decimals (Notion stores as 0–1 for percent fields)
    # IMPORTANT: raw values preserved exactly as they came from the Drafting record
    if data["raw_master_split"] is not None:
        properties["master split (%)"] = {"number": data["raw_master_split"]}
    if data["raw_publishing_split"] is not None:
        properties["publishing split (%)"] = {"number": data["raw_publishing_split"]}

    # Link to master agreement if present
    if data["master_contract_ids"]:
        properties["master agreement"] = {
            "relation": [{"id": mid} for mid in data["master_contract_ids"]]
        }

    # Draft ID for traceability
    draft_num = data["draft_id"].split("-")[-1]
    if draft_num.isdigit():
        properties["draft id"] = {"number": int(draft_num)}

    new_page = notion_create_page(SIDE_AGREEMENTS_DB, properties)
    new_page_id = new_page["id"]
    new_page_url = new_page.get("url", f"https://notion.so/{new_page_id.replace('-', '')}")

    # Read back the auto-assigned side_agreement_id
    new_props = new_page.get("properties", {})
    uid = new_props.get("side agreement id", {}).get("unique_id", {})
    side_id_num = uid.get("number")

    if side_id_num:
        final_name = build_side_name(
            side_id_num, royaltor, track_names, track_id_strs,
            agreement_type, master_id_str
        )
        notion_update_page(new_page_id, {
            "agreement": {
                "title": [{"text": {"content": final_name}}]
            }
        })
        print(f"  ✅ Side Agreement created: {final_name}")
    else:
        final_name = f"PENDING - {royaltor} - {agreement_type}"
        print(f"  ⚠ Could not read back side_agreement_id — title left as PENDING")

    # Rename Drive file
    rename_drive_file(drive_service, data["executed_url"], final_name)

    # Log splits for confirmation
    print(f"  ✅ Splits carried over — Master: {data['master_split']}% | Publishing: {data['publishing_split']}%")

    return new_page_id, new_page_url, final_name

# ── MAIN PROCESSOR ────────────────────────────────────────────────────────────

def process_record(record, drive_service):
    data = extract_record_data(record)

    print(f"\n→ {data['draft_id']} | {data['royaltor']} | {data['agreement_type']}")
    print(f"  Executed URL: {data['executed_url']}")
    print(f"  Splits — Master: {data['master_split']}% | Publishing: {data['publishing_split']}%")

    # Duplicate guard — check for existing processed comment
    try:
        if already_processed(data["page_id"]):
            print(f"  ⏭ Already processed — skipping")
            return
    except CommentCheckFailed as e:
        print(f"  ⚠ {e} — skipping to avoid duplicate")
        return

    agreement_type_lower = data["agreement_type"].lower().strip()

    # Resolve track names and TNH-TRACK IDs
    track_names = []
    track_id_strs = []
    for tid in data["track_ids"]:
        name, id_str = get_track_info(tid)
        track_names.append(name or "Unknown Track")
        track_id_strs.append(id_str or tid[:8])  # fallback to partial page ID

    # Resolve main artist name
    main_artist_name = ""
    if data["main_artist_ids"]:
        main_artist_name = get_page_title(data["main_artist_ids"][0])
    if not main_artist_name and data["artist_ids"]:
        main_artist_name = get_page_title(data["artist_ids"][0])
    if not main_artist_name:
        main_artist_name = "[Artist TBC]"

    # Resolve master contract ID string (for side agreement naming)
    master_id_str = "TNH-MASTER-?"
    if data["master_contract_ids"]:
        master_id_str, _ = get_master_id_str(data["master_contract_ids"][0])

    # Route based on agreement type
    if agreement_type_lower in MASTER_TYPES:
        new_page_id, new_page_url, final_name = create_master_contract(
            data, main_artist_name, drive_service
        )
    else:
        new_page_id, new_page_url, final_name = create_side_agreement(
            data, track_names, track_id_strs, master_id_str, drive_service
        )

    # Post audit comment on the Drafting record
    comment_text = (
        f"✅ Processed on {datetime.now().strftime('%d %B %Y at %H:%M')} | "
        f"{final_name} | {new_page_url}"
    )
    notion_post_comment(data["page_id"], comment_text)
    print(f"  ✅ Audit comment posted to Drafting record")

# ── ENTRY POINT ───────────────────────────────────────────────────────────────

def main():
    print("TNH Executed Agreement Processor starting...")
    print(f"Polling every {POLL_INTERVAL}s for status = 'fully executed' with executed agreement URL\n")

    # Initialise Drive service once
    try:
        drive_service = get_drive_service()
        print("✅ Google Drive auth successful\n")
    except Exception as e:
        print(f"❌ Google auth failed: {e}")
        print("Running without Drive rename capability — Notion records will still be created\n")
        drive_service = None

    while True:
        try:
            records = get_executed_records()
            if records:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Found {len(records)} fully executed record(s)")
                for record in records:
                    try:
                        process_record(record, drive_service)
                    except Exception as e:
                        page_id = record.get("id", "unknown")
                        print(f"  ❌ Error processing {page_id}: {e}")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] No executed records pending")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Poll error: {e}")

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
