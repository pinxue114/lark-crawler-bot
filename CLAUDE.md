# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Lark URL Preview & Image Archival Bot — a Flask-based integration bot for Lark that listens for group messages via webhooks. For text messages, it extracts URLs, crawls metadata, and replies with interactive card previews. For image messages (inline or file attachments), it downloads the image, uploads it to Lark Drive, sets link sharing permissions, and replies with a confirmation card. All records are saved to a Bitable table.

Requires Python 3.10+.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot (Flask server on port 5000)
python bot.py

# Test the crawler module standalone
python crawler.py

# Expose local server for Lark webhooks (development)
ngrok http 5000
```

No test framework, linter, or build system is configured.

## Architecture

Two-file codebase:

- **bot.py** — Flask app and Lark SDK integration. Receives webhook events at `POST /webhook/event`, dispatches to `do_p2_im_message_receive_v1` handler. Handles three message types:
  - **Text messages**: extracts URLs, crawls metadata via crawler.py, replies with "Link Preview" card, saves to Bitable.
  - **Image messages** (`msg_type == "image"`): downloads via `download_message_resource()`, uploads to Drive via `upload_to_drive()`, sets link sharing via `set_file_link_sharing()`, replies with "Image Saved" card, saves record (Title=圖片) to Bitable.
  - **File messages** (`msg_type == "file"`): same flow as image, but only processes image file extensions (png/jpg/jpeg/gif/bmp/webp/tiff/heic); non-image files are skipped.
  Health check at `GET /`.

- **crawler.py** — Stateless URL utilities. `extract_urls(text)` uses regex to find URLs. `fetch_page_metadata(url)` does HTTP GET with BeautifulSoup parsing; prioritizes `og:title`/`og:description` over standard HTML tags, falls back to first `<p>` for description (truncated to 200 chars). 10-second timeout.

## Configuration

All config via `.env` file (see `.env.example`). Key variables:
- `APP_ID`, `APP_SECRET` — Lark app credentials
- `ENCRYPT_KEY`, `VERIFICATION_TOKEN` — Lark event subscription security
- `BITABLE_APP_TOKEN`, `BITABLE_TABLE_ID` — target Bitable table (optional; bot works without them but skips saving)
- `DRIVE_FOLDER_TOKEN` — Lark Drive folder token for image uploads (required for image handling; obtain from folder URL `https://xxx.feishu.cn/drive/folder/{token}`)
- `PORT` — server port (default 5000)

## Lark SDK Patterns

The codebase uses `lark-oapi` SDK builder pattern throughout:
- `lark.Client.builder()` for client initialization
- `lark.EventDispatcherHandler.builder()` for event routing
- Request objects built with chained `.builder()...build()` calls
- Drive sub-resources use underscores: `client.drive.v1.permission_public.patch()` (not dot notation)

## Required App Permissions

- `im:message` — receive messages
- `im:resource` — download images/files from messages
- `drive:file:write` — upload files to Drive
- `drive:file:permission:write` — set file sharing permissions

## Bitable Schema

Target table must have fields: `Title` (Text), `Description` (Text), `URL` (Link), `Timestamp` (DateTime), `Sender` (People).
