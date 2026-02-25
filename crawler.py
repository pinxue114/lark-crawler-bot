import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, unquote

def extract_urls(text: str) -> list[str]:
    """
    Extracts all URLs from a given text string.
    """
    if not text:
        return []
    # Basic regex for extracting URLs
    url_pattern = re.compile(
        r'(?:(?:https?|ftp)://)(?:\S+(?::\S*)?@)?(?:(?:[1-9]\d?|1\d\d|2[01]\d|22[0-3])'
        r'(?:\.(?:1?\d{1,2}|2[0-4]\d|25[0-5])){2}(?:\.(?:[1-9]\d?|1\d\d|2[0-4]\d|25[0-4]))|'
        r'(?:(?:[a-z\u00a1-\uffff0-9]+-?)*[a-z\u00a1-\uffff0-9]+)(?:\.(?:[a-z\u00a1-\uffff0-9]+-?)'
        r'*[a-z\u00a1-\uffff0-9]+)*(?:\.(?:[a-z\u00a1-\uffff]{2,})))(?::\d{2,5})?(?:/[^\s]*)?',
        re.IGNORECASE
    )
    return url_pattern.findall(text)

def _is_facebook_url(url: str) -> bool:
    """Check if the URL belongs to Facebook/Meta domains."""
    try:
        host = urlparse(url).hostname or ""
        host = host.lower().removeprefix("www.")
        return host in (
            "facebook.com", "m.facebook.com", "web.facebook.com",
            "fb.com", "fb.watch",
        ) or host.endswith(".facebook.com")
    except Exception:
        return False


def _humanize(slug: str) -> str:
    """Turn a URL slug like 'john.doe' into 'John Doe'."""
    slug = unquote(slug)
    slug = re.sub(r'[._-]+', ' ', slug)
    return slug.strip().title()


_GENERIC_FB_TITLES = {
    "facebook", "facebook - log in or sign up",
    "log in to facebook", "facebook – log in or sign up",
    "log in or sign up to view",
}


def _is_generic_facebook_metadata(title: str, description: str) -> bool:
    """Detect Facebook boilerplate metadata returned by various APIs."""
    if not title:
        return True
    t = title.strip().lower()
    if t in _GENERIC_FB_TITLES:
        return True
    if t.startswith("log in") or t.startswith("sign up"):
        return True
    generic_desc_prefixes = (
        "connect with friends, family and other people you know",
        "create an account or log into facebook",
        "log into facebook to start sharing",
        "see posts, photos and more on facebook",
    )
    d = (description or "").strip().lower()
    return any(d.startswith(gd) for gd in generic_desc_prefixes)


