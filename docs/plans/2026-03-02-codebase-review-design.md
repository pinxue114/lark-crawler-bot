# Codebase Review & Fix Design

Date: 2026-03-02

## Summary

Full codebase review of Lark CrawlerBot identifying bugs, robustness issues, security concerns, and code quality improvements. All items to be fixed except 1b (download_url format — deferred).

## P0 — Bug Fixes

### 1a. `_processed_events` memory leak (bot.py:33)

**Problem**: `_processed_events` is an unbounded `set`. Every event ID is added but never removed. Over long uptime this will exhaust memory.

**Fix**: Replace with `cachetools.TTLCache(maxsize=10000, ttl=600)`. Events auto-expire after 10 minutes. Add `cachetools` to `requirements.txt`.

**Files**: `bot.py`, `requirements.txt`

### 1c. Delayed import of `parse_qs` (crawler.py:161)

**Problem**: `from urllib.parse import parse_qs` is imported inside `_fetch_facebook_via_proxy()`, but `urlparse` and `unquote` are already imported at the top of the file.

**Fix**: Add `parse_qs` to the top-level import statement. Remove the inline import.

**Files**: `crawler.py`

## P1 — Robustness

### 2a. Multiple URL reply conflict (bot.py:375-451)

**Problem**: When a text message contains multiple URLs, the code calls `client.im.v1.message.reply()` for each URL. Lark's reply API only allows one reply per message_id — subsequent replies fail silently.

**Fix**: Collect metadata for all URLs first, then build a single card with multiple sections (one div block per URL, each with its own button). Send one reply.

**Files**: `bot.py`

### 2b. Multi-worker dedup risk (Dockerfile)

**Problem**: If `--workers` is increased from 1, each worker gets its own `_processed_events` set, breaking deduplication.

**Fix**: Add a comment in Dockerfile warning against increasing workers without external dedup (e.g., Redis). Keep current `--workers 1`.

**Files**: `Dockerfile`

### 2c. Exceptions swallowed + print-only logging (bot.py, crawler.py)

**Problem**: All logging uses `print()`. The broad `try/except` in `_process_message` (line 453) hides errors. Gunicorn captures `logging` output properly but may miss `print()` in some configurations.

**Fix**: Replace all `print()` calls with `logging` module. Use `logging.exception()` for error handlers to include stack traces. Configure logging format in bot.py entrypoint.

**Files**: `bot.py`, `crawler.py`

## P2 — Security

### 3a. `image_fbid` endpoint unauthenticated (cf-worker/src/index.js:242-270)

**Problem**: The `?image_fbid=` endpoint bypasses API key auth. Anyone can proxy Facebook images through it.

**Fix**: Add optional Referer whitelist check. If `env.ALLOWED_REFERERS` is set, validate the Referer header. This keeps the endpoint open for Lark card rendering (which sends no Referer) while limiting abuse when configured.

**Files**: `cf-worker/src/index.js`

### 3b. `raw`/`debug` params in production (cf-worker/src/index.js:291-309)

**Problem**: `raw=1` returns raw HTML, `debug=1` leaks internal debug info. Both are behind API key auth, but if the key leaks these become an information disclosure risk.

**Fix**: When `API_KEY` is not configured, disable `raw` and `debug` parameters entirely (return 403). This ensures development convenience but production safety.

**Files**: `cf-worker/src/index.js`

## P3 — Code Quality

### 4a. Reply logic duplicated 4 times (bot.py:340-451)

**Problem**: The pattern (build card → build reply body → build reply request → send) is copy-pasted 4 times in `_process_message`.

**Fix**: Extract `reply_with_card(message_id, metadata) -> bool` helper function.

**Files**: `bot.py`

### 4b. All `print()` → `logging` (same as 2c)

Covered by 2c above.

### 4c. CLAUDE.md documentation mismatch

**Problem**: CLAUDE.md says "Gunicorn (2 workers, 30s timeout)" but Dockerfile has `--workers 1 --threads 2`.

**Fix**: Update CLAUDE.md to say "Gunicorn (1 worker, 2 threads, 30s timeout)".

**Files**: `CLAUDE.md`

### 5a. `requests.Session()` created per call (crawler.py:288)

**Problem**: A new `requests.Session()` is created for every URL fetch attempt, missing connection pooling benefits.

**Fix**: Create a module-level `_session = requests.Session()` and reuse it across calls.

**Files**: `crawler.py`

### 5b. Unnecessary `_fetch_facebook_via_api` wrapper (crawler.py:127-129)

**Problem**: `_fetch_facebook_via_api()` is a one-line wrapper around `_fetch_facebook_via_microlink()` with no additional logic.

**Fix**: Replace calls to `_fetch_facebook_via_api()` with direct calls to `_fetch_facebook_via_microlink()`. Remove the wrapper function.

**Files**: `crawler.py`

## Implementation Order

1. P0 bugs first (1a, 1c) — smallest risk, highest impact
2. P3 code quality (4a, 5a, 5b) — refactoring before behavior changes
3. P1 robustness (2a, 2b, 2c/4b) — logging migration + multi-URL fix
4. P2 security (3a, 3b) — CF Worker changes
5. P3 doc fix (4c) — last, after all code changes settle
