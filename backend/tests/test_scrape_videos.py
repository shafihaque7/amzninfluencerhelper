"""Unit tests for scrape_videos.py — pure functions and mocked Selenium paths."""

import json
import unittest
from dataclasses import asdict
from unittest.mock import MagicMock, patch

from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException

from scrape_videos import (
    VideoEntry,
    _load_storefront,
    check_shown_on_product_page,
    extract_entries_from_html,
    scrape_videos_stream,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _make_video_html(title: str, asin: str, vendor_code: str) -> str:
    """Build a minimal data-video-item-click HTML fragment with correct encoding.

    Ampersands must be escaped before quotes so that the resulting &quot; tokens
    are not themselves double-escaped to &amp;quot;.
    """
    payload = json.dumps(
        {"lightboxParams": {"title": title, "productAsin": asin, "vendorCode": vendor_code}}
    )
    # Order matters: escape & first, then "
    encoded = payload.replace("&", "&amp;").replace('"', "&quot;")
    return f'<div data-video-item-click="{encoded}"></div>'


# ─── extract_entries_from_html ────────────────────────────────────────────────

class TestExtractEntriesFromHtml(unittest.TestCase):
    def test_single_valid_entry(self):
        html = _make_video_html("Great Headphones Review", "B01ABCDEFG", "vendor:shop")
        entries = extract_entries_from_html(html)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e.title, "Great Headphones Review")
        self.assertEqual(e.asin, "B01ABCDEFG")
        self.assertEqual(e.vendor_code, "vendor:shop")
        self.assertEqual(e.product_url, "https://www.amazon.com/dp/B01ABCDEFG")

    def test_multiple_unique_entries(self):
        html = (
            _make_video_html("Product A", "B00000001", "vendor:shop")
            + _make_video_html("Product B", "B00000002", "vendor:shop")
        )
        self.assertEqual(len(extract_entries_from_html(html)), 2)

    def test_deduplicates_by_title(self):
        html = (
            _make_video_html("Same Title", "B00000001", "vendor:shop")
            + _make_video_html("Same Title", "B00000002", "vendor:shop")
        )
        entries = extract_entries_from_html(html)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].asin, "B00000001")

    def test_skips_entry_without_title(self):
        html = _make_video_html("", "B01ABCDEFG", "vendor:shop")
        self.assertEqual(extract_entries_from_html(html), [])

    def test_empty_asin_produces_na_url(self):
        html = _make_video_html("Some Title", "", "vendor:shop")
        self.assertEqual(extract_entries_from_html(html)[0].product_url, "N/A")

    def test_html_entities_in_title_are_unescaped(self):
        payload = json.dumps(
            {"lightboxParams": {"title": "Smart &amp; Stylish Watch", "productAsin": "B001", "vendorCode": "v:s"}}
        )
        encoded = payload.replace("&", "&amp;").replace('"', "&quot;")
        html = f'<div data-video-item-click="{encoded}"></div>'
        self.assertEqual(extract_entries_from_html(html)[0].title, "Smart & Stylish Watch")

    def test_malformed_json_is_skipped(self):
        html = '<div data-video-item-click="not-valid-json"></div>'
        self.assertEqual(extract_entries_from_html(html), [])

    def test_empty_html_returns_empty_list(self):
        self.assertEqual(extract_entries_from_html(""), [])

    def test_default_field_values(self):
        entry = extract_entries_from_html(_make_video_html("Title", "B001", "v:s"))[0]
        self.assertFalse(entry.shown_on_product_page)
        self.assertEqual(entry.product_name, "")

    def test_missing_lightbox_params_key_skips_entry(self):
        payload = json.dumps({"otherKey": {}})
        encoded = payload.replace("&", "&amp;").replace('"', "&quot;")
        html = f'<div data-video-item-click="{encoded}"></div>'
        self.assertEqual(extract_entries_from_html(html), [])


# ─── check_shown_on_product_page ─────────────────────────────────────────────

