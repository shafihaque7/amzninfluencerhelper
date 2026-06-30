"""
Scrapes video titles, product links, and product-page visibility from an
Amazon influencer storefront page.

Uses Selenium throughout: first to load the storefront, then to load each
product page so JavaScript-rendered video widgets are fully present before
checking for the influencer's vendor_code.

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
    product_name: str = field(default="")


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


def check_shown_on_product_page(
    driver: webdriver.Chrome, entry: VideoEntry, scroll_pause: float = 0.6
) -> tuple[bool, str]:
    """
    Load the product page with Selenium (so JS-rendered video widgets are present)
    and return (shown, product_name) where shown is True if the influencer's
    vendor_code appears anywhere in the DOM.

    Plain requests won't work here for two reasons:
      1. Amazon detects bots and returns a ~5 KB stub instead of the real page.
      2. The "Videos for this product" widget is injected by JavaScript after
         the initial HTML is delivered, so it would be invisible to requests even
         on a full page load.
    """
    if not entry.asin or not entry.vendor_code:
        return False, ""

    try:
        driver.get(entry.product_url)

        # Wait until the body is present, then scroll to trigger lazy video widgets
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        for _ in range(8):
            driver.execute_script("window.scrollBy(0, 600)")
            time.sleep(scroll_pause)

        page_source = driver.page_source

        product_name = ""
        try:
            title_el = driver.find_element(By.ID, "productTitle")
            product_name = title_el.text.strip()
        except Exception:
            pass

        vendor_code = entry.vendor_code
        # Amazon HTML-encodes the JSON in some places, so check both forms
        shown = vendor_code in page_source or vendor_code.replace(":", "&colon;") in page_source
        return shown, product_name
    except Exception:
        return False, ""


def scrape_videos_stream(url: str, headless: bool = True):
    """
    Generator that yields (event_type, payload) tuples as scraping progresses.
    Designed for consumption by the SSE endpoint in api.py.
    """
    from dataclasses import asdict

    driver = build_driver(headless)
    try:
        yield "status", {"message": f"Opening storefront page…"}
        driver.get(url)

        wait = WebDriverWait(driver, 20)
        try:
            wait.until(EC.presence_of_element_located((By.ID, "videoTab")))
        except Exception:
            yield "error", {"message": "Could not find the Videos tab. The storefront may not have videos or took too long to load."}
            return
        time.sleep(2)

        yield "status", {"message": "Clicking Videos tab…"}
        video_tab = driver.find_element(By.ID, "videoTab")
        driver.execute_script("arguments[0].click();", video_tab)

        try:
            wait.until(EC.invisibility_of_element_located((By.ID, "videoTabSpinner")))
        except Exception:
            pass
        time.sleep(3)

        yield "status", {"message": "Scrolling to load all video cards…"}
        for _ in range(12):
            driver.execute_script("window.scrollBy(0, 800)")
            time.sleep(0.8)

        container = driver.find_element(By.ID, "videoTabContentContainer")
        inner_html = container.get_attribute("innerHTML")
        entries = extract_entries_from_html(inner_html)

        if not entries:
            yield "done", {"total": 0, "shown": 0, "not_shown": 0}
            return

        yield "found", {"total": len(entries), "message": f"Found {len(entries)} videos — checking each product page…"}

        for i, entry in enumerate(entries, 1):
            yield "checking", {
                "index": i,
                "total": len(entries),
                "title": entry.title,
                "asin": entry.asin,
            }
            entry.shown_on_product_page, entry.product_name = check_shown_on_product_page(driver, entry)
            yield "video", {**asdict(entry), "index": i, "total": len(entries)}

        shown = sum(1 for e in entries if e.shown_on_product_page)
        yield "done", {"total": len(entries), "shown": shown, "not_shown": len(entries) - shown}

    except Exception as exc:
        yield "error", {"message": str(exc)}
    finally:
        driver.quit()


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

        # Product page checks happen inside the try block so the driver (and its
        # authenticated session) stays alive. The driver quit used to happen before
        # these checks, which meant cookies were never actually reused.
        print(f"\nChecking {len(entries)} product pages for video visibility...")
        for i, entry in enumerate(entries, 1):
            entry.shown_on_product_page, entry.product_name = check_shown_on_product_page(driver, entry)
            status = "✓" if entry.shown_on_product_page else "✗"
            print(f"  [{status}] {i}/{len(entries)}: {entry.title[:60]}")

    finally:
        driver.quit()

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
