# Architecture

**Analysis Date:** 2026-03-16

## Pattern Overview

**Overall:** Webhook-driven event processing with async task handling

**Key Characteristics:**
- Event-driven architecture triggered by external form submissions and Notion database changes
- Distributed system with Railway-deployed Python Flask services
- Multiple specialized workers handling distinct workflow stages
- Asynchronous background polling for state reconciliation
- Heavy integration with Notion API for data persistence and Dropbox for file storage

## Layers

**Webhook & HTTP Layer:**
- Purpose: Receive and route incoming events from external services (Cognito Forms, Notion automations)
- Location: `app.py` in invoice portal, `vendor_onboarding.py` in invoice portal
- Contains: Flask route handlers (`@app.route` decorators), HTTP request validation, request parsing
- Depends on: External service payloads (Cognito Forms, Notion webhooks)
- Used by: External systems (Cognito Forms, Notion, Railway triggers)

**API Integration Layer:**
- Purpose: Abstract communication with external APIs (Notion, Dropbox, Gmail, Google Sheets)
- Location: Helper functions in `app.py` (notion_request, upload_to_dropbox, etc.), sync_label_costs.py
- Contains: HTTP clients, authentication token management, error handling and retries
- Depends on: Environment variables for credentials, external API specifications
- Used by: Business logic layer to communicate with Notion, Dropbox, Google services

**Business Logic Layer:**
- Purpose: Implement core workflows (invoice submission, vendor onboarding, cost allocation)
- Location: Functions like `submit_invoice()`, `process_release_cost_rename()`, `poll_invoices()` in app.py
- Contains: Workflow orchestration, data validation, decision logic, state transitions
- Depends on: API integration layer, database models
- Used by: Webhook layer (synchronous) and polling layer (asynchronous)

**Data Access Layer:**
- Purpose: Query and manipulate Notion databases, manage Dropbox file operations
- Location: Functions like `find_vendor_by_email()`, `create_invoice_record()`, `get_invoice_details()` in app.py
- Contains: CRUD operations for Notion pages, Dropbox file operations, relationship resolution
- Depends on: API integration layer
- Used by: Business logic layer

**Async Polling Layer:**
- Purpose: Periodically check for state changes and trigger consequent operations
- Location: `poll_invoices()` and `poll_release_costs()` functions, background thread in app.py
- Contains: Infinite loop with sleep intervals, polling logic, state reconciliation
- Depends on: Data access and business logic layers
- Used by: Runs in background thread spawned at application startup

**Standalone Worker Layer:**
- Purpose: Execute specialized long-running tasks independently deployed
- Location: `sync_label_costs.py`, `main.py` in tnh-cloud-function
- Contains: Complete script logic for syncing label costs to Google Sheets, processing artist/product data
- Depends on: Same API integration patterns (Notion, Google services)
- Used by: Railway worker scheduled tasks, Cloud Functions triggers

## Data Flow

**Invoice Submission Flow:**

1. Cognito Forms submission → `/submit-invoice` webhook endpoint
2. Parse form payload (royalties, general, or staff expense variant)
3. Vendor lookup/creation via Notion API
4. Create invoice record in Notion Invoices DB with auto-generated invoice ID
5. Download PDF from Cognito and upload to Dropbox with standardized naming
6. Update invoice record with Dropbox path and shared link
7. Return success response with invoice details

**Invoice Allocation Flow (Polling-Based):**

1. `poll_invoices()` runs every 5 minutes in background thread
2. Query Notion Invoices DB for reconciled invoices
3. For each reconciled invoice: extract cost centre, cost code, vendor
4. Create cost record in corresponding cost centre database (releases, label, events, royalties)
5. Move PDF in Dropbox from `/Invoices/` to cost-centre-specific folder
6. Update invoice record with final Dropbox path

**Release Cost Project Assignment Flow:**

1. User assigns project relation in Notion Release Costs record
2. Notion automation triggers `/rename-release-cost` webhook
3. Extract release cost details: invoice, project assignment, cost type
4. Find matching project folder in Dropbox `/Accounting/Invoices/Project Costs/`
5. Move PDF from cost centre folder to project folder with project-prefixed name
6. Update cost record with new Dropbox path

**Vendor Onboarding Flow:**

1. Cognito Forms vendor setup submission → separate Flask endpoint (vendor_onboarding.py)
2. Find or create vendor record in Notion Vendors DB
3. Download W8/W9 tax form PDF
4. Upload PDF to Dropbox `/Vendors/` folder
5. Update vendor record with Dropbox path
6. Send confirmation email to admin via Gmail

**Label Costs Sync Flow:**

