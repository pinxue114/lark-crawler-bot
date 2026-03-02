# Codebase Review Fixes — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all bugs, robustness issues, security concerns, and code quality problems identified in the codebase review (design doc: `docs/plans/2026-03-02-codebase-review-design.md`).

**Architecture:** Incremental fixes to existing two-file Python codebase (`bot.py`, `crawler.py`) and CF Worker (`cf-worker/src/index.js`). No new files created. Each task is a self-contained commit.

**Tech Stack:** Python 3.10+, Flask, lark-oapi, requests, BeautifulSoup, cachetools (new dep), Cloudflare Workers (JS)

**Note:** No test framework is configured. Verification is done via `python -c` smoke tests and syntax checks.

---

### Task 1: Fix `_processed_events` memory leak (P0 — 1a)

**Files:**
- Modify: `requirements.txt` (add cachetools)
- Modify: `bot.py:1-36` (import + replace set with TTLCache)

**Step 1: Add cachetools to requirements.txt**

In `requirements.txt`, add after the last line:

```
cachetools>=5.3.0
```

**Step 2: Install the new dependency**

Run: `pip install cachetools>=5.3.0`
Expected: Successfully installed cachetools

**Step 3: Replace `_processed_events` set with TTLCache in bot.py**

In `bot.py`, add import at line 1 area:

```python
from cachetools import TTLCache
```

Replace line 33:

```python
_processed_events = set()
```

with:

```python
_processed_events = TTLCache(maxsize=10000, ttl=600)  # auto-expire after 10 min
```

Replace lines 262-265 (the dedup block inside `do_p2_im_message_receive_v1`):

```python
    with _event_lock:
        if event_id in _processed_events:
            print(f"Skipping duplicate event: {event_id}")
            return
        _processed_events.add(event_id)
```

with:

```python
    with _event_lock:
        if event_id in _processed_events:
            print(f"Skipping duplicate event: {event_id}")
            return
        _processed_events[event_id] = True
```

Note: TTLCache uses dict-style `[key] = value` instead of `.add()`.

**Step 4: Verify syntax**

