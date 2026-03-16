# Concerns

**Codebase:** /Users/pete (multi-project Python monorepo)
**Analyzed:** 2026-03-16

## Security

- **Hardcoded credential defaults** — env vars have fallback values that look like real credentials; any misconfigured deploy exposes them
- **Flask debug mode enabled** — `app.run(debug=True)` in production contexts exposes stack traces
- **Exposed admin email** — hardcoded admin contact visible in source
- **No webhook signature verification** — incoming webhooks accepted without HMAC validation

## Error Handling

- **Bare `except` clauses** — `except Exception` without re-raise swallows unexpected errors silently
- **Silent suppression** — errors printed and `None` returned; callers don't distinguish "not found" from "API failure"
- **Missing null checks** — API responses assumed to have expected fields; KeyError risk on schema changes

## Performance

- **Synchronous API calls blocking requests** — all Notion/Sheets calls are synchronous in request handlers
- **No rate limiting** — no backoff strategy if API rate limits are hit
- **Inefficient Notion queries** — full database fetches where filtered queries would suffice

## Data Integrity

- **No duplicate detection** — reprocessing the same webhook/event can create duplicate records
- **Inconsistent field mappings** — same logical data mapped differently across databases
- **Fragile unique ID extraction** — brittle string parsing to extract IDs from Notion page titles/URLs

## Testing

- **Zero test coverage** — no unit, integration, or end-to-end tests across any project
- **No API mocking** — all testing done against live external services
- **No regression safety net** — any refactor risks breaking working behavior undetected

## Incomplete Features

- **TODO: project folder organization** — multiple TODOs in `tnh-invoice-portal/app.py` for unfinished folder logic
- **Missing event folder organization** — referenced in code but not implemented
- **Partial vendor onboarding flow** — `vendor_onboarding.py` has stubs not fully wired up

## Technical Debt

- **Duplicated logic** — similar Notion query patterns repeated across files with slight variations
- **No shared utilities** — common helpers (API wrappers, retry logic) copy-pasted between projects
- **Large monolithic files** — `tnh-invoice-portal/app.py` at 1170 lines handles too many concerns

---
*Mapped: 2026-03-16*
