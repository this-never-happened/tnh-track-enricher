# Codebase Structure

**Analysis Date:** 2026-03-16

## Directory Layout

```
/Users/pete/
├── tnh-invoice-portal/       # Main Flask service: invoice submission & allocation
│   ├── app.py                # 1170 lines: Flask routes, webhooks, polling, Notion/Dropbox logic
│   ├── vendor_onboarding.py  # Vendor setup form handler
│   ├── Procfile              # Railway process definition
│   ├── requirements.txt       # Python dependencies (Flask, requests, Google libraries)
│   └── .git/                 # Git repository
│
├── tnh-label-costs/          # Worker: sync Notion costs to Google Sheets
│   ├── sync_label_costs.py   # 924 lines: Notion query → cost classification → Sheets write
│   ├── Procfile              # Railway worker process
│   ├── requirements.txt       # Dependencies (requests, googleapiclient, oauth2)
│   └── .git/                 # Git repository
│
├── tnh-cloud-function/       # Serverless: artist/product onboarding
│   ├── main.py               # 739 lines: Cognito Forms → Notion artist/product creation
│   ├── requirements.txt       # Google Cloud Functions dependencies
│   └── (no git)              # Separate deployment
│
└── (Root level Python scripts)  # One-off utility scripts
    ├── app.py                # 28KB multi-purpose script
    ├── sync_notion_royalty_status.py
    ├── youtube_mix_analysis.py
    ├── batch_recovery_analysis.py
    └── ... (15+ utility scripts)
```

## Directory Purposes

**`/Users/pete/tnh-invoice-portal/`:**
- Purpose: Primary production service for invoice workflows
- Contains: Flask HTTP server, invoice/vendor CRUD, Dropbox integration, background polling
- Key files: `app.py` (main logic), `vendor_onboarding.py` (onboarding workflow)
- Deployed on: Railway as persistent service (Procfile specifies `python app.py`)

**`/Users/pete/tnh-label-costs/`:**
- Purpose: Scheduled worker for accounting cost sync
- Contains: Notion database reader, cost classifier, Google Sheets writer
- Key files: `sync_label_costs.py` (all logic)
- Deployed on: Railway worker on hourly schedule (via Procfile)

**`/Users/pete/tnh-cloud-function/`:**
- Purpose: Standalone serverless endpoint for form submissions not handled by invoice portal
- Contains: Cognito Forms payload parsing, Notion artist/product creation
- Key files: `main.py` (all logic)
- Deployed on: Google Cloud Functions (not Railway)

**Root level (`/Users/pete/`):**
- Purpose: Ad-hoc analysis and utility scripts
- Contains: One-off scripts for YouTube analytics, cost recovery, data analysis
- Character: Utility/exploration code not part of core production workflow
- Not deployed or scheduled as services

## Key File Locations

**Entry Points:**
- `/Users/pete/tnh-invoice-portal/app.py`: Line 814+ contains Flask route handlers (submit_invoice, allocate_invoice, rename_release_cost, etc.)
- `/Users/pete/tnh-invoice-portal/vendor_onboarding.py`: Line 25-33 Flask app setup and webhook handlers
- `/Users/pete/tnh-cloud-function/main.py`: Line 200+ contains webhook handler (function entry_point)
- `/Users/pete/tnh-label-costs/sync_label_costs.py`: Line 400+ contains main() function execution

**Configuration:**
- `/Users/pete/tnh-invoice-portal/app.py` lines 26-52: Notion token, database IDs, Dropbox credentials, cost centre mapping
- `/Users/pete/tnh-label-costs/sync_label_costs.py` lines 20-35: Notion token, database ID, sheet ID, rate limit settings
- `/Users/pete/tnh-cloud-function/main.py` lines 22-46: Notion database IDs, Gmail sender, test mode flag
- Environment variables: NOTION_TOKEN, DROPBOX_REFRESH_TOKEN, SHEETS_TOKEN, GMAIL_CREDENTIALS (not committed)

**Core Logic:**
- Invoice submission: `tnh-invoice-portal/app.py` lines 814-974
- Invoice allocation polling: `tnh-invoice-portal/app.py` lines 670-768
- Release cost rename: `tnh-invoice-portal/app.py` lines 537-668
- Cost classification: `tnh-label-costs/sync_label_costs.py` lines 70-82
- Sheet writing: `tnh-label-costs/sync_label_costs.py` lines 279-400
- Artist creation: `tnh-cloud-function/main.py` lines 97-140
- Product creation: `tnh-cloud-function/main.py` lines 142-180

**Testing:**
- No dedicated test directory or files found
- `test_notion.py` in root is a minimal test stub (393 lines, appears unfinished)

