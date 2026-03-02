# SSRF Protection Design

Date: 2026-03-02

## Problem

User messages containing URLs are fetched directly by `fetch_page_metadata()` without host/IP validation. If deployed in a VPC or cloud environment, an attacker could use the bot to probe internal services (e.g., `http://169.254.169.254/latest/meta-data`, `http://10.0.0.1:8080/admin`).

## Attack Surface

| Entry Point | File | Risk | Notes |
|---|---|---|---|
| `fetch_page_metadata` general path | crawler.py:287 | **High** | Any user URL is fetched directly |
| `download_image_from_url` | bot.py:281 | **Medium** | URL from proxy response, not direct user input |
| `_fetch_facebook_direct` | crawler.py:108 | Low | Gated by `_is_facebook_url()` |
| Microlink API calls | crawler.py:77,331 | None | Fixed target `api.microlink.io` |

## Approach: URL Validation with IP Resolution (Option A)

Add `_is_safe_url(url)` in `crawler.py` that:

1. Parses the URL hostname
2. If hostname is an IP literal → check directly
3. If hostname is a domain → resolve via `socket.getaddrinfo()`, check all resolved IPs
4. Reject if any resolved IP is private, loopback, link-local, or reserved (using `ipaddress` stdlib)
5. Also reject non-HTTP(S) schemes (e.g., `file://`, `ftp://`, `gopher://`)

### Where to apply

- **`fetch_page_metadata`** — before the general (non-Facebook) crawl path at line 287. The Facebook branch is already gated by `_is_facebook_url()` and uses known-safe endpoints, so it's unaffected.
- **`download_image_from_url`** — before the `requests.get()` call. Although the URL comes from proxy responses (not direct user input), defense-in-depth is warranted.

### `_is_safe_url` implementation

```python
import socket
import ipaddress

def _is_safe_url(url: str) -> bool:
    """Check URL doesn't target private/reserved networks (SSRF protection)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False

        # Resolve hostname to IP(s)
        try:
            addr = ipaddress.ip_address(hostname)
            return _is_public_ip(addr)
        except ValueError:
            pass  # Not an IP literal, resolve DNS

        addrs = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        if not addrs:
            return False
        for family, _, _, _, sockaddr in addrs:
            ip = ipaddress.ip_address(sockaddr[0])
            if not _is_public_ip(ip):
                return False
        return True
    except Exception:
        return False


def _is_public_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if the IP is a public, routable address."""
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )
```

### Error handling

When `_is_safe_url()` returns False:
- `fetch_page_metadata` returns `{"url": url, "title": "Blocked", "description": "URL targets a private or reserved network."}`
- `download_image_from_url` returns `(None, None)` with a log warning

### What this blocks

- `http://169.254.169.254/...` (cloud metadata)
- `http://127.0.0.1:*`, `http://localhost:*`
- `http://10.*`, `http://172.16-31.*`, `http://192.168.*`
- `http://[::1]`, `http://[fd00::*]`
- IP obfuscation: `0x7f000001`, `2130706433` (decimal IP), `017700000001` (octal)
- Non-HTTP schemes: `file:///etc/passwd`, `gopher://...`
- DNS pointing to private IPs (resolved before request)

### What this does NOT block

- Facebook URLs (separate code path, unaffected)
- Normal public URLs (pass validation)
- The Microlink API and CF Worker proxy calls (fixed targets, not user-controlled)

## Files Changed

- `crawler.py` — add `_is_safe_url()`, `_is_public_ip()`, apply to `fetch_page_metadata`
- `bot.py` — apply `_is_safe_url()` to `download_image_from_url`
