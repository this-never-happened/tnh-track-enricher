#!/usr/bin/env python3
"""
One-shot script: renames Google Drive files to match the correct (original)
TNH-SIDE-NNN contract ID for all records that had duplicates archived.

Run with: railway run python fix_drive_names.py
"""

import os, re, time, json, base64, requests
from collections import defaultdict
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

NOTION_TOKEN   = os.environ["NOTION_TOKEN"]
NOTION_VERSION = "2022-06-28"
SIDE_AGREEMENTS_DB = "222e7b468ee7801398aed4f33fd5c78e"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

# Drive URLs that had duplicates — we need to rename these back to the correct ID
AFFECTED_URLS = [
    "https://drive.google.com/open?id=10dBvNfYTXPrU-K6lGfF5VFNwDC3DC0kT&usp=drive_fs",
    "https://drive.google.com/open?id=15UgP16Qj_k8SUT6TWZNSrN-od9kTe5sM&usp=drive_fs",
    "https://drive.google.com/open?id=161VyCzjI7LQDkthVVQO55IGTXNjUs9Dv&usp=drive_fs",
    "https://drive.google.com/open?id=17GpBOBOVSOCTKvJY9Ch2O5LTpNwPHwps&usp=drive_fs",
    "https://drive.google.com/open?id=1BOt5Dn_1pxR2e3FFHec_3XXN5KEdOkBD&usp=drive_fs",
    "https://drive.google.com/open?id=1Bd8fleUSeF0TZQREiCH9OhuhUPrkB8RZ&usp=drive_fs",
    "https://drive.google.com/open?id=1DZNupMgzFwu1828RRXi4Mzdne2xfzO7_&usp=drive_fs",
    "https://drive.google.com/open?id=1E6Tqfu7U0jFZmtvhYDEyO8ao5fRQbBT2&usp=drive_fs",
    "https://drive.google.com/open?id=1Gz8nEGClNTO_-LllwiFk3EDDkB-G7N7R&usp=drive_fs",
    "https://drive.google.com/open?id=1JRlbOCmJwdO_jqGIdAwNeEp02ll97m_J&usp=drive_fs",
    "https://drive.google.com/open?id=1KdXCPu_50ll1OAHHIRYWalXvkuw_bh9a&usp=drive_fs",
    "https://drive.google.com/open?id=1N9WzIUVmO5LMAmlacpF5n5wdMWP4Yno1&usp=drive_fs",
    "https://drive.google.com/open?id=1Q5e_9F1U6SKvCuOvzxPlRovdoY5lTOmS&usp=drive_fs",
    "https://drive.google.com/open?id=1VshclPfwjtJQJ-hvFLnhlRQKK95LdWIo&usp=drive_fs",
    "https://drive.google.com/open?id=1bBq-XliOxdf-L8ZFgIAMl-lQDS-CoLFj&usp=drive_fs",
    "https://drive.google.com/open?id=1dsTax_BLAj3k0VbkAXIjbDYG4EeckrOy&usp=drive_fs",
    "https://drive.google.com/open?id=1e_VxdXQM_rOwO2_wKoX0DQ7SS9ypMmn3&usp=drive_fs",
    "https://drive.google.com/open?id=1ikNwfih2SJABUva9oLQAZBZSazMZZfwf&usp=drive_fs",
    "https://drive.google.com/open?id=1mKZJJI-wC946PQrnMS27qRXod9TFOL7u&usp=drive_fs",
    "https://drive.google.com/open?id=1sQhZHtyvSW2mLKkA4yWiAlbyX5S7LoAz&usp=drive_fs",
    "https://drive.google.com/open?id=1t8DCjh25WTqmZjR7AHuW5Tt1XS9khuHO&usp=drive_fs",
    "https://drive.google.com/open?id=1tAgylJOl4ekIyvzZcQK_lGHk_kWQZwsl&usp=drive_fs",
    "https://drive.google.com/open?id=1yKSBSAmhLkOTQImWw_-kQ61-LLlQ5bm2&usp=drive_fs",
]

def get_drive_service():
    token_b64 = os.environ.get("SHEETS_TOKEN")
    if not token_b64:
        raise RuntimeError("SHEETS_TOKEN not set")
    token_data = json.loads(base64.b64decode(token_b64).decode())
    expiry = None
    if token_data.get("expiry"):
        expiry = datetime.fromisoformat(token_data["expiry"].replace("Z", "+00:00"))
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes"),
        expiry=expiry,
    )
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError("Google credentials invalid")
    return build("drive", "v3", credentials=creds)

def extract_file_id(url):
    match = re.search(r"[?&]id=([a-zA-Z0-9_-]{10,})", url)
    if match: return match.group(1)
    match = re.search(r"/d/([a-zA-Z0-9_-]{10,})", url)
    if match: return match.group(1)
    return None

def get_active_record_for_url(url):
    """Get the non-archived side agreement record for this Drive URL."""
    payload = {
        "filter": {
            "property": "signed agreement",
            "url": {"equals": url}
        }
    }
    r = requests.post(
        f"https://api.notion.com/v1/databases/{SIDE_AGREEMENTS_DB}/query",
        headers=HEADERS, json=payload
    )
    r.raise_for_status()
    results = [p for p in r.json().get("results", []) if not p.get("archived")]
    if not results:
        return None
    # Return the one with the lowest side agreement ID (the original)
    results.sort(key=lambda p: p["properties"].get("side agreement id", {}).get("unique_id", {}).get("number", 9999))
    p = results[0]
    title_items = p["properties"].get("agreement", {}).get("title", [])
    return title_items[0]["plain_text"] if title_items else None

def main():
    print("Fixing Drive filenames to match correct TNH-SIDE-NNN IDs...\n")
    drive = get_drive_service()

    renamed = 0
    already_correct = 0
    errors = 0

    for url in AFFECTED_URLS:
        file_id = extract_file_id(url)
        if not file_id:
            print(f"  ⚠ Could not extract file ID from {url}")
            continue

        correct_name = get_active_record_for_url(url)
        time.sleep(0.35)
        if not correct_name:
            print(f"  ⚠ No active Notion record found for {url[:60]}")
            continue

        try:
            current = drive.files().get(fileId=file_id, fields="name").execute().get("name", "")
            if current == correct_name:
                print(f"  ✅ Already correct: {correct_name[:80]}")
                already_correct += 1
            else:
                drive.files().update(fileId=file_id, body={"name": correct_name}).execute()
                print(f"  ✅ Renamed:")
                print(f"     From: {current[:80]}")
                print(f"     To:   {correct_name[:80]}")
                renamed += 1
        except Exception as e:
            print(f"  ❌ Error for {correct_name[:60]}: {e}")
            errors += 1

    print(f"\nDone. Renamed: {renamed} | Already correct: {already_correct} | Errors: {errors}")

if __name__ == "__main__":
    main()
