# Code Conventions

**Codebase:** /Users/pete (multi-project Python monorepo)
**Analyzed:** 2026-03-16

## Language & Style

- **Language:** Python (sole language across all projects)
- **Naming:**
  - `snake_case` for all functions and variables
  - `UPPER_CASE` for module-level constants
  - Descriptive names preferred over abbreviations
- **No linting config detected** — no `.flake8`, `.pylintrc`, `pyproject.toml` lint sections

## Module Structure

- Module-level docstrings are mandatory (present in all main files)
- Section headers use `# ── Section Name ──` format to visually separate logical blocks
- Constants declared at top of file after imports

## Logging

- `print()` used for all logging — no `logging` module
- Tags prefix output: `[PREFIX] message` (e.g., `[INFO]`, `[ERROR]`, `[SYNC]`)
- No structured logging or log levels beyond conventions

## Error Handling

- `try/except` blocks with retry logic for external API calls
- Functions return `None` on error (exceptions not propagated to caller)
- Errors printed to stdout with descriptive prefix tags

## Patterns

- Scripts are largely standalone — minimal shared utilities
- External API clients initialized at module level or in `main()`
- Configuration via environment variables (loaded with `os.environ` or `python-dotenv`)

## File Conventions

- Entry point: `main.py` or `app.py` per project
- No `__init__.py` / package structure — flat script organization
- Requirements tracked in `requirements.txt` per project

---
*Mapped: 2026-03-16*
