"""
Flask API for the Amazon influencer storefront video scraper.

Endpoints:
    GET  /scrape/stream?url=<storefront_url>&headless=true  — SSE stream (preferred)
    GET  /health
"""

import json

from flask import Flask, Response, jsonify, request, stream_with_context

from scrape_videos import DEFAULT_URL, scrape_videos_stream

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/scrape/stream")
def scrape_stream():
    url = request.args.get("url", DEFAULT_URL)
    headless = request.args.get("headless", "true").lower() != "false"

    def generate():
        try:
            for event_type, data in scrape_videos_stream(url, headless=headless):
                payload = json.dumps({"type": event_type, **data})
                yield f"data: {payload}\n\n"
        except Exception as exc:
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


if __name__ == "__main__":
    # threaded=False keeps Selenium in the main thread; use_reloader=False
    # prevents the reloader from spawning a second Chrome process on startup.
    app.run(debug=True, port=5000, threaded=False, use_reloader=False)
