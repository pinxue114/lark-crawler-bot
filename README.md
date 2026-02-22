# Lark URL Preview Bot

A Lark Base (Bitable) integration bot that automatically extracts URLs from group messages, crawls the parsed link for Title and Description metadata, replies with a rich Interactive Card preview, and saves the data directly into a Bitable table.

## Features

- URL Extraction from text messages in Lark Groups.
- Webpage Crawling using `requests` and `beautifulsoup4` to fetch `<title>` and `<meta description>` / `<p>` tags.
- Lark Interactive Message Cards to display the URL previews beautifully in chat.
- Automatic Record Insertion into your designated Bitable Table.

## Prerequisites

1. A Lark Developer Account and an App created in the [Lark Developer Console](https://open.larksuite.com/).
2. Enabled Permissions:
   - `im:message` (Read and Send messages)
   - `bitable:app` (Read and Edit Bitable apps)
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
   *Required Variables:*
   - `APP_ID`: App ID
   - `APP_SECRET`: App Secret
   - `ENCRYPT_KEY`: Event Subscription Encrypt Key
   - `VERIFICATION_TOKEN`: Event Subscription Verification Token
   - `BITABLE_APP_TOKEN`: Token of the Bitable document (URL part)
   - `BITABLE_TABLE_ID`: Table ID inside the document.

4. **Bitable Configuration**:
   Ensure your target Bitable has the following field names:
   - `Title` (Type: Text)
   - `Description` (Type: Text)
   - `URL` (Type: Link/URL or Text)

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
