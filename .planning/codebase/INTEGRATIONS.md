# External Integrations

**Analysis Date:** 2026-03-16

## APIs & External Services

**Notion Database API:**
- Invoices database management - Create/read invoice records during submission and allocation workflows
  - SDK/Client: requests library with manual Notion API v1 implementation
  - Auth: Bearer token via `NOTION_TOKEN` environment variable
  - Version: Notion-Version header set to `2022-06-28`
  - Endpoints used:
    - POST `/v1/pages` - Create invoice, cost centre, and vendor records
    - GET `/v1/pages/{page_id}` - Fetch invoice details and vendor information
    - PATCH `/v1/pages/{page_id}` - Update page properties (invoice status, PDF links)
    - POST `/v1/databases/{db_id}/query` - Query vendor database by email filter
  - Databases accessed:
    - `310e7b468ee7804eaf4cdd23d54765a2` - Invoices DB
    - `313e7b468ee7809e877ee8ba58d31346` - Vendors DB
    - `222e7b468ee7803f857af3b304254cca` - Projects DB
    - Cost Centre DBs: releases, label, events, royalties

**Dropbox API (OAuth2 Refresh Token Flow):**
- Invoice PDF file storage, organization, and team folder management
  - SDK/Client: requests library with manual Dropbox API v2 implementation
  - Auth: OAuth2 refresh token flow (`DROPBOX_REFRESH_TOKEN`)
    - Token exchange endpoint: `https://api.dropbox.com/oauth2/token`
    - App credentials: `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`
    - Member ID: `DROPBOX_MEMBER_ID` (dbmid:AABJCixa9Cw841nDVcHB29jQpG46nEATwkA)
    - Namespace routing: `DROPBOX_PATH_ROOT` JSON with namespace_id for team root
  - Endpoints used:
    - POST `/2/files/upload` - Upload invoice PDF files
    - POST `/2/sharing/create_shared_link_with_settings` - Generate public share links
    - POST `/2/sharing/list_shared_links` - Retrieve existing shared links
    - POST `/2/files/create_folder_v2` - Create invoice organization folders
    - POST `/2/files/list_folder` - Search for project cost folders
    - POST `/2/files/move_v2` - Move/rename invoice files
  - Folder structure:
    - `/Accounting/Invoices/Royalties` - Royalty invoice PDFs
    - `/Accounting/Invoices/Label Costs` - Label cost invoice PDFs
    - `/Accounting/Invoices/Project Costs/{project-id}/` - Release cost PDFs by project
    - `/Vendors/` - Vendor onboarding documents (W8/W9 forms)

**Google API (Gmail + Google Drive):**
- Email notifications for vendor onboarding confirmations
  - SDK/Client: google-api-python-client v2.127.0 with google-auth v2.29.0
  - Auth: OAuth2 credentials stored as base64 JSON in `GMAIL_CREDENTIALS`
    - Scopes: `https://www.googleapis.com/auth/gmail.send`
    - Token refresh via google-oauth2 endpoint
  - Service: Gmail API v1
  - Use case: Send admin confirmation emails when vendors are onboarded
  - Location: `vendor_onboarding.py` function `send_email()` (lines 193+)

## Data Storage

**Databases:**
- **Notion** (primary database system)
  - Connection: Notion API via Bearer token authentication
  - Client: Manual HTTP requests to Notion v1 API
  - Content: Invoice records, vendor information, cost centre allocations, project data
  - Type: Cloud-based relational/property database

**File Storage:**
- **Dropbox** (team shared filesystem)
  - Connection: OAuth2 refresh token flow
  - Purpose: PDF invoice storage with public shareable links
  - Team namespace: Shared team folder (not personal namespace)
  - Automatic folder hierarchy: Invoices organized by cost centre type and project

**Caching:**
- None configured - All data fetched fresh from Notion and Dropbox on each request

## Authentication & Identity

**Auth Provider:**
- Custom multi-provider OAuth2 setup:
  - Notion: Bearer token (service account token)
  - Dropbox: OAuth2 refresh token flow
  - Google: OAuth2 credentials with service-to-service authentication

**Implementation Details:**
- `notion_request()` function: `app.py` lines 55-83
  - Retry logic with exponential backoff on rate limits (429 errors)
  - 3 retries with 10s wait on rate limit, 5s between normal retries
  - 30s timeout on all requests
- `get_dropbox_access_token()` function: `app.py` lines 172-184
  - Refresh token exchange on every API call (no local caching)
  - Fallback if no refresh token available
- Google OAuth2: `vendor_onboarding.py` lines 193-210
  - Credentials loaded from base64-encoded JSON in `GMAIL_CREDENTIALS` env var
  - Token URI: `https://oauth2.googleapis.com/token`

## Monitoring & Observability

**Error Tracking:**
- None configured - No Sentry, DataDog, or other error tracking service

**Logs:**
- Console logging with [PREFIX] tags for debugging
  - [NOTION] - Notion API operations
  - [DROPBOX] - Dropbox file operations
  - [VENDOR] - Vendor lookup/creation
  - [INVOICE] - Invoice processing
  - [PDF] - PDF download/upload
  - [COST] - Cost centre record creation
  - [ONBOARD] - Vendor onboarding workflow
