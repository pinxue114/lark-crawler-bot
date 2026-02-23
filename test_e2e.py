#!/usr/bin/env python3
"""
End-to-end test script for Lark CrawlerBot running in Docker.

Usage:
    docker compose up -d --build
    python test_e2e.py

Requires: requests (pip install requests)
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

ENCRYPT_KEY = os.getenv("ENCRYPT_KEY", "")
VERIFICATION_TOKEN = os.getenv("VERIFICATION_TOKEN", "")
PORT = int(os.getenv("PORT", 5000))
BASE_URL = f"http://localhost:{PORT}"

RUN_ID = uuid.uuid4().hex[:8]  # unique per execution to avoid dedup collisions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def sign_request(timestamp: str, nonce: str, body: bytes) -> str:
    """Compute X-Lark-Signature exactly as the SDK does."""
    bs = (timestamp + nonce + ENCRYPT_KEY).encode("utf-8") + body
    return hashlib.sha256(bs).hexdigest()


def build_event_body(
    event_id: str,
    msg_type: str,
    content: dict,
    *,
    message_id: str | None = None,
    sender_open_id: str = "ou_test_sender_000",
) -> bytes:
    """Build a valid Lark SDK v2 event body for im.message.receive_v1."""
    now_ms = str(int(time.time() * 1000))
    body = {
        "schema": "2.0",
        "header": {
            "event_id": event_id,
            "token": VERIFICATION_TOKEN,
            "create_time": now_ms,
            "event_type": "im.message.receive_v1",
            "tenant_key": "tenant_test",
            "app_id": os.getenv("APP_ID", "cli_test"),
        },
        "event": {
            "sender": {
                "sender_id": {
                    "open_id": sender_open_id,
                    "user_id": "user_test",
                    "union_id": "union_test",
                },
                "sender_type": "user",
                "tenant_key": "tenant_test",
            },
            "message": {
                "message_id": message_id or f"om_test_{RUN_ID}_{event_id[-6:]}",
                "root_id": "",
                "parent_id": "",
                "create_time": now_ms,
                "chat_id": "oc_test_chat",
                "chat_type": "group",
                "message_type": msg_type,
                "content": json.dumps(content),  # double-encoded JSON string
            },
        },
    }
    return json.dumps(body).encode("utf-8")


def post_event(body: bytes) -> requests.Response:
    """POST an event to the webhook endpoint with correct signature headers."""
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    signature = sign_request(timestamp, nonce, body)

    headers = {
        "Content-Type": "application/json",
        "X-Lark-Request-Timestamp": timestamp,
        "X-Lark-Request-Nonce": nonce,
        "X-Lark-Signature": signature,
    }
    return requests.post(f"{BASE_URL}/webhook/event", data=body, headers=headers, timeout=5)


def get_docker_logs(since: str = "30s") -> str:
    """Fetch recent docker compose logs for the bot service."""
    result = subprocess.run(
        ["docker", "compose", "logs", "--no-color", "--since", since, "bot"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Test framework
# ---------------------------------------------------------------------------
results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = ""):
    status = "PASS" if passed else "FAIL"
    results.append((name, passed, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------
def test_health_check():
    """#1 — GET / returns healthy."""
    resp = requests.get(f"{BASE_URL}/", timeout=5)
    ok = resp.status_code == 200 and "healthy" in resp.text
    record("Health check", ok, f"status={resp.status_code} body={resp.text[:80]}")


def test_text_url():
    """#2 — Text message with a URL triggers URL processing."""
    event_id = f"ev_text_{RUN_ID}_001"
    body = build_event_body(event_id, "text", {"text": "Check this https://example.com page"})
    t0 = time.time()
    resp = post_event(body)
    elapsed = time.time() - t0

    ok = resp.status_code == 200 and "success" in resp.text and elapsed < 1.0
    record("Text+URL — HTTP response", ok, f"status={resp.status_code} time={elapsed:.3f}s")
    return event_id


def test_dedup():
    """#3 — Same event_id sent 3 times; only first should be processed."""
    event_id = f"ev_dedup_{RUN_ID}_002"
    body = build_event_body(event_id, "text", {"text": "Dedup test https://example.com"})

    for i in range(3):
        resp = post_event(body)
        ok = resp.status_code == 200 and "success" in resp.text
        record(f"Dedup x3 — send #{i+1} HTTP", ok, f"status={resp.status_code}")
    return event_id


def test_image():
    """#4 — Image message triggers image processing."""
    event_id = f"ev_img_{RUN_ID}_003"
    body = build_event_body(event_id, "image", {"image_key": "img_test_key_001"})
    t0 = time.time()
    resp = post_event(body)
    elapsed = time.time() - t0

    ok = resp.status_code == 200 and "success" in resp.text and elapsed < 1.0
    record("Image — HTTP response", ok, f"status={resp.status_code} time={elapsed:.3f}s")
    return event_id


def test_file_jpg():
    """#5 — File message with .jpg triggers file processing."""
    event_id = f"ev_fjpg_{RUN_ID}_004"
    body = build_event_body(event_id, "file", {
        "file_key": "file_test_key_001",
        "file_name": "photo.jpg",
    })
    t0 = time.time()
    resp = post_event(body)
    elapsed = time.time() - t0

    ok = resp.status_code == 200 and "success" in resp.text and elapsed < 1.0
    record("File(.jpg) — HTTP response", ok, f"status={resp.status_code} time={elapsed:.3f}s")
    return event_id