class TestCheckShownOnProductPage(unittest.TestCase):
    def _entry(self, asin="B001", vendor_code="tech:shop") -> VideoEntry:
        return VideoEntry(
            title="T",
            product_url=f"https://www.amazon.com/dp/{asin}",
            asin=asin,
            vendor_code=vendor_code,
        )

    def test_returns_false_empty_when_no_asin(self):
        entry = self._entry(asin="")
        shown, name = check_shown_on_product_page(MagicMock(), entry)
        self.assertFalse(shown)
        self.assertEqual(name, "")

    def test_returns_false_empty_when_no_vendor_code(self):
        entry = self._entry(vendor_code="")
        shown, name = check_shown_on_product_page(MagicMock(), entry)
        self.assertFalse(shown)
        self.assertEqual(name, "")

    @patch("scrape_videos.time.sleep")
    @patch("scrape_videos.WebDriverWait")
    def test_vendor_code_found_in_page_source(self, mock_wait_cls, _sleep):
        mock_wait_cls.return_value.until.return_value = None
        driver = MagicMock()
        driver.page_source = "...tech:shop..."
        title_el = MagicMock()
        title_el.text = "Fancy Product"
        driver.find_element.return_value = title_el

        shown, name = check_shown_on_product_page(driver, self._entry())
        self.assertTrue(shown)
        self.assertEqual(name, "Fancy Product")

    @patch("scrape_videos.time.sleep")
    @patch("scrape_videos.WebDriverWait")
    def test_html_encoded_vendor_code_is_also_detected(self, mock_wait_cls, _sleep):
        mock_wait_cls.return_value.until.return_value = None
        driver = MagicMock()
        driver.page_source = "...tech&colon;shop..."
        driver.find_element.return_value = MagicMock(text="Product")

        shown, _ = check_shown_on_product_page(driver, self._entry())
        self.assertTrue(shown)

    @patch("scrape_videos.time.sleep")
    @patch("scrape_videos.WebDriverWait")
    def test_vendor_code_absent_returns_false(self, mock_wait_cls, _sleep):
        mock_wait_cls.return_value.until.return_value = None
        driver = MagicMock()
        driver.page_source = "unrelated content"
        driver.find_element.return_value = MagicMock(text="Product")

        shown, _ = check_shown_on_product_page(driver, self._entry())
        self.assertFalse(shown)

    @patch("scrape_videos.time.sleep")
    @patch("scrape_videos.WebDriverWait")
    def test_missing_product_title_element_returns_empty_string(self, mock_wait_cls, _sleep):
        mock_wait_cls.return_value.until.return_value = None
        driver = MagicMock()
        driver.page_source = "tech:shop"
        driver.find_element.side_effect = NoSuchElementException()

        shown, name = check_shown_on_product_page(driver, self._entry())
        self.assertTrue(shown)
        self.assertEqual(name, "")

    def test_webdriver_exception_returns_false_and_empty(self):
        driver = MagicMock()
        driver.get.side_effect = WebDriverException("connection refused")
        shown, name = check_shown_on_product_page(driver, self._entry())
        self.assertFalse(shown)
        self.assertEqual(name, "")


# ─── _load_storefront ─────────────────────────────────────────────────────────

class TestLoadStorefront(unittest.TestCase):
    @patch("scrape_videos.WebDriverWait")
    @patch("scrape_videos.time.sleep")
    def test_raises_runtime_error_when_video_tab_not_found(self, _sleep, mock_wait_cls):
        mock_wait_cls.return_value.until.side_effect = TimeoutException()
        driver = MagicMock()

        with self.assertRaises(RuntimeError):
            _load_storefront(driver, "https://www.amazon.com/shop/test")

    @patch("scrape_videos.WebDriverWait")
    @patch("scrape_videos.time.sleep")
    def test_returns_inner_html_on_success(self, _sleep, mock_wait_cls):
        mock_wait_cls.return_value.until.return_value = None
        driver = MagicMock()
        container = MagicMock()
        container.get_attribute.return_value = "<div>video cards</div>"
        driver.find_element.return_value = container

        result = _load_storefront(driver, "https://www.amazon.com/shop/test")
        self.assertEqual(result[0], "<div>video cards</div>")


# ─── scrape_videos_stream ─────────────────────────────────────────────────────