- Logged to stdout (captured by Railway deployment logs)
- No persistent logging database

## CI/CD & Deployment

**Hosting:**
- Railway platform (PaaS)
- No custom domain configuration in code (handled by Railway)

**CI Pipeline:**
- None configured - No GitHub Actions, GitLab CI, or other automated testing
- Manual deployment via Railway git integration or CLI

**Application Health:**
- Health check endpoint: `GET /health` returns 200 OK
- Returns: `{'status': 'OK'}` JSON

## Environment Configuration

**Required env vars (production):**
- `NOTION_TOKEN` - Notion API bearer token (mandatory, no default)
- `DROPBOX_APP_KEY` - Dropbox OAuth app ID (mandatory)
- `DROPBOX_APP_SECRET` - Dropbox OAuth app secret (mandatory)
- `DROPBOX_REFRESH_TOKEN` - Dropbox refresh token (mandatory)
- `DROPBOX_MEMBER_ID` - Dropbox member ID for team routing (default: dbmid:AABJCixa9Cw841nDVcHB29jQpG46nEATwkA)
- `DROPBOX_PATH_ROOT` - Dropbox team namespace JSON (default: namespace_id 2628699171)
- `GMAIL_CREDENTIALS` - Base64-encoded Google OAuth2 JSON (for vendor onboarding emails)

**Optional env vars:**
- Flask environment variables (DEBUG, TESTING, etc.)

**Secrets location:**
- Railway environment variables (production)
- `.env` file for local development (not committed to git)
- Note: `NOTION_TOKEN` has a hardcoded default in code (should be removed in production)

## Webhooks & Callbacks

**Incoming Webhooks:**
- `POST /submit-invoice` (lines 814-975 in app.py)
  - Source: Cognito Forms invoice submission form
  - Payload: Invoice details (amount, company, date, PDF URL, description)
  - Processing: Creates invoice record, uploads PDF to Dropbox, allocates to cost centre if known
  - Return: JSON with invoice ID or error message

- `POST /allocate-invoice` (lines 976-1100 in app.py)
  - Source: Notion webhook when invoice reconciliation status changes
  - Payload: Invoice page ID
  - Processing: Fetches invoice details, creates cost centre record, moves PDF to cost centre folder
  - Return: JSON with cost record ID or error message

- `POST /allocate-invoice-legacy` (lines 982-1100 in app.py)
  - Legacy endpoint for older invoice allocation workflow
  - Same processing as `/allocate-invoice`

- `POST /rename-release-cost` (lines 1101-1131 in app.py)
  - Source: Notion webhook when release cost project is assigned
  - Payload: Release cost page ID
  - Processing: Moves project cost PDF to project-specific folder with project ID in filename
  - Return: JSON with move operation result

- `POST /poll-release-costs` (lines 1132-1138 in app.py)
  - Manual trigger endpoint for background release cost processing
  - Invokes background poller thread

- `POST /poll-invoices` (lines 1139-1145 in app.py)
  - Manual trigger endpoint for background invoice processing
  - Invokes background poller thread

**Outgoing Webhooks/Callbacks:**
- None explicit - Application calls external APIs directly (Notion, Dropbox, Gmail)

**Background Polling:**
- `poll_invoices()` thread: Runs continuously, polls Invoices DB for reconciled invoices
  - Frequency: 60-second interval with exponential backoff
  - Purpose: Allocate reconciled invoices to cost centres asynchronously
  - Location: Lines 670-768

- `poll_release_costs()` thread: Runs continuously, polls Projects DB for assigned release costs
  - Frequency: 60-second interval with exponential backoff
  - Purpose: Move/rename project cost PDFs when project assignment completes
  - Location: Lines 769-803

- `run_poller()` daemon: Started on app startup (line 805)
  - Runs both polling threads in background
  - Daemon threads (exit when main app exits)

## Vendor Onboarding Integrations

**Cognito Forms Integration:**
- Webhook payload structure:
  - CompanyInformation (company_name, contact_email, alternative_email)
  - ContactPersonDetails (name, role, phone)
  - BusinessAddress (street, city, state, country)
  - TaxInformation (tax_id, tax_form)
  - AdditionalInformation
  - Id, Entry (Cognito form metadata)

**W8/W9 Form Processing:**
- PDF downloaded from Cognito Forms submission
- Uploaded to Dropbox `/Vendors/` folder
- Shared link stored in Notion Vendors DB `w8/w9 form` field
- Location: `vendor_onboarding.py` lines 193-371

**Admin Email Notification:**
- Email sent to `admin@this-never-happened.com`
- Content: HTML table with vendor details (name, email, alt email, address, tax info, forms)
- Triggered after successful vendor record creation
- Location: `vendor_onboarding.py` line 371

## Rate Limiting & Throttling

**Notion API:**
- Manual rate limit handling in `notion_request()` function
- On 429 (Too Many Requests): Wait 10 seconds before retry
- Max 3 retries for any request
- Potential issue: Hardcoded 10s wait may cause delays in webhook processing

**Dropbox API:**
- No explicit rate limit handling
- 30s timeout on all requests
- Risk: Requests will fail if Dropbox is slow or rate-limited

**Gmail API:**
- No explicit rate limit handling in send_email()
- Risk: Email send failures not retried

---

*Integration audit: 2026-03-16*
