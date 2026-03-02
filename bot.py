import io
import logging
import os
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from cachetools import TTLCache
from urllib.parse import urlparse

import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    ReplyMessageRequest,
    ReplyMessageRequestBody,
    GetMessageResourceRequest,
)
from lark_oapi.api.drive.v1 import (
    UploadAllFileRequest,
    UploadAllFileRequestBody,
    PatchPermissionPublicRequest,
    PermissionPublicRequest,
)
from lark_oapi.api.bitable.v1 import (
    CreateAppTableRecordRequest,
    AppTableRecord
)

from crawler import extract_urls, fetch_page_metadata, _is_safe_url

# Event deduplication: Lark may retry delivery if response is slow
_processed_events = TTLCache(maxsize=10000, ttl=600)  # auto-expire after 10 min
_event_lock = threading.Lock()          # Atomic check-then-add for dedup
_executor = ThreadPoolExecutor(max_workers=4)  # Background processing pool
_bot_start_time = int(time.time())

# Load environment variables
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

APP_ID = os.getenv("APP_ID")
APP_SECRET = os.getenv("APP_SECRET")
ENCRYPT_KEY = os.getenv("ENCRYPT_KEY")
VERIFICATION_TOKEN = os.getenv("VERIFICATION_TOKEN")

BITABLE_APP_TOKEN = os.getenv("BITABLE_APP_TOKEN")
BITABLE_TABLE_ID = os.getenv("BITABLE_TABLE_ID")
DRIVE_FOLDER_TOKEN = os.getenv("DRIVE_FOLDER_TOKEN")
PORT = int(os.getenv("PORT", 5000))

# Initialize Lark Client
client = lark.Client.builder() \
    .app_id(APP_ID) \
    .app_secret(APP_SECRET) \
    .log_level(lark.LogLevel.DEBUG) \
    .build()

app = Flask(__name__)

def build_card_message(metadata: dict) -> str:
    """
    Constructs a Lark interactive message card JSON.
    """
    card = {
        "config": {
            "wide_screen_mode": True
        },
        "elements": [
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
                "actions": _build_action_buttons(metadata),
            }
        ],
        "header": {
            "template": "blue",
            "title": {
                "content": "Link Preview",
                "tag": "plain_text"
            }
        }
    }
    return json.dumps(card)


