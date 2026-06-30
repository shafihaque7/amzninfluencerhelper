"""Unit tests for api.py — Flask endpoints, URL validation, and result cache."""

import json
import unittest
from unittest.mock import patch

import api
from api import _cache, _cache_get, _cache_set, _is_valid_storefront_url, app

_VALID_URL = "https://www.amazon.com/shop/test"


class TestIsValidStorefrontUrl(unittest.TestCase):
    def test_valid_https_storefront(self):
        self.assertTrue(_is_valid_storefront_url("https://www.amazon.com/shop/myhandle"))

    def test_valid_http_storefront(self):
        self.assertTrue(_is_valid_storefront_url("http://www.amazon.com/shop/myhandle"))

    def test_valid_apex_domain(self):
        self.assertTrue(_is_valid_storefront_url("https://amazon.com/shop/myhandle"))

    def test_valid_url_with_query_string(self):
        self.assertTrue(_is_valid_storefront_url("https://www.amazon.com/shop/handle?ref=dp_vse&ccs_id=abc123"))

    def test_rejects_non_amazon_domain(self):
        self.assertFalse(_is_valid_storefront_url("https://www.evil.com/shop/test"))

    def test_rejects_non_shop_path(self):
        self.assertFalse(_is_valid_storefront_url("https://www.amazon.com/dp/B001"))

    def test_rejects_missing_scheme(self):
        self.assertFalse(_is_valid_storefront_url("www.amazon.com/shop/handle"))

    def test_rejects_empty_string(self):
        self.assertFalse(_is_valid_storefront_url(""))

    def test_rejects_ftp_scheme(self):
        self.assertFalse(_is_valid_storefront_url("ftp://www.amazon.com/shop/handle"))

    def test_rejects_amazon_subdomain_other_than_www(self):
        self.assertFalse(_is_valid_storefront_url("https://seller.amazon.com/shop/handle"))


class TestHealthEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_returns_200(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_returns_ok_status(self):
        self.assertEqual(self.client.get("/health").get_json(), {"status": "ok"})


class TestScrapeStreamEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        _cache.clear()

    def test_invalid_url_returns_400(self):
        self.assertEqual(self.client.get("/scrape/stream?url=https://evil.com/shop/x").status_code, 400)

    def test_invalid_url_returns_error_message(self):
        self.assertIn("error", self.client.get("/scrape/stream?url=https://evil.com/shop/x").get_json())

    def test_non_shop_path_returns_400(self):
        self.assertEqual(self.client.get("/scrape/stream?url=https://www.amazon.com/dp/B001").status_code, 400)

    @patch("api.scrape_videos_stream")
    def test_valid_url_returns_event_stream_content_type(self, mock_stream):
        mock_stream.return_value = iter([("done", {"total": 0, "shown": 0, "not_shown": 0})])
        resp = self.client.get(f"/scrape/stream?url={_VALID_URL}")
        self.assertIn("text/event-stream", resp.content_type)

    @patch("api.scrape_videos_stream")
    def test_valid_url_streams_sse_data(self, mock_stream):
        mock_stream.return_value = iter([("done", {"total": 0, "shown": 0, "not_shown": 0})])
        resp = self.client.get(f"/scrape/stream?url={_VALID_URL}")
        self.assertTrue(resp.data.decode().startswith("data:"))

    @patch("api.scrape_videos_stream")
    def test_each_sse_line_is_valid_json_with_type_field(self, mock_stream):
        mock_stream.return_value = iter([
            ("status", {"message": "hello"}),
            ("done", {"total": 1, "shown": 1, "not_shown": 0}),
        ])
        resp = self.client.get(f"/scrape/stream?url={_VALID_URL}")
        for line in resp.data.decode().splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[len("data:"):].strip())
                self.assertIn("type", payload)

    @patch("api.scrape_videos_stream")
    def test_headless_param_is_forwarded(self, mock_stream):
        mock_stream.return_value = iter([])
        self.client.get(f"/scrape/stream?url={_VALID_URL}&headless=false")
        _, kwargs = mock_stream.call_args
        self.assertFalse(kwargs.get("headless", True))

    @patch("api.scrape_videos_stream")
    def test_headless_defaults_to_true(self, mock_stream):
        mock_stream.return_value = iter([])
        self.client.get(f"/scrape/stream?url={_VALID_URL}")
        _, kwargs = mock_stream.call_args
        self.assertTrue(kwargs.get("headless", True))


