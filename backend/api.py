"""
Flask API for the Amazon influencer storefront video scraper.

Endpoints:
    GET  /scrape/stream?url=<storefront_url>&headless=true  — SSE stream
    GET  /suggest/stream?url=<storefront_url>&asin=<asin>&title=<title>&product_name=<name>
    GET  /health
"""

import json
import logging
import os
import time
from urllib.parse import urlparse

# Load .env so GEMINI_API_KEY is available without a shell export
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass  # dotenv is optional; fall back to process env

from flask import Flask, Response, jsonify, request, stream_with_context

from scrape_videos import DEFAULT_URL, scrape_videos_stream

log = logging.getLogger(__name__)
app = Flask(__name__)

_ALLOWED_HOSTS = {"www.amazon.com", "amazon.com"}

# ─── in-memory result cache ───────────────────────────────────────────────────

_CACHE_TTL = 3600  # 1 hour

# Only cache these event types — transient progress events (status, checking)
# are not useful to replay.
_CACHEABLE_EVENTS = {"found", "video", "done", "suggestion", "stream_end"}

# url -> (stored_at_timestamp, events)
_cache: dict[str, tuple[float, list[tuple[str, dict]]]] = {}


def _cache_get(url: str) -> list[tuple[str, dict]] | None:
    """Return cached events for url if they exist and are under an hour old."""
    entry = _cache.get(url)
    if entry and time.time() - entry[0] < _CACHE_TTL:
        return entry[1]
    _cache.pop(url, None)
    return None


def _cache_set(url: str, events: list[tuple[str, dict]]) -> None:
    _cache[url] = (time.time(), events)


def _cache_age_minutes(url: str) -> int | None:
    """Return how many minutes ago the cache entry was stored, or None."""
    entry = _cache.get(url)
    if entry:
        return int((time.time() - entry[0]) / 60)
    return None


def _cache_append_suggestion(url: str, suggestion_event: tuple[str, dict]) -> None:
    """Insert a suggestion event into an existing cache entry (before stream_end)."""
    entry = _cache.get(url)
    if not entry:
        return
    timestamp, events = entry
    updated = []
    inserted = False
    for ev in events:
        if ev[0] == "stream_end" and not inserted:
            updated.append(suggestion_event)
            inserted = True
        updated.append(ev)
    if not inserted:
        updated.append(suggestion_event)
    _cache[url] = (timestamp, updated)


# ─── URL validation ───────────────────────────────────────────────────────────

def _is_valid_storefront_url(url: str) -> bool:
    """Return True only for well-formed Amazon storefront URLs."""
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme in {"http", "https"}
            and parsed.netloc in _ALLOWED_HOSTS
            and parsed.path.startswith("/shop/")
        )
    except Exception:
        return False


# ─── endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/scrape/stream")
def scrape_stream():
    url = request.args.get("url", DEFAULT_URL)
    headless = request.args.get("headless", "true").lower() != "false"

    if not _is_valid_storefront_url(url):
        return (
            jsonify({"error": "url must be an Amazon storefront URL (amazon.com/shop/…)"}),
            400,
        )

    cached_events = _cache_get(url)

    def generate():
        if cached_events is not None:
            age = _cache_age_minutes(url)
            age_str = f"{age} minute{'s' if age != 1 else ''} ago" if age is not None else "recently"
            log.info("Cache hit for url=%s (stored %s)", url, age_str)
            yield f"data: {json.dumps({'type': 'status', 'message': f'Returning cached results ({age_str})…'})}\n\n"
            for event_type, data in cached_events:
                yield f"data: {json.dumps({'type': event_type, **data})}\n\n"
            return

        log.info("Cache miss — scraping url=%s headless=%s", url, headless)
        collected: list[tuple[str, dict]] = []
        got_done = False
        try:
            for event_type, data in scrape_videos_stream(url, headless=headless):
                # Collect and cache BEFORE yielding so these run in the same
                # next() call as the yield — the test client (and stream_with_context)
                # may call close() after the last byte is sent, skipping post-yield code.
                if event_type in _CACHEABLE_EVENTS:
                    collected.append((event_type, data))
                if event_type == "done":
                    got_done = True
                elif event_type == "stream_end" and got_done:
                    _cache_set(url, collected)
                    log.info("Cached %d events for url=%s (TTL %ds)", len(collected), url, _CACHE_TTL)
                yield f"data: {json.dumps({'type': event_type, **data})}\n\n"
        except Exception as exc:
            log.exception("Stream generation error")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/suggest/stream")
def suggest_stream():
    """Generate an AI title suggestion for a single not-shown video on demand.

    Query params:
        asin         — required
        title        — video title
        product_name — product name from the product page
        url          — storefront URL (used to update the cache if present)
    """
    asin = request.args.get("asin", "").strip()
    title = request.args.get("title", "").strip()
    product_name = request.args.get("product_name", "").strip()
    storefront_url = request.args.get("url", "").strip()

    if not asin:
        return jsonify({"error": "asin is required"}), 400

    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        return jsonify({"error": "OPENAI_API_KEY not configured"}), 500

    def generate():
        from scrape_videos import VideoEntry
        from suggest import suggest_better_title

        entry = VideoEntry(
            title=title,
            product_url=f"https://www.amazon.com/dp/{asin}",
            asin=asin,
            vendor_code="",
            product_name=product_name,
        )
        suggestion = suggest_better_title(entry, openai_key)

        if suggestion["suggested_title"]:
            event_data = {
                "asin": asin,
                "reason": suggestion["reason"],
                "suggested_title": suggestion["suggested_title"],
            }
            if storefront_url and _is_valid_storefront_url(storefront_url):
                _cache_append_suggestion(storefront_url, ("suggestion", event_data))
            yield f"data: {json.dumps({'type': 'suggestion', **event_data})}\n\n"

        yield f"data: {json.dumps({'type': 'suggest_end', 'asin': asin})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        port=int(os.getenv("PORT", "5000")),
        threaded=False,
        use_reloader=False,
    )
