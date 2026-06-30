"""
OpenAI-powered title suggestions for Amazon influencer videos that are not
appearing on product pages.
"""

import json
import logging
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scrape_videos import VideoEntry

from openai import OpenAI, RateLimitError

log = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"

# Free / low-rate-limit tier: space requests out to avoid 429s.
INTER_REQUEST_DELAY = 2

# How long to wait after a 429 if the API doesn't supply a Retry-After header.
_DEFAULT_RETRY_DELAY = 30
_MAX_RETRIES = 2

# Prompt engineered to surface the specific mismatch between an influencer
# video title and Amazon's product-page matching algorithm.
_SYSTEM_PROMPT = (
    "You are an Amazon influencer video optimization specialist. "
    "Amazon's algorithm matches influencer videos to product pages using "
    "semantic relevance between the video title and the product listing. "
    "Videos fail to surface when their titles are too generic, "
    "entertainment-focused, or lack the specific product keywords Amazon uses "
    "for matching. Titles that clearly signal 'this is a review or demo of "
    "THIS specific product' consistently outperform vague or clickbait-style titles."
)

_USER_PROMPT = """\
A creator's video is NOT appearing in the "Videos for this product" section \
on an Amazon product page.

Video details:
- Current title: {title}
- Product name: {product_name}
- ASIN: {asin}

1. In exactly 2 sentences, explain WHY the current title likely fails Amazon's \
matching algorithm. Focus on keyword gaps, specificity, and content-signal issues.
2. Write a replacement title (under 100 characters) that: names or closely \
references the product, signals review/demo intent, and uses search-friendly language.

Reply ONLY with valid JSON — no markdown, no code fences:
{{"reason": "<2-sentence explanation>", "suggested_title": "<improved title>"}}"""


def _retry_delay_from_error(error: Exception) -> float:
    """Parse the suggested retry delay (seconds) from a rate-limit error."""
    # OpenAI errors may carry a Retry-After header value in the message
    match = re.search(r"retry.after[^\d]*(\d+)", str(error), re.IGNORECASE)
    return float(match.group(1)) if match else _DEFAULT_RETRY_DELAY


def _is_rate_limit_error(error: Exception) -> bool:
    return isinstance(error, RateLimitError) or "429" in str(error) or "rate_limit" in str(error).lower()


def suggest_better_title(entry: "VideoEntry", api_key: str) -> dict[str, str]:
    """
    Call OpenAI to suggest a better title for a not-shown video.

    Retries up to _MAX_RETRIES times on rate-limit errors, waiting the delay
    from the response headers (or _DEFAULT_RETRY_DELAY) before each retry.

    Returns a dict with 'reason' and 'suggested_title'. On any unrecoverable
    failure both values are empty strings.
    """
    if not api_key:
        log.warning("No OpenAI API key — skipping suggestion for ASIN %s", entry.asin)
        return {"reason": "", "suggested_title": ""}

    client = OpenAI(api_key=api_key)
    user_prompt = _USER_PROMPT.format(
        title=entry.title,
        product_name=entry.product_name or "Unknown product",
        asin=entry.asin,
    )

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=300,
            )
            text = response.choices[0].message.content.strip()

            # Strip accidental markdown code fences
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            result = json.loads(text)
            return {
                "reason": result.get("reason", "").strip(),
                "suggested_title": result.get("suggested_title", "").strip(),
            }

        except json.JSONDecodeError as exc:
            log.warning("OpenAI returned non-JSON for ASIN %s: %s", entry.asin, exc)
            return {"reason": "", "suggested_title": ""}

        except Exception as exc:
            last_exc = exc
            if _is_rate_limit_error(exc) and attempt < _MAX_RETRIES:
                delay = _retry_delay_from_error(exc)
                log.warning(
                    "Rate limited for ASIN %s — waiting %.0fs before retry %d/%d",
                    entry.asin, delay, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(delay)
                continue
            break

    log.warning("OpenAI suggestion failed for ASIN %s: %s", entry.asin, last_exc)
    return {"reason": "", "suggested_title": ""}