1. `sync_label_costs.py` runs on hourly schedule (Railway worker)
2. Query Notion Label Costs database with pagination
3. Extract: cost ID, date, description, type, amount, vendor, invoice ID
4. Classify cost type into cost groups: Recoupable, Release, Overhead
5. Resolve vendor names via Notion (with caching)
6. Authenticate to Google Sheets via base64-encoded credentials token
7. Clear existing sheets and write 4 tabs: Recoupable, Release, Overhead, All Costs
8. Apply formatting, colors, and header styling via Sheets API batch update

**State Management:**

- **Notion Database as Primary Store:** All persistent state lives in Notion (invoices, vendors, costs, projects)
- **Dropbox as File Store:** PDFs and documents tracked via stored paths in Notion
- **Polling as Reconciliation:** Background polling ensures state transitions happen even if webhooks fail
- **Vendor Cache:** In-memory caching during sync operations (e.g., `sync_label_costs.py` uses vendor_cache dict)

## Key Abstractions

**Notion Database Record:**
- Purpose: Represents a persistent entity (Invoice, Vendor, Cost, Project)
- Examples: `app.py` functions query/create/update Notion pages
- Pattern: Query by property filter → parse response → extract specific fields → return as dict

**Dropbox File Operation:**
- Purpose: Upload, share, move, and organize PDFs
- Examples: `upload_to_dropbox()`, `move_dropbox_file()`, `get_or_create_dropbox_shared_link()`
- Pattern: Get access token → call Dropbox API with headers/auth → handle 200/409/error responses

**API Request with Retry:**
- Purpose: Resilient API communication with rate-limit and error handling
- Examples: `notion_request()` in app.py (max 3 retries, 10s sleep on 429)
- Pattern: Loop with exponential backoff, timeout handling, status code checking

**Notion Filter Query:**
- Purpose: Find records matching a condition (e.g., vendor by email)
- Examples: `find_vendor_by_email()` searches Vendors DB with email property filter
- Pattern: POST to `/databases/{id}/query` with filter → extract results[0]

**Cost Centre Mapper:**
- Purpose: Route invoices to correct cost centre DB based on type/status
- Examples: COST_CENTRE_DBS dict, event_category_map for event costs
- Pattern: Lookup table matches invoice property → returns database ID or mapped value

## Entry Points

**Invoice Portal Service (`/Users/pete/tnh-invoice-portal/app.py`):**
- Location: Flask application listening on Railway-assigned port (typically 5000)
- Triggers: Cognito Forms webhooks, Notion automations, manual polling endpoints
- Responsibilities:
  - Invoice submission validation and initial creation
  - Invoice allocation to cost centres
  - Release cost PDF renaming and project folder placement
  - Background polling loop for reconciliation

**Vendor Onboarding Endpoint (`/Users/pete/tnh-invoice-portal/vendor_onboarding.py`):**
- Location: Separate Flask endpoint (or integrated into app.py)
- Triggers: Cognito vendor setup form submissions
- Responsibilities: Vendor CRUD, W8/W9 document handling, confirmation emails

**Label Costs Sync Worker (`/Users/pete/tnh-label-costs/sync_label_costs.py`):**
- Location: Railway worker process running on hourly schedule
- Triggers: Scheduled jobs (cron-like via Railway)
- Responsibilities: Fetch Notion costs → classify → sync to Google Sheet with formatting

**Cloud Function Handler (`/Users/pete/tnh-cloud-function/main.py`):**
- Location: Google Cloud Function deployed separately
- Triggers: Cognito Forms webhooks (artist/product onboarding)
- Responsibilities: Create artist and product records in Notion, send confirmation emails

## Error Handling

**Strategy:** Try-catch with logging and graceful degradation

**Patterns:**

- **API Failures:** Log error, return empty/None, allow caller to decide on retry (e.g., Dropbox upload fails → keep Cognito URL as fallback)
- **Notion Rate Limits (429):** Retry up to 3 times with 10s sleep in `notion_request()`
- **Missing Data:** Return None or empty dict; caller validates and returns user-friendly error
- **Webhook Validation:** Extract payload, check required fields, return 400 on missing data
- **Dropbox Conflicts (409):** Handle specially (e.g., folder exists → return True, link exists → extract URL from error)

## Cross-Cutting Concerns

**Logging:** Console-based with log prefixes for module identification (e.g., `[WEBHOOK]`, `[DROPBOX]`, `[NOTION]`)

**Validation:** Explicit field extraction with defaults; email lowercasing; amount parsing with currency symbol stripping

**Authentication:** Environment variables for tokens (NOTION_TOKEN, DROPBOX_REFRESH_TOKEN, SHEETS_TOKEN); tokens obtained at request time (Dropbox refresh token flow)

**Rate Limiting:** Explicit sleep() calls between requests (0.35s for Google APIs, 10s retry on Notion 429)

---

*Architecture analysis: 2026-03-16*
