import re
import requests
from bs4 import BeautifulSoup

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

def fetch_page_metadata(url: str) -> dict:
    """
    Fetches the URL and extracts its title and description using BeautifulSoup.
    """
    metadata = {
        "url": url,
        "title": "No Title",
        "description": "No description available."
    }
    
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

    return metadata

if __name__ == "__main__":
    # Test script
    sample_text = "Check out this link: https://github.com and also https://larksuite.com"
    urls = extract_urls(sample_text)
    print(f"Found URLs: {urls}")
    for u in urls:
        print(fetch_page_metadata(u))