class TestCacheFunctions(unittest.TestCase):
    def setUp(self):
        _cache.clear()

    def test_cache_miss_returns_none(self):
        self.assertIsNone(_cache_get(_VALID_URL))

    def test_cache_hit_returns_events(self):
        events = [("done", {"total": 1, "shown": 1, "not_shown": 0})]
        _cache_set(_VALID_URL, events)
        self.assertEqual(_cache_get(_VALID_URL), events)

    @patch("api.time")
    def test_expired_entry_returns_none(self, mock_time):
        mock_time.time.return_value = 0.0
        _cache_set(_VALID_URL, [("done", {})])
        mock_time.time.return_value = api._CACHE_TTL + 1
        self.assertIsNone(_cache_get(_VALID_URL))

    @patch("api.time")
    def test_expired_entry_is_evicted(self, mock_time):
        mock_time.time.return_value = 0.0
        _cache_set(_VALID_URL, [("done", {})])
        mock_time.time.return_value = api._CACHE_TTL + 1
        _cache_get(_VALID_URL)
        self.assertNotIn(_VALID_URL, _cache)

    @patch("api.time")
    def test_entry_within_ttl_is_returned(self, mock_time):
        mock_time.time.return_value = 0.0
        events = [("video", {"asin": "B001"})]
        _cache_set(_VALID_URL, events)
        mock_time.time.return_value = api._CACHE_TTL - 1
        self.assertEqual(_cache_get(_VALID_URL), events)


class TestCacheIntegration(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        _cache.clear()

    @patch("api.scrape_videos_stream")
    def test_successful_scrape_is_cached(self, mock_stream):
        mock_stream.return_value = iter([
            ("found", {"total": 1, "message": "Found 1"}),
            ("video", {"asin": "B001", "title": "T", "index": 1, "total": 1,
                       "product_url": "u", "vendor_code": "v", "shown_on_product_page": True, "product_name": ""}),
            ("done", {"total": 1, "shown": 1, "not_shown": 0}),
            ("stream_end", {}),
        ])
        resp = self.client.get(f"/scrape/stream?url={_VALID_URL}")
        _ = resp.data  # ensure generator is fully drained
        self.assertIn(_VALID_URL, _cache)

    @patch("api.scrape_videos_stream")
    def test_cache_hit_does_not_call_scraper(self, mock_stream):
        events = [
            ("done", {"total": 1, "shown": 1, "not_shown": 0}),
            ("stream_end", {}),
        ]
        _cache_set(_VALID_URL, events)
        self.client.get(f"/scrape/stream?url={_VALID_URL}")
        mock_stream.assert_not_called()

    @patch("api.scrape_videos_stream")
    def test_cache_hit_replays_cached_events(self, mock_stream):
        events = [("done", {"total": 5, "shown": 3, "not_shown": 2})]
        _cache_set(_VALID_URL, events)
        resp = self.client.get(f"/scrape/stream?url={_VALID_URL}")
        body = resp.data.decode()
        payloads = [json.loads(line[5:].strip()) for line in body.splitlines() if line.startswith("data:")]
        done = next(p for p in payloads if p["type"] == "done")
        self.assertEqual(done["total"], 5)

    @patch("api.scrape_videos_stream")
    def test_cache_hit_includes_status_message(self, mock_stream):
        _cache_set(_VALID_URL, [("done", {"total": 0, "shown": 0, "not_shown": 0})])
        resp = self.client.get(f"/scrape/stream?url={_VALID_URL}")
        body = resp.data.decode()
        payloads = [json.loads(line[5:].strip()) for line in body.splitlines() if line.startswith("data:")]
        status = next((p for p in payloads if p["type"] == "status"), None)
        self.assertIsNotNone(status)
        self.assertIn("cached", status["message"].lower())

    @patch("api.scrape_videos_stream")
    def test_error_stream_is_not_cached(self, mock_stream):
        mock_stream.return_value = iter([
            ("error", {"message": "something went wrong"}),
        ])
        resp = self.client.get(f"/scrape/stream?url={_VALID_URL}")
        _ = resp.data
        self.assertNotIn(_VALID_URL, _cache)

    @patch("api.scrape_videos_stream")
    def test_transient_events_are_not_cached(self, mock_stream):
        mock_stream.return_value = iter([
            ("status", {"message": "Opening…"}),
            ("checking", {"index": 1, "total": 1, "title": "T", "asin": "B001"}),
            ("done", {"total": 1, "shown": 0, "not_shown": 1}),
            ("stream_end", {}),
        ])
        resp = self.client.get(f"/scrape/stream?url={_VALID_URL}")
        _ = resp.data  # ensure generator is fully drained
        _, cached_events = _cache[_VALID_URL]
        event_types = {t for t, _ in cached_events}
        self.assertNotIn("status", event_types)
        self.assertNotIn("checking", event_types)
        self.assertIn("done", event_types)


if __name__ == "__main__":
    unittest.main()
