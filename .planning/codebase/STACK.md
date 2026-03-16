# Technology Stack

**Analysis Date:** 2026-03-16

## Languages

**Primary:**
- Python 3.x - Application code for invoice processing, vendor onboarding, and data synchronization workflows

## Runtime

**Environment:**
- Python 3 (no specific version pinned)

**Package Manager:**
- pip - Manages Python dependencies via `requirements.txt`
- Lockfile: Not present (using `requirements.txt` only)

## Frameworks

**Core:**
- Flask 2.3.3 - Web framework for webhook endpoints and HTTP routing
- Gunicorn 21.2.0 - WSGI application server for production deployment

**API/Integration:**
- requests 2.31.0 - HTTP library for external API calls (Notion, Dropbox, Google APIs)
- google-auth 2.29.0 - OAuth2 authentication for Google services
- google-api-python-client 2.127.0 - Official Google API client library (Gmail, Drive, etc.)

**Email:**
- email.mime - Built-in Python MIME module for email formatting

## Key Dependencies

**Critical:**
- requests 2.31.0 - HTTP client used for all external API calls (Notion, Dropbox, Google)
- google-api-python-client 2.127.0 - Required for Gmail integration in vendor onboarding
- Flask 2.3.3 - Web framework routing all webhook endpoints
- Gunicorn 21.2.0 - Production WSGI server for Railway deployment

**Infrastructure:**
- google-auth 2.29.0 - OAuth2 credential management for Google APIs

## Configuration

**Environment:**
- Configured via environment variables (os.environ.get)
- Key configuration variables:
  - `NOTION_TOKEN` - Bearer token for Notion API authentication
  - `DROPBOX_APP_KEY` - Dropbox OAuth app ID
  - `DROPBOX_APP_SECRET` - Dropbox OAuth app secret
  - `DROPBOX_REFRESH_TOKEN` - Dropbox refresh token for token refresh flow
  - `DROPBOX_MEMBER_ID` - Dropbox member ID for team namespace routing
  - `DROPBOX_PATH_ROOT` - JSON string with namespace_id for team root folder access
  - `GMAIL_CREDENTIALS` - Base64-encoded Google OAuth2 credentials JSON

**Build:**
- Procfile at project root: `web: gunicorn app:app --bind 0.0.0.0:$PORT`
- No additional build configuration (Flask development mode or Gunicorn production)

## Platform Requirements

**Development:**
- Python 3.x with pip
- Local Flask server: `python app.py`
- Environment variables must be configured locally

**Production:**
- Deployment target: Railway platform
- Environment variables injected by Railway deployment
- Port binding: 0.0.0.0:$PORT (dynamic PORT from Railway)
- Gunicorn as WSGI server with dynamic worker count

## Project Structure

**Location:** `/Users/pete/tnh-invoice-portal/`

**Core Files:**
- `app.py` (57KB) - Main Flask application with invoice processing webhooks and polling
- `vendor_onboarding.py` (17KB) - Separate Flask app for vendor onboarding workflow
- `requirements.txt` - Dependency manifest
- `Procfile` - Railway deployment configuration
- `README.md` - Documentation

## Deployment Configuration

**Server:**
- Gunicorn 21.2.0 with default worker settings
- Bind to 0.0.0.0:$PORT (Railway injects PORT)
- Application module: `app:app` (Flask app instance)

**Infrastructure:**
- Hosted on Railway (PaaS platform)
- Webhook receiver for Cognito Forms, Notion, and other event sources
- No database server (uses external Notion, Dropbox, Google Sheets)

---

*Stack analysis: 2026-03-16*
