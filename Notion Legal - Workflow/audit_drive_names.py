#!/usr/bin/env python3
"""
Audit script: checks every active side agreement with a Drive URL and reports
any whose Drive filename doesn't match the Notion agreement title.

Optionally fixes mismatches with --fix flag.

Run with: railway run --service 092c1675-7de9-4eb5-97db-4f8ee485b525 python3 audit_drive_names.py
Run with fixes: railway run --service 092c1675-7de9-4eb5-97db-4f8ee485b525 python3 audit_drive_names.py --fix
"""

import os, re, time, json, base64, sys, requests
from datetime import datetime

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

NOTION_TOKEN       = os.environ["NOTION_TOKEN"]
NOTION_VERSION     = "2022-06-28"
SIDE_AGREEMENTS_DB = "222e7b468ee7801398aed4f33fd5c78e"
FIX_MODE           = "--fix" in sys.argv

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}


def get_drive_service():
    token_b64 = os.environ.get("SHEETS_TOKEN")
    if not token_b64:
        raise RuntimeError("SHEETS_TOKEN not set")
    token_data = json.loads(base64.b64decode(token_b64).decode())
    expiry = None
    if token_data.get("expiry"):
        expiry = datetime.fromisoformat(token_data["expiry"].replace("Z", "+00:00")).replace(tzinfo=None)
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
    if match:
        return match.group(1)
    match = re.search(r"/d/([a-zA-Z0-9_-]{10,})", url)
    if match:
        return match.group(1)
    return None


def get_all_active_records():
    """Paginate through all active side agreements that have a signed agreement URL."""
    records = []
    payload = {
        "filter": {
            "property": "signed agreement",
            "url": {"is_not_empty": True},
        },
        "page_size": 100,
    }
    while True:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{SIDE_AGREEMENTS_DB}/query",
            headers=HEADERS, json=payload,
        )
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            if page.get("archived"):
                continue
            url_prop = page["properties"].get("signed agreement", {}).get("url") or ""
            title_items = page["properties"].get("agreement", {}).get("title", [])
            notion_name = title_items[0]["plain_text"] if title_items else ""
            if url_prop and notion_name:
                records.append({"url": url_prop, "notion_name": notion_name})
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
        time.sleep(0.2)
    return records


def main():
    mode = "AUDIT + FIX" if FIX_MODE else "AUDIT ONLY"
    print(f"Auditing Drive filenames against Notion titles ({mode})...\n")
    drive = get_drive_service()

    records = get_all_active_records()
    print(f"Found {len(records)} active side agreements with Drive URLs.\n")

    mismatches = []
    skipped = 0
    errors = 0
    fixed = 0

    for rec in records:
        file_id = extract_file_id(rec["url"])
        if not file_id:
            skipped += 1
            continue

        try:
            current = drive.files().get(
                fileId=file_id, fields="name", supportsAllDrives=True
            ).execute().get("name", "")
        except Exception as e:
            print(f"  ❌ Drive error for {rec['notion_name'][:60]}: {e}")
            errors += 1
            time.sleep(0.3)
            continue

        if current != rec["notion_name"]:
            mismatches.append({
                "file_id": file_id,
                "current": current,
                "expected": rec["notion_name"],
            })
            if FIX_MODE:
                try:
                    drive.files().update(
                        fileId=file_id,
                        body={"name": rec["notion_name"]},
                        supportsAllDrives=True,
                    ).execute()
                    print(f"  ✅ Fixed:")
                    print(f"     From: {current[:80]}")
                    print(f"     To:   {rec['notion_name'][:80]}")
                    fixed += 1
                except Exception as e:
                    print(f"  ❌ Fix failed for {rec['notion_name'][:60]}: {e}")
                    errors += 1
            else:
                print(f"  ⚠ Mismatch:")
                print(f"     Drive:  {current[:80]}")
                print(f"     Notion: {rec['notion_name'][:80]}")

        time.sleep(0.15)

    print(f"\n{'='*60}")
    print(f"Total checked:  {len(records) - skipped}")
    print(f"Mismatches:     {len(mismatches)}")
    print(f"Skipped (no ID):{skipped}")
    print(f"Drive errors:   {errors}")
    if FIX_MODE:
        print(f"Fixed:          {fixed}")
    else:
        print(f"\nRe-run with --fix to rename all mismatched files.")


if __name__ == "__main__":
    main()
