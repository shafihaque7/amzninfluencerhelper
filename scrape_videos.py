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
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Generator

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

log = logging.getLogger(__name__)

DEFAULT_URL = (
    "https://www.amazon.com/shop/ai.creations625"
    "?ref=dp_vse_ibvc_profile"
    "&ccs_id=4dd68749-08ea-4437-a052-c5be23a5d9f8"
)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Timing / scroll tuning — adjust without touching logic
_PAGE_LOAD_TIMEOUT = 20
_STOREFRONT_SCROLL_STEPS = 12
_STOREFRONT_SCROLL_PX = 800
_STOREFRONT_SCROLL_PAUSE = 0.8
_PRODUCT_SCROLL_STEPS = 8
_PRODUCT_SCROLL_PX = 600
_PRODUCT_SCROLL_PAUSE = 0.6

SseEvent = tuple[str, dict]


@dataclass
class VideoEntry:
    title: str
    product_url: str
    asin: str
    vendor_code: str
    shown_on_product_page: bool = field(default=False)
    product_name: str = field(default="")


def build_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument(f"user-agent={_USER_AGENT}")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(options=opts)


def extract_entries_from_html(html: str) -> list[VideoEntry]:
    """Parse video card JSON blobs from the storefront container's innerHTML."""
    raw_jsons = re.findall(r'data-video-item-click="([^"]+)"', html)
    entries: list[VideoEntry] = []
    seen_titles: set[str] = set()

    for raw in raw_jsons:
        raw = raw.replace("&quot;", '"').replace("&amp;", "&")
        try:
            obj = json.loads(raw).get("lightboxParams", {})
        except json.JSONDecodeError:
            log.debug("Skipping unparseable video JSON blob")
            continue

        title = html_lib.unescape(obj.get("title", "")).strip()
        asin = obj.get("productAsin", "").strip()
        vendor_code = obj.get("vendorCode", "").strip()

        if not title or title in seen_titles:
            continue

        seen_titles.add(title)
        product_url = f"https://www.amazon.com/dp/{asin}" if asin else "N/A"
        entries.append(
            VideoEntry(title=title, product_url=product_url, asin=asin, vendor_code=vendor_code)
        )

    return entries


def _load_storefront(driver: webdriver.Chrome, url: str) -> str:
    """
    Navigate to the storefront, click the Videos tab, scroll to lazy-load all
    cards, and return the innerHTML of the video container.

    Raises RuntimeError if the Videos tab is not found within the timeout.
    """
    driver.get(url)
    wait = WebDriverWait(driver, _PAGE_LOAD_TIMEOUT)

    try:
        wait.until(EC.presence_of_element_located((By.ID, "videoTab")))
    except TimeoutException as exc:
        raise RuntimeError(
            "Could not find the Videos tab. The storefront may not have videos "
            "or the page took too long to load."
        ) from exc
    time.sleep(2)

    video_tab = driver.find_element(By.ID, "videoTab")
    driver.execute_script("arguments[0].click();", video_tab)
    log.debug("Clicked Videos tab")

    try:
        wait.until(EC.invisibility_of_element_located((By.ID, "videoTabSpinner")))
    except TimeoutException:
        log.debug("videoTabSpinner did not disappear within timeout; continuing anyway")
    time.sleep(3)

    for _ in range(_STOREFRONT_SCROLL_STEPS):
        driver.execute_script(f"window.scrollBy(0, {_STOREFRONT_SCROLL_PX})")
        time.sleep(_STOREFRONT_SCROLL_PAUSE)

    container = driver.find_element(By.ID, "videoTabContentContainer")
    return container.get_attribute("innerHTML")