Run: `python -c "import bot" 2>&1 | head -5`
Expected: No ImportError or SyntaxError (may show Lark SDK warnings, that's OK)

**Step 5: Commit**

```bash
git add requirements.txt bot.py
git commit -m "fix: replace unbounded _processed_events set with TTLCache

Prevents memory leak from event IDs accumulating indefinitely.
Uses cachetools.TTLCache with 10-minute TTL and 10k max size."
```

---

### Task 2: Fix delayed import + remove wrapper function (P0 — 1c, P3 — 5b)

**Files:**
- Modify: `crawler.py:1-5` (top-level imports)
- Modify: `crawler.py:127-129` (remove `_fetch_facebook_via_api`)
- Modify: `crawler.py:161` (remove inline import)
- Modify: `crawler.py:242` (call site)

**Step 1: Add `parse_qs` to top-level import in crawler.py**

Change line 5:

```python
from urllib.parse import urlparse, unquote
```

to:

```python
from urllib.parse import urlparse, unquote, parse_qs
```

**Step 2: Remove inline import in `_fetch_facebook_via_proxy`**

Delete line 161:

```python
                from urllib.parse import parse_qs
```

**Step 3: Remove `_fetch_facebook_via_api` wrapper**

Delete lines 127-129:

```python
def _fetch_facebook_via_api(url: str) -> dict | None:
    """Try metadata APIs for Facebook URLs. Returns first meaningful result or None."""
    return _fetch_facebook_via_microlink(url)
```

**Step 4: Update call site in `fetch_page_metadata`**

Change line 242:

```python
        api_result = _fetch_facebook_via_api(url)
```

to:

```python
        api_result = _fetch_facebook_via_microlink(url)
```

**Step 5: Verify syntax**

Run: `python -c "from crawler import extract_urls, fetch_page_metadata; print('OK')"`
Expected: `OK`

**Step 6: Commit**

```bash
git add crawler.py
git commit -m "fix: move parse_qs to top-level import, remove redundant wrapper

- parse_qs now imported at module level alongside urlparse/unquote
- _fetch_facebook_via_api was a passthrough to _fetch_facebook_via_microlink"
```

---

### Task 3: Extract reply helper + reuse requests.Session (P3 — 4a, 5a)

**Files:**
- Modify: `bot.py:60-106` (add helper function)
- Modify: `bot.py:312-454` (refactor `_process_message` to use helper)
- Modify: `crawler.py:4,269-290` (module-level session)

**Step 1: Add `reply_with_card` helper in bot.py**

Add after `build_card_message` function (after line 106):

```python
def reply_with_card(message_id: str, metadata: dict) -> bool:
    """Build a card and reply to a message. Returns True on success."""
    card_content = build_card_message(metadata)

    reply_body = ReplyMessageRequestBody.builder() \
        .content(card_content) \
        .msg_type("interactive") \
        .build()

    reply_req = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(reply_body) \
        .build()

    resp = client.im.v1.message.reply(reply_req)
    if not resp.success():
        print(f"Failed to send reply: {resp.code} {resp.msg}, req_id: {resp.get_log_id()}")
        return False
    return True
```

**Step 2: Refactor `_process_message` image/file branch**

Replace the reply block in the image/file branch (lines ~340-359) with:

```python
            reply_with_card(message_id, {
                "title": "Image Saved",
                "description": "Image has been saved to Drive.",
                "url": download_url,
                "button_text": "View Image",
            })
```

**Step 3: Refactor `_process_message` text URL branches**

Replace all 3 remaining reply blocks (Facebook image success, Facebook image failure, normal link preview) with calls to `reply_with_card(message_id, {...})`.

**Step 4: Add module-level session in crawler.py**

Add after the imports (after line 4):

```python
_session = requests.Session()
```

Replace all `requests.get(...)` calls in crawler.py with `_session.get(...)`.

Replace the session creation block in `fetch_page_metadata` (lines 288-290):

```python
            session = requests.Session()
            session.headers.update(headers)
            response = session.get(url, timeout=10, allow_redirects=True)
```

with:

```python
            response = _session.get(url, headers=headers, timeout=10, allow_redirects=True)
```

Note: Pass headers per-request instead of updating the shared session to avoid cross-request header leakage.

**Step 5: Verify syntax**

Run: `python -c "import bot; from crawler import fetch_page_metadata; print('OK')"`
Expected: `OK`

**Step 6: Commit**

```bash
git add bot.py crawler.py
git commit -m "refactor: extract reply_with_card helper, reuse requests.Session

- Deduplicated 4 identical reply code blocks into one helper
- Module-level requests.Session for connection pooling in crawler.py"
```

---

### Task 4: Fix multi-URL reply conflict (P1 — 2a)

**Files:**
- Modify: `bot.py` — `_process_message` text URL loop

**Step 1: Refactor text URL processing to collect results then reply once**

Replace the text URL processing section in `_process_message` (from `urls = extract_urls(text)` through end of the for loop) with logic that:

1. Iterates URLs, collects metadata + handles image downloads as before
2. Builds a single card with multiple element sections
3. Sends one reply
4. Saves each record to Bitable

The card structure for multiple URLs: each URL gets a `div` (title), `div` (description), `action` (button), then an `hr` separator before the next URL.

**Step 2: Update `build_card_message` to accept a list**

Add a new function `build_multi_card_message(items: list[dict]) -> str` that builds a card with multiple URL sections separated by `hr` dividers. Keep `build_card_message` for single-item use (image/file replies).

```python
def build_multi_card_message(items: list[dict]) -> str:
    """Build a card with multiple URL preview sections."""
    elements = []
    for i, metadata in enumerate(items):
        if i > 0:
            elements.append({"tag": "hr"})
        elements.extend([
            {
                "tag": "div",
                "text": {
                    "content": f"**Title:** {metadata.get('title')}",
                    "tag": "lark_md"
                }
            },
            {
                "tag": "div",
                "text": {
                    "content": f"**Description:** {metadata.get('description')}",
                    "tag": "lark_md"
                }
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "content": metadata.get('button_text', 'Visit Link'),
                            "tag": "plain_text"
                        },
                        "url": metadata.get('url'),
                        "type": "primary"
                    }
                ]
            },
        ])

    card = {
        "config": {"wide_screen_mode": True},
        "elements": elements,
        "header": {
            "template": "blue",
            "title": {"content": "Link Preview", "tag": "plain_text"}
        }
    }
    return json.dumps(card)
```

**Step 3: Rewrite text URL loop**

```python
        # Text message with URLs
        # ... (parse text, extract URLs as before) ...

        card_items = []
        bitable_records = []

        for url in urls:
            print(f"Processing URL: {url}")
            metadata = fetch_page_metadata(url)
            image_url = metadata.get("image_url")

            if image_url:
                file_obj, file_name = download_image_from_url(image_url)
                if file_obj:
                    file_token = upload_to_drive(file_obj, file_name)
                    if file_token:
                        set_file_link_sharing(file_token)
                        download_url = f"https://feishu.cn/file/{file_token}"
                        card_items.append({
                            "title": metadata.get("title", "Image Saved"),
                            "description": metadata.get("description", ""),
                            "url": download_url,
                            "button_text": "View Image",
                        })
                        bitable_records.append({
                            "title": metadata.get("title", "圖片"),
                            "description": metadata.get("description", ""),
                            "url": download_url,
                        })
                        continue

                # Download or upload failed
                card_items.append({
                    "title": "圖片下載失敗",
                    "description": f"無法從 Facebook 下載圖片：{metadata.get('title', '')}",
                    "url": url,
                    "button_text": "Open Link",
                })
                continue

            # Normal link preview
            card_items.append(metadata)
            bitable_records.append(metadata)

        # Single reply for all URLs
        if card_items:
            if len(card_items) == 1:
                reply_with_card(message_id, card_items[0])
            else:
                card_content = build_multi_card_message(card_items)
                reply_body = ReplyMessageRequestBody.builder() \
                    .content(card_content) \
                    .msg_type("interactive") \
                    .build()
                reply_req = ReplyMessageRequest.builder() \
                    .message_id(message_id) \
                    .request_body(reply_body) \
                    .build()
                resp = client.im.v1.message.reply(reply_req)
                if not resp.success():
                    print(f"Failed to send reply: {resp.code} {resp.msg}, req_id: {resp.get_log_id()}")

        for record_meta in bitable_records:
            save_to_bitable(record_meta, timestamp_ms, sender_open_id)
```

**Step 4: Verify syntax**

Run: `python -c "import bot; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add bot.py
git commit -m "fix: collect all URL results and send single reply

Multiple URLs in one message now produce one combined card instead
of multiple reply attempts (only the first would succeed)."
```

---

### Task 5: Migrate print() to logging (P1 — 2c / P3 — 4b)

**Files:**
- Modify: `bot.py` (all `print()` calls → `logging`, add logging config)
- Modify: `crawler.py` (all `print()` calls → `logging`)

**Step 1: Add logging setup in bot.py**

Add `import logging` at the top. After `load_dotenv()`, add:

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)
```

**Step 2: Replace all print() in bot.py**

- `print(f"...")` → `logger.info(f"...")`
- `print(f"Failed to ...")` → `logger.error(f"...")`
- `print(f"Exception ...")` → `logger.exception(f"...")`
- The broad except in `_process_message` line 453: change to `logger.exception(...)` to include stack trace

**Step 3: Add logging in crawler.py**

Add `import logging` and `logger = logging.getLogger(__name__)` at top.

Replace all `print()` with appropriate `logger.info()` / `logger.error()` / `logger.warning()`.

**Step 4: Verify syntax**

Run: `python -c "import bot; from crawler import fetch_page_metadata; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add bot.py crawler.py
git commit -m "refactor: migrate all print() to logging module