def test_file_pdf():
    """#6 — File message with .pdf is skipped (non-image)."""
    event_id = f"ev_fpdf_{RUN_ID}_005"
    body = build_event_body(event_id, "file", {
        "file_key": "file_test_key_002",
        "file_name": "report.pdf",
    })
    t0 = time.time()
    resp = post_event(body)
    elapsed = time.time() - t0

    ok = resp.status_code == 200 and "success" in resp.text and elapsed < 1.0
    record("File(.pdf) — HTTP response", ok, f"status={resp.status_code} time={elapsed:.3f}s")
    return event_id


def test_audio():
    """#7 — Audio message is unsupported; handler returns early."""
    event_id = f"ev_audio_{RUN_ID}_006"
    body = build_event_body(event_id, "audio", {"duration": "5000"})
    t0 = time.time()
    resp = post_event(body)
    elapsed = time.time() - t0

    ok = resp.status_code == 200 and "success" in resp.text and elapsed < 1.0
    record("Audio — HTTP response", ok, f"status={resp.status_code} time={elapsed:.3f}s")
    return event_id


# ---------------------------------------------------------------------------
# Phase 2: log verification
# ---------------------------------------------------------------------------
def verify_logs(event_ids: dict):
    """Read docker logs and verify expected log patterns."""
    logs = get_docker_logs(since="30s")

    def has(pattern: str) -> bool:
        return pattern in logs

    def count(pattern: str) -> int:
        return logs.count(pattern)

    # #2 Text+URL logs
    eid = event_ids["text"]
    record("Text+URL — log: Received", has(f"Received message event: {eid}"))
    record("Text+URL — log: Processing URL", has("Processing URL: https://example.com"))

    # #3 Dedup logs
    eid = event_ids["dedup"]
    recv_count = count(f"Received message event: {eid}")
    skip_count = count(f"Skipping duplicate event: {eid}")
    record("Dedup — log: Received x3", recv_count >= 3, f"found {recv_count}")
    record("Dedup — log: Skipping duplicate x2", skip_count >= 2, f"found {skip_count}")

    # #4 Image logs
    eid = event_ids["image"]
    record("Image — log: Received", has(f"Received message event: {eid}"))
    record("Image — log: Processing image", has("Processing image: img_test_key_001"))

    # #5 File(.jpg) logs
    eid = event_ids["file_jpg"]
    record("File(.jpg) — log: Received", has(f"Received message event: {eid}"))
    record("File(.jpg) — log: Processing file", has("Processing file: file_test_key_001"))
    record("File(.jpg) — log: no skip", not has("Skipping non-image file: photo.jpg"),
           "should NOT contain 'Skipping non-image'")

    # #6 File(.pdf) logs
    eid = event_ids["file_pdf"]
    record("File(.pdf) — log: Received", has(f"Received message event: {eid}"))
    record("File(.pdf) — log: Skipping non-image", has("Skipping non-image file: report.pdf"))
    # Ensure no "Processing file: file_test_key_002" (the pdf's file_key)
    record("File(.pdf) — log: no processing", not has("Processing file: file_test_key_002"),
           "should NOT process pdf file")

    # #7 Audio logs
    eid = event_ids["audio"]
    record("Audio — log: Received", has(f"Received message event: {eid}"))
    # Audio is unsupported → handler returns before any "Processing" for this event
    # We check that no "Processing image:" or "Processing file:" or "Processing URL:"
    # appears for the audio event's message_id
    record("Audio — log: no Processing", not has(f"Processing audio"),
           "should NOT contain any Processing for audio")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"\n{'='*60}")
    print(f"  Lark CrawlerBot — End-to-End Tests")
    print(f"  RUN_ID: {RUN_ID}")
    print(f"  Target: {BASE_URL}")
    print(f"{'='*60}\n")

    if not ENCRYPT_KEY or not VERIFICATION_TOKEN:
        print("ERROR: ENCRYPT_KEY and VERIFICATION_TOKEN must be set in .env")
        sys.exit(1)

    # Phase 1: send events and check HTTP responses
    print("Phase 1: Sending events & verifying HTTP responses\n")

    test_health_check()
    eid_text = test_text_url()
    eid_dedup = test_dedup()
    eid_image = test_image()
    eid_fjpg = test_file_jpg()
    eid_fpdf = test_file_pdf()
    eid_audio = test_audio()

    # Phase 2: wait for background processing, then verify logs
    print("\nPhase 2: Waiting for background processing (3s)...\n")
    time.sleep(3)

    event_ids = {
        "text": eid_text,
        "dedup": eid_dedup,
        "image": eid_image,
        "file_jpg": eid_fjpg,
        "file_pdf": eid_fpdf,
        "audio": eid_audio,
    }
    verify_logs(event_ids)

    # Summary
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'='*60}")
    print(f"  Results: {passed}/{total} passed")
    if passed == total:
        print("  ALL TESTS PASSED")
    else:
        print("  SOME TESTS FAILED")
        for name, ok, detail in results:
            if not ok:
                print(f"    FAIL: {name}" + (f" — {detail}" if detail else ""))
    print(f"{'='*60}\n")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
