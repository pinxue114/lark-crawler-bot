[中文版](README_zh.md)

# Lark URL Preview & Image Archival Bot

A Lark Base (Bitable) integration bot that listens for group messages via webhooks. For text messages, it extracts URLs, crawls metadata, and replies with interactive card previews. For image messages (inline or file attachments), it downloads the image, uploads it to Lark Drive, sets link sharing permissions, and replies with a confirmation card. All records are saved to a Bitable table.

## Features

- **URL Preview**: Extracts URLs from text messages, crawls webpage metadata (`og:title`, `og:description`, `<title>`, `<meta description>`, `<p>`), and replies with a rich Interactive Card preview.
- **Image Archival**: Downloads images sent in chat (both inline images and image file attachments), uploads them to a designated Lark Drive folder, enables link sharing, and replies with an "Image Saved" confirmation card.
- **File Handling**: Processes file attachments with image extensions (png/jpg/jpeg/gif/bmp/webp/tiff/heic) using the same image archival flow; non-image files are skipped.
- **Bitable Integration**: Automatically saves all records (URL previews and image uploads) into your designated Bitable table.

## Prerequisites

1. A Lark Developer Account and an App created in the [Lark Developer Console](https://open.larksuite.com/).
2. Enabled Permissions:
   - `im:message` — receive messages
   - `im:resource` — download images/files from messages
   - `drive:file:write` — upload files to Drive
   - `drive:file:permission:write` — set file sharing permissions
   - `bitable:app` — read and edit Bitable apps
3. Event Subscriptions enabled:
   - Listen to the `im.message.receive_v1` event.
4. Python 3.10+ installed.

## Setup Instructions

1. **Clone/Navigate** into the project directory:
   ```bash
   cd Lark_CrawlerBot
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Environment Configuration**:
   Copy `.env.example` to `.env` and fill in your app details from the Lark Developer Console:
   ```bash
   cp .env.example .env
   ```
   **Required — Lark App Credentials**
   *(Developer Console → your app → Credentials & Basic Info)*
   - `APP_ID` — **App ID**, shown at the top of the Credentials & Basic Info page.
   - `APP_SECRET` — **App Secret**, on the same page; click "Show" then copy.

   **Required — Event Subscription Security**
   *(Developer Console → your app → Event Subscriptions)*
   - `ENCRYPT_KEY` — **Encrypt Key**, found in the *Encryption Strategy* section of the Event Subscriptions page.
   - `VERIFICATION_TOKEN` — **Verification Token**, shown at the top of the same page.

   **Optional — Bitable** *(only needed if you want to save records)*
   - `BITABLE_APP_TOKEN` — Open your Bitable document in a browser; the token is the `{app_token}` part of the URL: `https://xxx.feishu.cn/base/{app_token}`.
   - `BITABLE_TABLE_ID` — In the same URL, look for `?table={table_id}`; alternatively, right-click a table tab in the left sidebar → Copy Link to obtain it.

   **Optional — Drive** *(only needed for image archival)*
   - `DRIVE_FOLDER_TOKEN` — Open the target folder in Lark Drive; the token is the `{token}` part of the URL: `https://xxx.feishu.cn/drive/folder/{token}`.

   **Optional — Server**
   - `PORT` — Flask server port, defaults to `5000`. Usually no change needed.

4. **Bitable Configuration**:
   Ensure your target Bitable has the following field names:
   - `Title` (Type: Text)
   - `Description` (Type: Text)
   - `URL` (Type: Link/URL or Text)
   - `Timestamp` (Type: DateTime)
   - `Sender` (Type: People)

## Running the Bot

Start the Flask server locally:
```bash
python bot.py
```

*Note:* If you are running this locally to test with Lark's Webhooks, you'll need to expose your local server using a tool like [ngrok](https://ngrok.com/) or Cloudflare Tunnels:
```bash
ngrok http 5000
```
Then copy the `https://<your-ngrok-url>.ngrok-free.app/webhook/event` URL into your Lark App's Event Subscription settings.

## Docker Deployment

Build and run with Docker Compose:
```bash
docker compose up -d
```

Or build and run manually:
```bash
docker build -t lark-crawlerbot .
docker run -d --env-file .env -p 5000:5000 lark-crawlerbot
```

The container uses Gunicorn as the production WSGI server (2 workers, 30s timeout). The health check endpoint is available at `GET /`.