**Helper/Utility Functions:**
- Notion API: `tnh-invoice-portal/app.py` lines 55-83 (notion_request wrapper)
- Notion API: `tnh-label-costs/sync_label_costs.py` lines 87-105 (notion_get, notion_post)
- Dropbox operations: `tnh-invoice-portal/app.py` lines 172-330 (upload, move, create folder, list folder, shared links)
- Vendor lookup: `tnh-invoice-portal/app.py` lines 86-121 (find_vendor_by_email, create_vendor, find_or_create_vendor)
- Invoice details: `tnh-invoice-portal/app.py` lines 464-490 (get_invoice_details)
- Cost centre creation: `tnh-invoice-portal/app.py` lines 364-461 (create_cost_centre_record with per-centre property mapping)

## Naming Conventions

**Files:**
- Services: `app.py` (main Flask), function-specific script files (`sync_label_costs.py`, `vendor_onboarding.py`, `main.py`)
- Utilities: Descriptive snake_case (e.g., `batch_recovery_analysis.py`, `youtube_mix_deep_analysis.py`)
- Config: `requirements.txt` (dependencies), `Procfile` (Railway process definition), `.env` (secrets, not committed)

**Directories:**
- Project repos: `tnh-` prefix + descriptor (`tnh-invoice-portal`, `tnh-label-costs`, `tnh-cloud-function`)
- No subdirectories for code organization within projects (monolithic single/dual-file structure)

**Functions:**
- Descriptive snake_case: `find_vendor_by_email()`, `create_invoice_record()`, `get_dropbox_access_token()`, `poll_invoices()`
- Prefixed helper groups: `notion_request()`, `notion_get()`, `notion_post()` (Notion API wrappers)
- Webhook handlers: Named by action (`submit_invoice()`, `rename_release_cost()`)
- Poll handlers: `poll_*` prefix (`poll_invoices()`, `poll_release_costs()`)

**Variables:**
- Notion/Dropbox IDs: All caps with `_DB` or `_ID` suffix (e.g., `INVOICES_DB`, `DROPBOX_APP_KEY`)
- Environment variables: Upper-case (e.g., `NOTION_TOKEN`, `DRY_RUN`)
- Local data dicts: snake_case (e.g., `invoice_data`, `vendor_cache`, `base_properties`)
- Prefixed log messages: `[MODULE]` format (e.g., `[WEBHOOK]`, `[NOTION]`, `[DROPBOX]`, `[COST]`)

**Database/Property Names:**
- Database constant naming: COST_CENTRE_DBS (dict), VENDORS_DB (string ID)
- Notion property access: Via 'property' key with spaces preserved (e.g., `'invoice id'`, `'vendor name'`)
- Property type patterns: `{'title': [...]}`, `{'select': {...}}`, `{'relation': [...]}`

## Where to Add New Code

**New Invoice-Related Feature:**
- Primary code: `tnh-invoice-portal/app.py` (add helper function + webhook route)
- Tests: Create dedicated file `tnh-invoice-portal/test_<feature>.py` (currently missing)
- Configuration: Add database ID or mapping to app.py lines 26-52

**New Worker/Scheduled Task:**
- Implementation: New file in appropriate repo directory or root (e.g., `sync_<entity>.py`)
- Configuration: Add to Procfile and `requirements.txt`
- Deployment: Commit to git, Railway picks up Procfile

**New Notion Integration:**
- Add database ID constant to app.py or corresponding worker
- Follow existing pattern: `notion_request()` wrapper for API calls
- Handle rate limiting with `time.sleep(RATE_LIMIT_SLEEP)`

**New Dropbox Operation:**
- Add function to `tnh-invoice-portal/app.py` following existing patterns
- Use existing `get_dropbox_access_token()` and auth headers structure
- Handle 200/409 conflicts explicitly

**New Webhook Endpoint:**
- Add `@app.route()` decorated function in `tnh-invoice-portal/app.py`
- Parse request.get_json(), validate required fields, return 400 on missing data
- Follow logging pattern with `[PREFIX]` log lines for debugging
- Return jsonify({'success': True, ...}) or jsonify({'error': '...'}) with 200/400/500 status

**Utilities/Analysis Scripts:**
- Place in root directory `/Users/pete/` as standalone `.py` scripts
- Use existing imports pattern: requests, json, os, datetime
- Include docstring at top with purpose
- No tests or deployment configuration needed

## Special Directories

**`.git/` directories:**
- Purpose: Git version control
- Generated: Yes (one per project repo)
- Committed: No (git internal)

**`.planning/` directory:**
- Purpose: GSD planning documents (ARCHITECTURE.md, STRUCTURE.md, etc.)
- Generated: By gsd:map-codebase command
- Committed: Yes (to git)

**Root `.env` files:**
- Purpose: Environment variables (secrets)
- Generated: Manually created per deployment (Railway/Cloud Functions)
- Committed: No (must add to .gitignore)
- Contains: NOTION_TOKEN, DROPBOX_REFRESH_TOKEN, SHEETS_TOKEN, GMAIL_CREDENTIALS

---

*Structure analysis: 2026-03-16*
