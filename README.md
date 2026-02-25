[中文版](README_zh.md)

# Lark URL Preview & Image Archival Bot

A Lark Base (Bitable) integration bot that listens for group messages via webhooks. For text messages, it extracts URLs, crawls metadata, and replies with interactive card previews. For image messages (inline or file attachments), it downloads the image, uploads it to Lark Drive, sets link sharing permissions, and replies with a confirmation card. All records are saved to a Bitable table.

## Features

- **URL Preview**: Extracts URLs from text messages, crawls webpage metadata (`og:title`, `og:description`, `<title>`, `<meta description>`, `<p>`), and replies with a rich Interactive Card preview. Facebook URLs are handled specially (see [Handling Facebook Links](#handling-facebook-links) below).
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

   **Optional — Facebook Proxy** *(improves Facebook URL metadata on cloud servers)*
   - `FB_PROXY_URL` — Cloudflare Worker proxy URL. Deploy `cf-worker/` first, then paste the Worker URL here (e.g. `https://fb-meta-proxy.<subdomain>.workers.dev`).
   - `FB_PROXY_KEY` — API key for the proxy. Must match the Worker's `API_KEY` secret; leave empty if no key is configured.

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

## Handling Facebook Links

Facebook blocks most servers from reading page titles and descriptions. When you share a Facebook link, a normal server just sees a login page instead of the actual content. The bot works around this by trying four methods in order, stopping as soon as one succeeds:

```
Facebook URL detected
        |
        v
  1. Microlink.io API ---- free third-party service (no setup needed)
        |
      failed?
        v
  2. Direct crawl -------- bot pretends to be Facebook's own crawler
        |
      failed?
        v
  3. Cloudflare Worker --- proxy on Cloudflare's network (optional setup)
        |
      failed?
        v
  4. URL parsing --------- extracts name from the URL itself
                            e.g. facebook.com/TeslaInsider → "TeslaInsider"
```

At each step, the bot checks whether Facebook returned real content or just a generic login page. If the result looks like boilerplate, it moves on to the next method.

| Method | How it works | Setup needed | Limitations |
|--------|-------------|-------------|-------------|
| Microlink.io | Third-party API fetches the page for us | None (free tier) | 250 requests/day, 1 req/s |
| Direct crawl | Requests the page using Facebook's own crawler identity | None | Often blocked on cloud servers |
| Cloudflare Worker | A small proxy on Cloudflare's network, whose IPs Facebook does not block | Deploy `cf-worker/` (see below) | 100k requests/day (free tier) |
| URL parsing | Reads the page name directly from the URL structure | None | No description, only a basic title |

> **For most users**: The bot works out of the box (methods 1, 2, and 4 require no setup). Deploy the Cloudflare Worker (method 3) only if Facebook previews are frequently missing on your server.

### Facebook Photo URLs

Facebook photo links (`/photo/?fbid=XXX`) receive special treatment. Since Facebook blocks direct access to photo images from most servers, the bot uses the Cloudflare Worker's lookaside fallback:

1. **Worker detects photo URL** — extracts the `fbid` from the URL and fetches the image from Facebook's `lookaside.fbsbx.com/lookaside/crawler/media/?media_id={fbid}` endpoint.
2. **Worker image proxy** — the `?image_fbid={fbid}` endpoint on the Worker proxies the lookaside image as a binary response, so the bot can download it without needing a special User-Agent.
3. **Bot downloads and saves** — when crawler.py returns an `image_url` for a photo URL, the bot downloads the image via the Worker proxy, uploads it to Lark Drive, and replies with a "View Image" card.

> **Note**: This feature requires the Cloudflare Worker to be deployed (`FB_PROXY_URL` must be set). Without it, photo URLs fall back to a basic title extracted from the URL.

### Deploy the Cloudflare Worker (Optional)

```bash
# 1. Install dependencies
cd cf-worker && npm install

# 2. Log in to Cloudflare (opens browser on first use)
npx wrangler login

# 3. Local dev test
npx wrangler dev
# Test: curl 'http://localhost:8787/?url=https://www.facebook.com/share/p/1DWWsctUwX/'

# 4. Deploy to Cloudflare edge network
npx wrangler deploy
# Output: Published fb-meta-proxy (https://fb-meta-proxy.<your-subdomain>.workers.dev)

# 5. (Optional) Set an API key for protection
npx wrangler secret put API_KEY
```

Then add to your `.env`:
```
FB_PROXY_URL=https://fb-meta-proxy.<your-subdomain>.workers.dev
FB_PROXY_KEY=your_secret_key
```

**Cloudflare Workers free tier**: 100,000 requests/day, 10ms CPU per invocation, no credit card required.