Structured logging with timestamps and levels. Exception handlers
now use logger.exception() for full stack traces."
```

---

### Task 6: Add Dockerfile dedup warning (P1 — 2b)

**Files:**
- Modify: `Dockerfile:12`

**Step 1: Add warning comment**

Change the CMD line in Dockerfile:

```dockerfile
# WARNING: --workers must stay at 1 unless external dedup (e.g. Redis) is added.
# Each worker has its own in-memory event dedup set — multiple workers = duplicate processing.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "2", "--timeout", "30", "bot:app"]
```

**Step 2: Commit**

```bash
git add Dockerfile
git commit -m "docs: add worker count warning to Dockerfile

Explains why --workers must stay at 1 without external dedup."
```

---

### Task 7: CF Worker security hardening (P2 — 3a, 3b)

**Files:**
- Modify: `cf-worker/src/index.js:233-310`

**Step 1: Add rate limit awareness to image_fbid endpoint**

After the `image_fbid` validation (line 245), add optional Referer check:

```javascript
    if (imageFbid) {
      if (!/^\d+$/.test(imageFbid)) {
        return Response.json({ error: 'Invalid image_fbid (must be numeric)' }, { status: 400 });
      }
      // Optional: restrict image proxy to known referers
      const allowedReferers = env.ALLOWED_REFERERS; // comma-separated, e.g. "feishu.cn,larksuite.com"
      if (allowedReferers) {
        const referer = request.headers.get('Referer') || '';
        const refHost = referer ? new URL(referer).hostname : '';
        const allowed = allowedReferers.split(',').map(s => s.trim());
        if (referer && !allowed.some(a => refHost.endsWith(a))) {
          return Response.json({ error: 'Forbidden' }, { status: 403 });
        }
      }
      // ... rest of image proxy logic unchanged ...
```

Note: Empty Referer is allowed (Lark card renderer / direct bot download may not send Referer).

**Step 2: Gate raw/debug behind API_KEY requirement**

After the `isFacebookUrl` check, before the `debug`/`raw` parameter handling, add:

```javascript
    // raw and debug modes require API_KEY to be configured
    if (!apiKey && (params.get('raw') === '1' || params.get('debug') === '1')) {
      return Response.json({ error: 'Debug features require API_KEY configuration' }, { status: 403 });
    }
```

**Step 3: Verify syntax**

Run: `cd cf-worker && npx wrangler deploy --dry-run 2>&1 | tail -5`
Expected: No syntax errors (may show deployment info)

**Step 4: Commit**

```bash
git add cf-worker/src/index.js
git commit -m "security: add Referer whitelist for image proxy, gate debug modes

- image_fbid: optional ALLOWED_REFERERS env var for abuse prevention
- raw/debug: now require API_KEY to be configured (no key = no debug)"
```

---

### Task 8: Update CLAUDE.md documentation (P3 — 4c)

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Fix Gunicorn description**

Find in CLAUDE.md the text:

```
- Docker Compose with Gunicorn (2 workers, 30s timeout)
```

Replace with:

```
- Docker Compose with Gunicorn (1 worker, 2 threads, 30s timeout)
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: fix Gunicorn config description in CLAUDE.md

Was '2 workers', actual config is '1 worker, 2 threads'."
```

---

### Task 9: Final verification

**Step 1: Verify all files parse correctly**

Run: `python -c "import bot; from crawler import extract_urls, fetch_page_metadata; print('All imports OK')"`
Expected: `All imports OK`

**Step 2: Run crawler standalone test**

Run: `python crawler.py`
Expected: Extracts URLs from sample text and prints metadata (no crashes)

**Step 3: Verify CF Worker syntax**

Run: `cd cf-worker && npx wrangler deploy --dry-run 2>&1 | tail -5`
Expected: No errors

**Step 4: Review git log**

Run: `git log --oneline -10`
Expected: 8 new commits (Tasks 1-8) in order