def _build_action_buttons(metadata: dict) -> list:
    """Build action buttons: primary link + optional Bitable link."""
    buttons = [
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
    if BITABLE_APP_TOKEN:
        buttons.append({
            "tag": "button",
            "text": {
                "content": "前往多維表格",
                "tag": "plain_text"
            },
            "url": f"https://feishu.cn/base/{BITABLE_APP_TOKEN}",
            "type": "default"
        })
    return buttons

def build_multi_card_message(items: list) -> str:
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
                "actions": _build_action_buttons(metadata),
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
        logger.error(f"Failed to send reply: {resp.code} {resp.msg}, req_id: {resp.get_log_id()}")
        return False
    return True

def save_to_bitable(metadata: dict, timestamp_ms: int, sender_open_id: str):
    """
    Saves the extracted URL metadata to Lark Bitable.
    """
    if not BITABLE_APP_TOKEN or not BITABLE_TABLE_ID:
        logger.warning("Bitable credentials not configured. Skipping save.")
        return

    try:
        # Assuming the base has 'Title', 'Description', and 'URL' fields
        record = AppTableRecord.builder().fields({
            "Title": metadata.get('title'),
            "Description": metadata.get('description'),
            "URL": {"text": metadata.get('url'), "link": metadata.get('url')},
            "Timestamp": timestamp_ms,
            "Sender": [{"id": sender_open_id}],
        }).build()

        req = CreateAppTableRecordRequest.builder() \
            .app_token(BITABLE_APP_TOKEN) \
            .table_id(BITABLE_TABLE_ID) \
            .request_body(record) \
            .build()
            
        resp = client.bitable.v1.app_table_record.create(req)
        
        if not resp.success():
            logger.error(f"Failed to add bitable record: {resp.code} {resp.msg} {resp.raw.content}")
        else:
            logger.info(f"Successfully added record to Bitable! record_id: {resp.data.record.record_id}")
    except Exception as e:
        logger.exception(f"Exception saving to bitable: {e}")

def download_message_resource(message_id: str, file_key: str, resource_type: str = "image") -> tuple:
    """
    Downloads an image or file from a Lark message.
    Returns (file_obj, file_name).
    """
    req = GetMessageResourceRequest.builder() \
        .message_id(message_id) \
        .file_key(file_key) \
        .type(resource_type) \
        .build()

    resp = client.im.v1.message_resource.get(req)
    if not resp.success():
        logger.error(f"Failed to download {resource_type}: {resp.code} {resp.msg}")
        return None, None

    file_name = resp.file_name if hasattr(resp, 'file_name') and resp.file_name else f"{file_key}.png"
    return resp.file, file_name


def upload_to_drive(file_obj, file_name: str) -> str:
    """
    Uploads a file to Lark Drive and returns the file token.
    """
    if not DRIVE_FOLDER_TOKEN:
        logger.warning("DRIVE_FOLDER_TOKEN not configured. Skipping upload.")
        return None

    if isinstance(file_obj, bytes):
        file_obj = io.BytesIO(file_obj)

    # Compute file size, then reset stream position
    file_size = file_obj.seek(0, 2)
    file_obj.seek(0)

    req = UploadAllFileRequest.builder() \
        .request_body(
            UploadAllFileRequestBody.builder()
            .file_name(file_name)
            .parent_type("explorer")
            .parent_node(DRIVE_FOLDER_TOKEN)
            .size(file_size)
            .file(file_obj)
            .build()
        ).build()

    resp = client.drive.v1.file.upload_all(req)
    if not resp.success():
        logger.error(f"Failed to upload to drive: {resp.code} {resp.msg}")
        return None

    file_token = resp.data.file_token
    logger.info(f"Uploaded to drive, file_token: {file_token}")
    return file_token


def download_image_from_url(url: str) -> tuple:
    """Download image from external URL. Returns (BytesIO, filename)."""
    if not _is_safe_url(url):
        logger.warning(f"SSRF blocked in image download: {url}")
        return None, None
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "facebookexternalhit/1.1"
        })
        resp.raise_for_status()

        # Try to get filename from URL path
        path = urlparse(url).path
        basename = os.path.basename(path)
        if basename and "." in basename:
            filename = basename
        else:
            # Fallback: infer extension from Content-Type
            ct = resp.headers.get("Content-Type", "")
            ext_map = {
                "image/jpeg": ".jpg", "image/png": ".png",
                "image/gif": ".gif", "image/webp": ".webp",
            }
            ext = ext_map.get(ct.split(";")[0].strip(), ".jpg")
            filename = f"fb_image{ext}"

        return io.BytesIO(resp.content), filename
    except Exception as e:
        logger.exception(f"Failed to download image from {url}: {e}")
        return None, None


def set_file_link_sharing(file_token: str):
    """
    Sets the file's link sharing permission so anyone in the org can view it.
    """
    try:
        req = PatchPermissionPublicRequest.builder() \
            .token(file_token) \
            .type("file") \
            .request_body(
                PermissionPublicRequest.builder()
                .link_share_entity("tenant_readable")
                .build()
            ).build()

        resp = client.drive.v1.permission_public.patch(req)
        if not resp.success():
            logger.error(f"Failed to set link sharing: {resp.code} {resp.msg}")
        else:
            logger.info(f"Link sharing enabled for {file_token}")
    except Exception as e:
        logger.exception(f"Exception setting link sharing: {e}")


