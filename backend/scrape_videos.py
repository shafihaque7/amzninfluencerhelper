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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from queue import Queue
from typing import Generator

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    from selenium_stealth import stealth as _apply_stealth
    _STEALTH_AVAILABLE = True
except ImportError:
    _STEALTH_AVAILABLE = False

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

# Parallel product-page checkers (each gets its own Chrome instance)
_MAX_WORKERS = 4

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
    # Required for running in Docker/containers
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-setuid-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    # Anti-bot-detection
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(f"user-agent={_USER_AGENT}")
    # Stability / rendering
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--no-first-run")
    opts.add_argument("--disable-default-apps")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=opts)
    if _STEALTH_AVAILABLE:
        _apply_stealth(
            driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )
        log.debug("selenium-stealth applied")
    return driver


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


def _load_storefront(driver: webdriver.Chrome, url: str) -> tuple[str, str]:
    """
    Navigate to the storefront, click the Videos tab, scroll to lazy-load all
    cards, and return (innerHTML of the video container, page title).

    Raises RuntimeError if the Videos tab is not found within the timeout.
    """
    driver.get(url)
    wait = WebDriverWait(driver, _PAGE_LOAD_TIMEOUT)

    log.info("Page title after load: %r", driver.title)

    try:
        wait.until(EC.presence_of_element_located((By.ID, "videoTab")))
    except TimeoutException as exc:
        log.warning("videoTab not found. Page title: %r | URL: %s", driver.title, driver.current_url)
        raise RuntimeError(
            "Could not find the Videos tab. The storefront may not have videos "
            "or the page took too long to load."
        ) from exc
    time.sleep(2)

    video_tab = driver.find_element(By.ID, "videoTab")
    driver.execute_script("arguments[0].click();", video_tab)
    log.info("Clicked Videos tab")

    try:
        wait.until(EC.invisibility_of_element_located((By.ID, "videoTabSpinner")))
    except TimeoutException:
        log.info("videoTabSpinner did not disappear within timeout; continuing anyway")
    time.sleep(5)  # extra wait for JS rendering in cloud environments

    for _ in range(_STOREFRONT_SCROLL_STEPS):
        driver.execute_script(f"window.scrollBy(0, {_STOREFRONT_SCROLL_PX})")
        time.sleep(_STOREFRONT_SCROLL_PAUSE)

    time.sleep(2)  # settle after scrolling

    container = driver.find_element(By.ID, "videoTabContentContainer")
    inner_html = container.get_attribute("innerHTML")
    page_title = driver.title
    log.info("Page title: %r | Container HTML: %d chars", page_title, len(inner_html))
    return inner_html, page_title


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

    Product-page checks run in parallel across _MAX_WORKERS Chrome instances.
    All "checking" events are emitted upfront so the UI can render all cards
    immediately; "video" events then arrive in completion order.
    """
    log.info("Scraping storefront: %s", url)
    yield "status", {"message": "Opening storefront page…"}

    storefront_driver = build_driver(headless)
    worker_drivers: list[webdriver.Chrome] = []
    entries: list[VideoEntry] = []

    try:
        try:
            inner_html, page_title = _load_storefront(storefront_driver, url)
        except RuntimeError as exc:
            yield "error", {"message": str(exc)}
            return

        yield "status", {"message": f"Storefront loaded: \"{page_title}\""}

        entries = extract_entries_from_html(inner_html)

        if not entries:
            container_len = len(inner_html)
            title_lower = page_title.lower()
            if "robot check" in title_lower or "captcha" in title_lower or "sorry" in title_lower:
                msg = (
                    f"Amazon blocked this request — CAPTCHA/bot-check detected "
                    f"(page title: \"{page_title}\"). "
                    "Cloud server IPs are routinely blocked by Amazon. "
                    "Run the scraper from your local machine instead."
                )
            elif container_len < 200:
                msg = (
                    f"The video container loaded but was empty ({container_len} chars). "
                    f"Page title: \"{page_title}\". "
                    "Amazon may be suppressing content for cloud server IPs, or the Videos tab "
                    "failed to render. Try running locally."
                )
            else:
                msg = (
                    f"No video cards found in the storefront. "
                    f"Page title: \"{page_title}\" | Container: {container_len} chars. "
                    "The page loaded but contained no video entries — "
                    "check that this storefront has a Videos tab."
                )
            yield "error", {"message": msg, "page_title": page_title, "container_html_length": container_len}
            return

        log.info("Found %d video entries", len(entries))
        yield "found", {
            "total": len(entries),
            "message": f"Found {len(entries)} videos — checking each product page…",
        }

        # Emit all checking events upfront so the UI renders all cards in pending state
        for i, entry in enumerate(entries, 1):
            yield "checking", {
                "index": i,
                "total": len(entries),
                "title": entry.title,
                "asin": entry.asin,
            }

        # Build a pool of Chrome drivers — reuse the storefront driver as worker #0
        num_workers = min(_MAX_WORKERS, len(entries))
        worker_drivers = [storefront_driver]
        driver_pool: Queue[webdriver.Chrome] = Queue()
        driver_pool.put(storefront_driver)
        for _ in range(num_workers - 1):
            d = build_driver(headless)
            worker_drivers.append(d)
            driver_pool.put(d)

        def _check_entry(entry: VideoEntry, index: int) -> tuple[int, VideoEntry, str]:
            driver = driver_pool.get()
            prod_page_title = ""
            try:
                entry.shown_on_product_page, entry.product_name = check_shown_on_product_page(driver, entry)
                prod_page_title = driver.title  # driver is still on the product page here
            finally:
                driver_pool.put(driver)
            return index, entry, prod_page_title

        first_diag_done = False

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {
                executor.submit(_check_entry, entry, i + 1): i + 1
                for i, entry in enumerate(entries)
            }
            for future in as_completed(futures):
                try:
                    index, entry, prod_page_title = future.result()
                except Exception as exc:
                    log.warning("Worker error: %s", exc)
                    continue

                # Emit a one-time diagnostic after the first result so the UI
                # shows what Amazon actually served on product pages.
                if not first_diag_done:
                    first_diag_done = True
                    vendor_preview = (entry.vendor_code or "")[:10]
                    title_lower = prod_page_title.lower()
                    if "robot check" in title_lower or "captcha" in title_lower:
                        diag = (
                            f"Product page blocked — Amazon returned a CAPTCHA "
                            f"(title: \"{prod_page_title}\"). "
                            "Video widget data will not be present; all results will show as Not Shown. "
                            "Run the scraper locally to get accurate results."
                        )
                    else:
                        diag = (
                            f"Product page loaded: \"{prod_page_title}\" | "
                            f"vendor_code ({vendor_preview}…) "
                            f"{'FOUND ✓' if entry.shown_on_product_page else 'NOT found — video widget may not be rendering on this IP'}"
                        )
                    yield "status", {"message": diag}

                log.debug("[%d/%d] shown=%s  %s", index, len(entries), entry.shown_on_product_page, entry.title[:60])
                yield "video", {**asdict(entry), "index": index, "total": len(entries)}

    except Exception as exc:
        log.exception("Unexpected error during scrape")
        yield "error", {"message": str(exc)}
        return
    finally:
        for d in (worker_drivers or [storefront_driver]):
            try:
                d.quit()
            except Exception:
                pass

    shown = sum(1 for e in entries if e.shown_on_product_page)
    yield "done", {"total": len(entries), "shown": shown, "not_shown": len(entries) - shown}

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


def scrape_videos(url: str, headless: bool = True) -> list[VideoEntry]:
    """Blocking version of the scraper. Returns the completed VideoEntry list."""
    storefront_driver = build_driver(headless)
    worker_drivers: list[webdriver.Chrome] = []
    entries: list[VideoEntry] = []

    try:
        log.info("Loading storefront: %s", url)
        inner_html = _load_storefront(storefront_driver, url)
        entries = extract_entries_from_html(inner_html)

        if entries:
            num_workers = min(_MAX_WORKERS, len(entries))
            worker_drivers = [storefront_driver]
            driver_pool: Queue[webdriver.Chrome] = Queue()
            driver_pool.put(storefront_driver)
            for _ in range(num_workers - 1):
                d = build_driver(headless)
                worker_drivers.append(d)
                driver_pool.put(d)

            def _check(entry: VideoEntry, index: int) -> None:
                d = driver_pool.get()
                try:
                    entry.shown_on_product_page, entry.product_name = check_shown_on_product_page(d, entry)
                    status = "✓" if entry.shown_on_product_page else "✗"
                    log.info("[%s] %d/%d: %s", status, index, len(entries), entry.title[:60])
                finally:
                    driver_pool.put(d)

            log.info("Checking %d product pages across %d workers…", len(entries), num_workers)
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = [executor.submit(_check, e, i + 1) for i, e in enumerate(entries)]
                for f in as_completed(futures):
                    f.result()  # surface any worker exceptions

    finally:
        for d in (worker_drivers or [storefront_driver]):
            try:
                d.quit()
            except Exception:
                pass

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
