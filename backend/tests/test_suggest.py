"""Unit tests for suggest.py — OpenAI title suggestion logic."""

import json
import unittest
from unittest.mock import MagicMock, patch

from scrape_videos import VideoEntry
from suggest import _is_rate_limit_error, _retry_delay_from_error, suggest_better_title


def _entry(title="Great Video", product_name="Conair Fabric Shaver", asin="B001"):
    return VideoEntry(
        title=title,
        product_url=f"https://www.amazon.com/dp/{asin}",
        asin=asin,
        vendor_code="vendor:shop",
        product_name=product_name,
    )


def _mock_openai_response(reason: str, suggested_title: str) -> MagicMock:
    """Build a minimal mock that looks like an OpenAI chat completion response."""
    content = json.dumps({"reason": reason, "suggested_title": suggested_title})
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    resp = MagicMock()
    resp.choices = [choice]
    return resp


class TestSuggestBetterTitle(unittest.TestCase):
    @patch("suggest.OpenAI")
    def test_returns_reason_and_suggested_title(self, mock_openai_cls):
        mock_openai_cls.return_value.chat.completions.create.return_value = _mock_openai_response(
            "The title lacks product keywords.", "Conair Fabric Shaver Review: Does It Work?"
        )
        result = suggest_better_title(_entry(), api_key="fake-key")
        self.assertEqual(result["reason"], "The title lacks product keywords.")
        self.assertEqual(result["suggested_title"], "Conair Fabric Shaver Review: Does It Work?")

    @patch("suggest.OpenAI")
    def test_constructs_client_with_api_key(self, mock_openai_cls):
        mock_openai_cls.return_value.chat.completions.create.return_value = _mock_openai_response("r", "t")
        suggest_better_title(_entry(), api_key="my-key")
        mock_openai_cls.assert_called_once_with(api_key="my-key")

    def test_empty_api_key_returns_empty_without_calling_openai(self):
        result = suggest_better_title(_entry(), api_key="")
        self.assertEqual(result, {"reason": "", "suggested_title": ""})

    @patch("suggest.OpenAI")
    def test_strips_markdown_code_fences(self, mock_openai_cls):
        content = '```json\n{"reason": "Too vague.", "suggested_title": "Better Title"}\n```'
        message = MagicMock()
        message.content = content
        choice = MagicMock()
        choice.message = message
        resp = MagicMock()
        resp.choices = [choice]
        mock_openai_cls.return_value.chat.completions.create.return_value = resp
        result = suggest_better_title(_entry(), api_key="key")
        self.assertEqual(result["suggested_title"], "Better Title")

    @patch("suggest.OpenAI")
    def test_malformed_json_returns_empty_strings(self, mock_openai_cls):
        message = MagicMock()
        message.content = "not valid json at all"
        choice = MagicMock()
        choice.message = message
        resp = MagicMock()
        resp.choices = [choice]
        mock_openai_cls.return_value.chat.completions.create.return_value = resp
        result = suggest_better_title(_entry(), api_key="key")
        self.assertEqual(result, {"reason": "", "suggested_title": ""})

    @patch("suggest.OpenAI")
    def test_network_error_returns_empty_strings(self, mock_openai_cls):
        mock_openai_cls.return_value.chat.completions.create.side_effect = Exception("network error")
        result = suggest_better_title(_entry(), api_key="key")
        self.assertEqual(result, {"reason": "", "suggested_title": ""})

    @patch("suggest.time.sleep")
    @patch("suggest.OpenAI")
    def test_retries_on_rate_limit_then_succeeds(self, mock_openai_cls, mock_sleep):
        from openai import RateLimitError
        rate_limit_exc = RateLimitError("rate limit", response=MagicMock(headers={}), body={})
        mock_openai_cls.return_value.chat.completions.create.side_effect = [
            rate_limit_exc,
            _mock_openai_response("reason", "Better Title"),
        ]
        result = suggest_better_title(_entry(), api_key="key")
        self.assertEqual(result["suggested_title"], "Better Title")
        self.assertEqual(mock_sleep.call_count, 1)

    @patch("suggest.time.sleep")
    @patch("suggest.OpenAI")
    def test_exhausts_retries_and_returns_empty(self, mock_openai_cls, mock_sleep):
        from openai import RateLimitError
        rate_limit_exc = RateLimitError("rate limit", response=MagicMock(headers={}), body={})
        mock_openai_cls.return_value.chat.completions.create.side_effect = rate_limit_exc
        result = suggest_better_title(_entry(), api_key="key")
        self.assertEqual(result, {"reason": "", "suggested_title": ""})
        self.assertEqual(mock_sleep.call_count, 2)  # _MAX_RETRIES = 2

    @patch("suggest.OpenAI")
    def test_unknown_product_name_falls_back_gracefully(self, mock_openai_cls):
        mock_openai_cls.return_value.chat.completions.create.return_value = _mock_openai_response("r", "t")
        entry = _entry(product_name="")
        suggest_better_title(entry, api_key="key")
        call_kwargs = mock_openai_cls.return_value.chat.completions.create.call_args.kwargs
        user_msg = next(m["content"] for m in call_kwargs["messages"] if m["role"] == "user")
        self.assertIn("Unknown product", user_msg)

    @patch("suggest.OpenAI")
    def test_result_strings_are_stripped(self, mock_openai_cls):
        mock_openai_cls.return_value.chat.completions.create.return_value = _mock_openai_response(
            "  Spaces around.  ", "  Padded Title  "
        )
        result = suggest_better_title(_entry(), api_key="key")
        self.assertEqual(result["reason"], "Spaces around.")
        self.assertEqual(result["suggested_title"], "Padded Title")


class TestHelpers(unittest.TestCase):
    def test_is_rate_limit_error_detects_rate_limit_error_instance(self):
        from openai import RateLimitError
        exc = RateLimitError("rate limit", response=MagicMock(headers={}), body={})
        self.assertTrue(_is_rate_limit_error(exc))

    def test_is_rate_limit_error_detects_429_in_message(self):
        self.assertTrue(_is_rate_limit_error(Exception("HTTP 429 Too Many Requests")))

    def test_is_rate_limit_error_ignores_other_errors(self):
        self.assertFalse(_is_rate_limit_error(Exception("500 Internal Server Error")))

    def test_retry_delay_parses_retry_after_from_error_message(self):
        exc = Exception("retry-after: 20 seconds")
        self.assertEqual(_retry_delay_from_error(exc), 20.0)

    def test_retry_delay_defaults_when_not_present(self):
        from suggest import _DEFAULT_RETRY_DELAY
        self.assertEqual(_retry_delay_from_error(Exception("no delay here")), _DEFAULT_RETRY_DELAY)


if __name__ == "__main__":
    unittest.main()