# Define event handler — fast path (runs in webhook thread, must return quickly)
def do_p2_im_message_receive_v1(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    event_id = data.header.event_id
    create_time = int(data.event.message.create_time) // 1000  # ms to seconds
    logger.info(f"Received message event: {event_id}, create_time: {create_time}")

    # Skip events from before bot started (stale retries after restart)
    if create_time < _bot_start_time:
        logger.info(f"Skipping stale event: {event_id} (created before bot start)")
        return

    # Atomic dedup: lock guarantees only one thread passes for a given event_id
    with _event_lock:
        if event_id in _processed_events:
            logger.info(f"Skipping duplicate event: {event_id}")
            return
        _processed_events[event_id] = True

    msg_type = data.event.message.message_type
    message_id = data.event.message.message_id
    timestamp_ms = int(data.event.message.create_time)
    sender_open_id = data.event.sender.sender_id.open_id
    content_str = data.event.message.content

    # Lightweight pre-checks before submitting to background
    if msg_type in ("image", "file"):
        try:
            content_json = json.loads(content_str)
        except Exception:
            logger.warning("Failed to parse image/file content")
            return

        if msg_type == "image":
            file_key = content_json.get("image_key", "")
        else:
            file_key = content_json.get("file_key", "")
            fname = content_json.get("file_name", "").lower()
            if not fname.split(".")[-1] in ("png", "jpg", "jpeg", "gif", "bmp", "webp", "tiff", "heic"):
                logger.info(f"Skipping non-image file: {fname}")
                return

        if not file_key:
            return

    elif msg_type == "text":
        try:
            content_json = json.loads(content_str)
            text = content_json.get("text", "")
        except Exception:
            text = content_str
        if not extract_urls(text):
            return

    else:
        return

    # Submit heavy work to background thread — webhook returns immediately
    _executor.submit(
        _process_message, msg_type, message_id, timestamp_ms,
        sender_open_id, content_str
    )


def _process_message(msg_type, message_id, timestamp_ms, sender_open_id, content_str):
    """Slow path — runs in ThreadPoolExecutor, handles download/upload/reply/save."""
    try:
        if msg_type in ("image", "file"):
            content_json = json.loads(content_str)

            if msg_type == "image":
                file_key = content_json.get("image_key", "")
            else:
                file_key = content_json.get("file_key", "")

            logger.info(f"Processing {msg_type}: {file_key}")

            resource_type = "image" if msg_type == "image" else "file"
            file_obj, file_name = download_message_resource(message_id, file_key, resource_type)
            if file_obj is None:
                return

            original_name = content_json.get("file_name", file_name)

            file_token = upload_to_drive(file_obj, original_name)
            if file_token is None:
                return

            set_file_link_sharing(file_token)

            download_url = f"https://feishu.cn/file/{file_token}"

            reply_with_card(message_id, {
                "title": "Image Saved",
                "description": "Image has been saved to Drive.",
                "url": download_url,
                "button_text": "View Image",
            })

            save_to_bitable(
                {"title": "圖片", "description": "", "url": download_url},
                timestamp_ms, sender_open_id
            )
            return

        # Text message with URLs
        try:
            content_json = json.loads(content_str)
            text = content_json.get("text", "")
        except Exception:
            text = content_str

        urls = extract_urls(text)
        card_items = []
        bitable_records = []

        for url in urls:
            logger.info(f"Processing URL: {url}")
            metadata = fetch_page_metadata(url)
            image_url = metadata.get("image_url")

            if image_url:
                # Facebook photo: download → upload to Drive
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
                    logger.error(f"Failed to send reply: {resp.code} {resp.msg}, req_id: {resp.get_log_id()}")

        for record_meta in bitable_records:
            save_to_bitable(record_meta, timestamp_ms, sender_open_id)

    except Exception as e:
        logger.exception(f"Error processing message {message_id}: {e}")
        

# Register handler
event_handler = lark.EventDispatcherHandler.builder(ENCRYPT_KEY, VERIFICATION_TOKEN) \
    .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
    .build()

@app.route("/webhook/event", methods=["POST"])
def lark_event():
    # Construct lark request from flask request
    lark_request = lark.BaseRequest.builder() \
        .uri(request.url) \
        .http_method(request.method) \
        .headers(dict(request.headers)) \
        .body(request.data) \
        .build()

    # Dispatch event
    lark_response = event_handler.do(lark_request)

    # Return flask response
    return lark_response.content, lark_response.status_code, lark_response.headers.items()

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
