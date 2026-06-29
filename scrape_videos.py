"""
Scrapes video titles, product links, and product-page visibility from an
Amazon influencer storefront page.

Uses Selenium to render JS content, then reuses the browser session cookies
with requests for fast parallel product-page checks.

Usage:
    python3 scrape_videos.py
    python3 scrape_videos.py --url "https://www.amazon.com/shop/<handle>"
    python3 scrape_videos.py --headless false   # show the browser window
"""

import argparse
import html as html_lib
import json
import re
import time
from dataclasses import dataclass, field

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


DEFAULT_URL = (
    "https://www.amazon.com/shop/ai.creations625"
    "?ref=dp_vse_ibvc_profile"
    "&ccs_id=4dd68749-08ea-4437-a052-c5be23a5d9f8"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}


@dataclass
class VideoEntry:
    title: str
    product_url: str
    asin: str
    vendor_code: str
    shown_on_product_page: bool = field(default=False)


def build_driver(headless: bool) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument(f"user-agent={HEADERS['User-Agent']}")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(options=opts)


def extract_entries_from_html(html: str) -> list[VideoEntry]:
    """Extract title, ASIN, and vendor_code from each video card's JSON."""
    raw_jsons = re.findall(r'data-video-item-click="([^"]+)"', html)
    entries: list[VideoEntry] = []
    seen_titles: set[str] = set()

    for raw in raw_jsons:
        raw = raw.replace("&quot;", '"').replace("&amp;", "&")
        try:
            obj = json.loads(raw).get("lightboxParams", {})
        except json.JSONDecodeError:
            continue

        title = html_lib.unescape(obj.get("title", "")).strip()
        asin = obj.get("productAsin", "").strip()
        vendor_code = obj.get("vendorCode", "").strip()

        if not title or title in seen_titles:
            continue

        seen_titles.add(title)
        product_url = f"https://www.amazon.com/dp/{asin}" if asin else "N/A"
        entries.append(VideoEntry(title=title, product_url=product_url, asin=asin, vendor_code=vendor_code))

    return entries


def build_requests_session(driver: webdriver.Chrome) -> requests.Session:
    """Copy Selenium cookies into a requests session so it passes Amazon's bot checks."""
    session = requests.Session()
    for cookie in driver.get_cookies():
        session.cookies.set(cookie["name"], cookie["value"])
    return session


def check_shown_on_product_page(
    session: requests.Session, entry: VideoEntry, delay: float = 0.4
) -> bool:
    """Return True if the influencer's vendor_code appears on the product page."""
    if not entry.asin or not entry.vendor_code:
        return False
    try:
        resp = session.get(entry.product_url, headers=HEADERS, timeout=15)
        time.sleep(delay)
        # Amazon HTML-encodes the JSON, so check both plain and encoded forms
        return entry.vendor_code in resp.text or entry.vendor_code.replace(":", "&colon;") in resp.text
    except requests.RequestException:
        return False


def scrape_videos(url: str, headless: bool = True) -> list[VideoEntry]:
    driver = build_driver(headless)
    try:
        print(f"Loading: {url}")
        driver.get(url)

        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.ID, "videoTab")))
        time.sleep(2)

        # Click the Videos tab to trigger the AJAX fetch
        video_tab = driver.find_element(By.ID, "videoTab")
        driver.execute_script("arguments[0].click();", video_tab)
        print("Clicked 'Videos' tab — waiting for content...")

        try:
            wait.until(EC.invisibility_of_element_located((By.ID, "videoTabSpinner")))
        except Exception:
            pass
        time.sleep(3)

        # Scroll to lazy-load all video cards
        print("Scrolling to load all videos...")
        for _ in range(12):
            driver.execute_script("window.scrollBy(0, 800)")
            time.sleep(0.8)

        container = driver.find_element(By.ID, "videoTabContentContainer")
        inner_html = container.get_attribute("innerHTML")
        entries = extract_entries_from_html(inner_html)

        # Reuse the browser's authenticated session for product page checks
        session = build_requests_session(driver)

    finally:
        driver.quit()

    print(f"\nChecking {len(entries)} product pages for video visibility...")
    for i, entry in enumerate(entries, 1):
        entry.shown_on_product_page = check_shown_on_product_page(session, entry)
        status = "✓" if entry.shown_on_product_page else "✗"
        print(f"  [{status}] {i}/{len(entries)}: {entry.title[:60]}")

    return entries


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Amazon influencer video titles, product links, and product-page visibility"
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="Storefront URL")
    parser.add_argument(
        "--headless",
        default="true",
        choices=["true", "false"],
        help="Run browser headless (default: true)",
    )
    args = parser.parse_args()

    entries = scrape_videos(args.url, headless=args.headless == "true")

    if not entries:
        print("\nNo videos found.")
        return

    shown = [e for e in entries if e.shown_on_product_page]
    not_shown = [e for e in entries if not e.shown_on_product_page]

    print(f"\n{'='*70}")
    print(f"Results: {len(shown)} shown on product page / {len(entries)} total\n")

    print(f"--- SHOWN ON PRODUCT PAGE ({len(shown)}) ---")
    for i, entry in enumerate(shown, 1):
        print(f"  {i:>3}. {entry.title}")
        print(f"       {entry.product_url}")
        print()

    print(f"--- NOT SHOWN ON PRODUCT PAGE ({len(not_shown)}) ---")
    for i, entry in enumerate(not_shown, 1):
        print(f"  {i:>3}. {entry.title}")
        print(f"       {entry.product_url}")
        print()


if __name__ == "__main__":
    main()