def check_shown_on_product_page(
    driver: webdriver.Chrome,
    entry: VideoEntry,
) -> tuple[bool, str]:
    """
    Load the product page and return (is_shown, product_name).

    is_shown is True when the influencer's vendor_code appears in the fully-
    rendered DOM (including JS-injected video widgets). Plain HTTP requests are
    insufficient: Amazon bot-detects them, and the video widget is JS-injected
    after the initial HTML is delivered.
    """
    if not entry.asin or not entry.vendor_code:
        return False, ""

    try:
        driver.get(entry.product_url)
        WebDriverWait(driver, _PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        for _ in range(_PRODUCT_SCROLL_STEPS):
            driver.execute_script(f"window.scrollBy(0, {_PRODUCT_SCROLL_PX})")
            time.sleep(_PRODUCT_SCROLL_PAUSE)

        page_source = driver.page_source

        product_name = ""
        try:
            product_name = driver.find_element(By.ID, "productTitle").text.strip()
        except NoSuchElementException:
            log.debug("productTitle element not found for ASIN %s", entry.asin)

        # Amazon HTML-encodes the JSON in some places, so check both forms
        shown = (
            entry.vendor_code in page_source
            or entry.vendor_code.replace(":", "&colon;") in page_source
        )
        return shown, product_name

    except WebDriverException as exc:
        log.warning("WebDriver error while checking ASIN %s: %s", entry.asin, exc)
        return False, ""


def scrape_videos_stream(url: str, headless: bool = True) -> Generator[SseEvent, None, None]:
    """
    Yield (event_type, payload) tuples as scraping progresses.
    Designed for consumption by the SSE endpoint in api.py.
    """
    driver = build_driver(headless)
    try:
        log.info("Scraping storefront: %s", url)
        yield "status", {"message": "Opening storefront page…"}

        try:
            inner_html = _load_storefront(driver, url)
        except RuntimeError as exc:
            yield "error", {"message": str(exc)}
            return

        entries = extract_entries_from_html(inner_html)

        if not entries:
            log.info("No video entries found")
            yield "done", {"total": 0, "shown": 0, "not_shown": 0}
            return

        log.info("Found %d video entries", len(entries))
        yield "found", {
            "total": len(entries),
            "message": f"Found {len(entries)} videos — checking each product page…",
        }

        for i, entry in enumerate(entries, 1):
            yield "checking", {
                "index": i,
                "total": len(entries),
                "title": entry.title,
                "asin": entry.asin,
            }
            entry.shown_on_product_page, entry.product_name = check_shown_on_product_page(driver, entry)
            log.debug("[%d/%d] shown=%s  %s", i, len(entries), entry.shown_on_product_page, entry.title[:60])
            yield "video", {**asdict(entry), "index": i, "total": len(entries)}

        shown = sum(1 for e in entries if e.shown_on_product_page)
        yield "done", {"total": len(entries), "shown": shown, "not_shown": len(entries) - shown}

        # Suggest better titles for the first 10 not-shown videos via Gemini
        openai_key = os.getenv("OPENAI_API_KEY", "")
        not_shown_entries = [(i + 1, e) for i, e in enumerate(entries) if not e.shown_on_product_page][:10]
        if openai_key and not_shown_entries:
            from suggest import INTER_REQUEST_DELAY, suggest_better_title
            yield "status", {"message": f"Generating title suggestions for {len(not_shown_entries)} not-shown videos…"}
            for i, (orig_idx, entry) in enumerate(not_shown_entries):
                if i > 0:
                    time.sleep(INTER_REQUEST_DELAY)
                suggestion = suggest_better_title(entry, openai_key)
                if suggestion["suggested_title"]:
                    yield "suggestion", {
                        "asin": entry.asin,
                        "index": orig_idx,
                        "reason": suggestion["reason"],
                        "suggested_title": suggestion["suggested_title"],
                    }
        yield "stream_end", {}

    except Exception as exc:
        log.exception("Unexpected error during scrape")
        yield "error", {"message": str(exc)}
    finally:
        driver.quit()


def scrape_videos(url: str, headless: bool = True) -> list[VideoEntry]:
    """Blocking version of the scraper. Returns the completed VideoEntry list."""
    driver = build_driver(headless)
    try:
        log.info("Loading storefront: %s", url)
        inner_html = _load_storefront(driver, url)
        entries = extract_entries_from_html(inner_html)

        log.info("Checking %d product pages for video visibility…", len(entries))
        for i, entry in enumerate(entries, 1):
            entry.shown_on_product_page, entry.product_name = check_shown_on_product_page(driver, entry)
            status = "✓" if entry.shown_on_product_page else "✗"
            log.info("[%s] %d/%d: %s", status, i, len(entries), entry.title[:60])
    finally:
        driver.quit()

    return entries


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

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

    print(f"\n{'=' * 70}")
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