class TestScrapeVideosStream(unittest.TestCase):
    @patch("scrape_videos.build_driver")
    @patch("scrape_videos._load_storefront")
    @patch("scrape_videos.check_shown_on_product_page")
    def test_full_happy_path_event_sequence(self, mock_check, mock_load, mock_build):
        mock_build.return_value = MagicMock()
        mock_load.return_value = (
            _make_video_html("Product A", "B001", "v:s")
            + _make_video_html("Product B", "B002", "v:s"),
            "Test Storefront",
        )
        mock_check.side_effect = [(True, "Product A Name"), (False, "Product B Name")]

        events = list(scrape_videos_stream("https://www.amazon.com/shop/test"))
        types = [e[0] for e in events]

        self.assertIn("status", types)
        self.assertIn("found", types)
        self.assertEqual(types.count("checking"), 2)
        self.assertEqual(types.count("video"), 2)
        self.assertIn("done", types)

        done = next(e[1] for e in events if e[0] == "done")
        self.assertEqual(done["total"], 2)
        self.assertEqual(done["shown"], 1)
        self.assertEqual(done["not_shown"], 1)

    @patch("scrape_videos.build_driver")
    @patch("scrape_videos._load_storefront")
    def test_empty_storefront_yields_error(self, mock_load, mock_build):
        mock_build.return_value = MagicMock()
        mock_load.return_value = ("", "Test Storefront")

        events = list(scrape_videos_stream("https://www.amazon.com/shop/test"))
        error_events = [e for e in events if e[0] == "error"]
        self.assertEqual(len(error_events), 1)
        self.assertIn("empty", error_events[0][1]["message"])

    @patch("scrape_videos.build_driver")
    @patch("scrape_videos._load_storefront")
    def test_storefront_load_error_yields_error_event(self, mock_load, mock_build):
        mock_build.return_value = MagicMock()
        mock_load.side_effect = RuntimeError("Videos tab not found")

        events = list(scrape_videos_stream("https://www.amazon.com/shop/test"))
        error_events = [e for e in events if e[0] == "error"]
        self.assertEqual(len(error_events), 1)
        self.assertIn("Videos tab not found", error_events[0][1]["message"])

    @patch("scrape_videos.build_driver")
    @patch("scrape_videos._load_storefront")
    @patch("scrape_videos.check_shown_on_product_page")
    def test_video_event_contains_product_name(self, mock_check, mock_load, mock_build):
        mock_build.return_value = MagicMock()
        mock_load.return_value = (_make_video_html("My Video", "B001", "v:s"), "Test Storefront")
        mock_check.return_value = (True, "Actual Product Name")

        events = list(scrape_videos_stream("https://www.amazon.com/shop/test"))
        video_event = next(e[1] for e in events if e[0] == "video")
        self.assertEqual(video_event["product_name"], "Actual Product Name")
        self.assertTrue(video_event["shown_on_product_page"])

    @patch("scrape_videos.build_driver")
    @patch("scrape_videos._load_storefront")
    def test_driver_quit_called_even_on_error(self, mock_load, mock_build):
        driver = MagicMock()
        mock_build.return_value = driver
        mock_load.side_effect = RuntimeError("boom")

        list(scrape_videos_stream("https://www.amazon.com/shop/test"))
        driver.quit.assert_called_once()


# ─── VideoEntry dataclass ─────────────────────────────────────────────────────

class TestVideoEntry(unittest.TestCase):
    def test_default_values(self):
        entry = VideoEntry(title="T", product_url="url", asin="B001", vendor_code="v:s")
        self.assertFalse(entry.shown_on_product_page)
        self.assertEqual(entry.product_name, "")

    def test_asdict_includes_all_fields(self):
        entry = VideoEntry(
            title="T", product_url="url", asin="B001",
            vendor_code="v:s", shown_on_product_page=True, product_name="Name"
        )
        d = asdict(entry)
        self.assertIn("product_name", d)
        self.assertIn("shown_on_product_page", d)
        self.assertIn("vendor_code", d)


if __name__ == "__main__":
    unittest.main()
