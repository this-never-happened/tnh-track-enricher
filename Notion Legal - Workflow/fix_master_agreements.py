#!/usr/bin/env python3
"""
One-shot script: updates all active main agreement Notion titles to add the
TNH-MASTER-NNN prefix, then renames matching Drive files to match.

Canonical format: TNH-MASTER-{id} - {existing title}

Run (audit):  railway run --service 092c1675-7de9-4eb5-97db-4f8ee485b525 python3 fix_master_agreements.py
Run (fix):    railway run --service 092c1675-7de9-4eb5-97db-4f8ee485b525 python3 fix_master_agreements.py --fix
"""

import os, re, time, json, base64, sys, requests
from datetime import datetime

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

NOTION_TOKEN       = os.environ["NOTION_TOKEN"]
NOTION_VERSION     = "2022-06-28"
MASTER_AGREEMENTS_DB = "222e7b468ee780369ca6e6a80a04c2d9"
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
    records = []
    payload = {"page_size": 100}
    while True:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{MASTER_AGREEMENTS_DB}/query",
            headers=HEADERS, json=payload,
        )
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            if page.get("archived"):
                continue
            props = page["properties"]

            title_prop_name = None
            current_title = ""
            for k, v in props.items():
                if v.get("type") == "title":
                    title_prop_name = k
                    items = v.get("title", [])
                    current_title = items[0]["plain_text"] if items else ""
                    break

            master_id_data = props.get("master id", {}).get("unique_id", {})
            master_num = master_id_data.get("number")
            url = props.get("agreement (url)", {}).get("url") or ""

            if not master_num or not current_title:
                continue

            records.append({
                "page_id": page["id"],
                "title_prop": title_prop_name,
                "current_title": current_title,
                "master_num": master_num,
                "url": url,
            })
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
        time.sleep(0.2)
    return records


def update_notion_title(page_id, title_prop, new_title):
    r = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS,
        json={"properties": {title_prop: {"title": [{"text": {"content": new_title}}]}}},
    )
    r.raise_for_status()


def main():
    mode = "AUDIT + FIX" if FIX_MODE else "AUDIT ONLY"
    print(f"Fixing main agreement titles and Drive filenames ({mode})...\n")

    drive = get_drive_service()
    records = get_all_active_records()
    print(f"Found {len(records)} active main agreements with title and master ID.\n")

    already_correct = 0
    to_fix = 0
    notion_updated = 0
    drive_renamed = 0
    drive_skipped = 0
    errors = 0

    for rec in records:
        prefix = f"TNH-MASTER-{rec['master_num']} - "
        if rec["current_title"].startswith(prefix):
            already_correct += 1
            continue

        to_fix += 1
        new_title = f"{prefix}{rec['current_title']}"

        if not FIX_MODE:
            print(f"  ⚠ Would rename:")
            print(f"     Notion: {rec['current_title'][:80]}")
            print(f"     →      {new_title[:80]}")
            if rec["url"]:
                file_id = extract_file_id(rec["url"])
                if file_id:
                    try:
                        current_drive = drive.files().get(
                            fileId=file_id, fields="name", supportsAllDrives=True
                        ).execute().get("name", "")
                        if current_drive != new_title:
                            print(f"     Drive: {current_drive[:80]}")
                    except Exception:
                        pass
            time.sleep(0.15)
            continue

        # Fix Notion title
        try:
            update_notion_title(rec["page_id"], rec["title_prop"], new_title)
            notion_updated += 1
        except Exception as e:
            print(f"  ❌ Notion update failed for {rec['current_title'][:60]}: {e}")
            errors += 1
            time.sleep(0.3)
            continue

        # Fix Drive filename
        if rec["url"]:
            file_id = extract_file_id(rec["url"])
            if file_id:
                try:
                    current_drive = drive.files().get(
                        fileId=file_id, fields="name", supportsAllDrives=True
                    ).execute().get("name", "")
                    if current_drive != new_title:
                        drive.files().update(
                            fileId=file_id,
                            body={"name": new_title},
                            supportsAllDrives=True,
                        ).execute()
                        print(f"  ✅ Fixed:")
                        print(f"     From: {current_drive[:80]}")
                        print(f"     To:   {new_title[:80]}")
                        drive_renamed += 1
                    else:
                        drive_skipped += 1
                except Exception as e:
                    print(f"  ❌ Drive rename failed for {new_title[:60]}: {e}")
                    errors += 1
            else:
                drive_skipped += 1
        else:
            drive_skipped += 1

        time.sleep(0.15)

    print(f"\n{'='*60}")
    print(f"Already correct:     {already_correct}")
    print(f"Needed fixing:       {to_fix}")
    if FIX_MODE:
        print(f"Notion updated:      {notion_updated}")
        print(f"Drive renamed:       {drive_renamed}")
        print(f"Drive skipped/no URL:{drive_skipped}")
        print(f"Errors:              {errors}")
    else:
        print(f"\nRe-run with --fix to apply all changes.")


if __name__ == "__main__":
    main()