def _fetch_facebook_via_microlink(url: str) -> dict | None:
    """Free tier, no key needed. GET https://api.microlink.io?url=..."""
    try:
        resp = requests.get("https://api.microlink.io", params={"url": url}, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != "success":
            print(f"Microlink: non-success status for {url}: {payload.get('status')}")
            return None
        data = payload.get("data") or {}
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        if _is_generic_facebook_metadata(title, description):
            print(f"Microlink: generic metadata filtered for {url}: title={title!r}")
            return None
        image_url = ""
        img = data.get("image")
        if isinstance(img, dict):
            image_url = (img.get("url") or "").strip()
        elif isinstance(img, str):
            image_url = img.strip()
        print(f"Microlink: got metadata for {url}: title={title!r}")
        result = {"url": url, "title": title, "description": description or "No description available."}
        if image_url:
            result["image_url"] = image_url
        return result
    except Exception as e:
        print(f"Microlink API error for {url}: {e}")
        return None


def _fetch_facebook_direct(url: str) -> dict | None:
    """Direct crawl with Twitterbot UA — Facebook serves full OG tags (incl. og:image) to social crawlers."""
    try:
        resp = requests.get(url, headers={"User-Agent": "Twitterbot/1.0"},
                            timeout=10, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        og_title = soup.find('meta', property='og:title')
        og_desc = soup.find('meta', property='og:description')
        title = (og_title.get('content') or "").strip() if og_title else ""
        description = (og_desc.get('content') or "").strip() if og_desc else ""
        if _is_generic_facebook_metadata(title, description):
            print(f"Direct crawl: generic metadata filtered for {url}: title={title!r}")
            return None
        og_image = soup.find('meta', property='og:image')
        image_url = (og_image.get('content') or "").strip() if og_image else ""
        print(f"Direct crawl: got metadata for {url}: title={title!r}")
        result = {"url": url, "title": title or "No Title",
                "description": description or "No description available."}
        if image_url:
            result["image_url"] = image_url
        return result
    except Exception as e:
        print(f"Direct crawl error for {url}: {e}")
        return None


def _fetch_facebook_via_api(url: str) -> dict | None:
    """Try metadata APIs for Facebook URLs. Returns first meaningful result or None."""
    return _fetch_facebook_via_microlink(url)



def _fetch_facebook_via_proxy(url: str) -> dict | None:
    """Fallback: fetch Facebook metadata via Cloudflare Worker proxy."""
    proxy_url = os.getenv("FB_PROXY_URL")
    if not proxy_url:
        print("FB proxy: FB_PROXY_URL not set, skipping")
        return None
    try:
        headers = {}
        proxy_key = os.getenv("FB_PROXY_KEY")
        if proxy_key:
            headers["Authorization"] = f"Bearer {proxy_key}"
        resp = requests.get(proxy_url, params={"url": url},
                            headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        print(f"FB proxy response for {url}: {data}")
        if "error" in data:
            return None
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        image_url = (data.get("image") or "").strip()

        # For photo URLs: proxy may return image-only (no title/description)
        # via the lookaside crawler media endpoint. Use proxy image endpoint
        # so the bot can download without needing special UA.
        if _is_generic_facebook_metadata(title, description):
            if image_url:
                # Extract media_id from lookaside URL or fbid from original URL
                from urllib.parse import parse_qs
                media_id = parse_qs(urlparse(image_url).query).get("media_id", [None])[0]
                if not media_id:
                    media_id = parse_qs(urlparse(url).query).get("fbid", [None])[0]
                if media_id:
                    proxy_image_url = f"{proxy_url.rstrip('/')}?image_fbid={media_id}"
                    print(f"FB proxy: photo image found, fbid={media_id}")
                    return {
                        "url": url,
                        "title": "Facebook Photo",
                        "description": url,
                        "image_url": proxy_image_url,
                    }
            print(f"FB proxy: generic metadata filtered for {url}: title={title!r}")
            return None

        print(f"FB proxy: got metadata for {url}: title={title!r}")
        result = {"url": url, "title": title or "No Title",
                "description": description or "No description available."}
        if image_url:
            result["image_url"] = image_url
        return result
    except Exception as e:
        print(f"FB proxy error for {url}: {e}")
        return None


def _parse_facebook_url(url: str) -> dict:
    """Parse Facebook URL structure into descriptive metadata."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = unquote(parsed.path).strip("/")
    segments = [s for s in path.split("/") if s]

    title = "Facebook Link"
    description = url

    if host == "fb.watch":
        title = "Facebook Video"
    elif not segments:
        title = "Facebook"
    elif segments[0] == "groups" and len(segments) >= 2:
        title = f"Facebook Group: {_humanize(segments[1])}"
    elif segments[0] == "events" and len(segments) >= 2:
        title = "Facebook Event"
    elif segments[0] == "watch":
        title = "Facebook Video"
    elif segments[0] == "reel" or segments[0] == "reels":
        title = "Facebook Reel"
    elif segments[0] == "marketplace":
        title = "Facebook Marketplace"
    elif segments[0] == "share":
        title = "Facebook Share Link"
    elif segments[0] == "photo" or segments[0] == "photo.php":
        title = "Facebook Photo"
    elif segments[0] == "story.php":
        title = "Facebook Story"
    elif len(segments) >= 2 and segments[1] in ("posts", "activity"):
        title = f"Post by {_humanize(segments[0])}"
    elif len(segments) >= 2 and segments[1] == "videos":
        title = f"Video by {_humanize(segments[0])}"
    elif len(segments) >= 2 and segments[1] == "photos":
        title = f"Photo by {_humanize(segments[0])}"
    elif len(segments) == 1 and not segments[0].startswith("profile.php"):
        title = f"Facebook: {_humanize(segments[0])}"

    return {"url": url, "title": title, "description": description}


def fetch_page_metadata(url: str) -> dict:
    """
    Fetches the URL and extracts its title and description using BeautifulSoup.
    """
    metadata = {
        "url": url,
        "title": "No Title",
        "description": "No description available."
    }

    # Facebook URLs: try Microlink API → direct crawl → proxy → URL structure fallback
    if _is_facebook_url(url):
        api_result = _fetch_facebook_via_api(url)
        if api_result is not None:
            result = api_result
        else:
            direct_result = _fetch_facebook_direct(url)
            if direct_result is not None:
                result = direct_result
            else:
                proxy_result = _fetch_facebook_via_proxy(url)
                if proxy_result is not None:
                    result = proxy_result
                else:
                    result = _parse_facebook_url(url)

        # Only keep image_url for photo URLs
        if "image_url" in result:
            path = urlparse(url).path.lower().strip("/")
            segments = [s for s in path.split("/") if s]
            is_photo = (
                (len(segments) >= 1 and segments[0] in ("photo", "photo.php"))
                or (len(segments) >= 2 and segments[1] == "photos")
            )
            if not is_photo:
                del result["image_url"]

        return result

    headers_list = [
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8,zh;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        },
        # Fallback: bot UA that social platforms serve OG tags to
        {"User-Agent": "facebookexternalhit/1.1"},
    ]

    last_error = None
    for headers in headers_list:
        try:
            session = requests.Session()
            session.headers.update(headers)
            response = session.get(url, timeout=10, allow_redirects=True)
            response.encoding = response.apparent_encoding
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # 1. Try extracting title
            og_title = soup.find('meta', property='og:title')
            title_tag = soup.find('title')

            if og_title and og_title.get('content'):
                metadata['title'] = og_title['content']
            elif title_tag and title_tag.string:
                metadata['title'] = title_tag.string.strip()

            # 2. Try extracting description
            og_desc = soup.find('meta', property='og:description')
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            first_p = soup.find('p')

            if og_desc and og_desc.get('content'):
                metadata['description'] = og_desc['content']
            elif meta_desc and meta_desc.get('content'):
                metadata['description'] = meta_desc['content']
            elif first_p and first_p.text:
                text = first_p.text.strip()
                if text:
                    metadata['description'] = text[:200] + ('...' if len(text) > 200 else '')

            # If we got meaningful metadata, stop trying
            if metadata['title'] != "No Title" or metadata['description'] != "No description available.":
                break

        except Exception as e:
            print(f"Error fetching metadata for {url}: {e}")
            last_error = str(e)

    # Only set error description if no attempt succeeded at all
    if last_error and metadata['title'] == "No Title" and metadata['description'] == "No description available.":
        metadata['description'] = f"Failed to fetch preview: {last_error}"

    # Last resort: try Microlink.io for pages blocked by bot protection (e.g. Cloudflare)
    if metadata['title'] == "No Title" and metadata['description'].startswith("Failed to fetch"):
        try:
            resp = requests.get("https://api.microlink.io", params={"url": url}, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("status") == "success":
                data = payload.get("data") or {}
                title = (data.get("title") or "").strip()
                description = (data.get("description") or "").strip()
                if title:
                    metadata['title'] = title
                if description:
                    metadata['description'] = description
        except Exception as e:
            print(f"Microlink fallback error for {url}: {e}")

    return metadata

if __name__ == "__main__":
    # Test script
    sample_text = "Check out this link: https://github.com and also https://larksuite.com"
    urls = extract_urls(sample_text)
    print(f"Found URLs: {urls}")
    for u in urls:
        print(fetch_page_metadata(u))

    # Facebook URL tests
    print("\n--- Facebook URL parsing ---")
    fb_urls = [
        "https://www.facebook.com/zuck/posts/123",
        "https://www.facebook.com/groups/pythonistas",
        "https://www.facebook.com/share/p/1Aoy4RUHJG/",
        "https://fb.watch/abc123/",
        "https://www.facebook.com/events/456",
        "https://m.facebook.com/story.php?id=789",
    ]
    for u in fb_urls:
        print(fetch_page_metadata(u))
