# AmznInfluencerScraper

Scrapes an Amazon influencer storefront to report which of their videos are actually surfacing on product pages — and uses OpenAI to suggest better titles for the ones that aren't.

<img width="1987" height="1126" alt="image" src="https://github.com/user-attachments/assets/fc439fa6-6d0d-4ace-82ef-4d8fe14ec7dd" />


---

## What It Does

Amazon influencer videos are only shown in the "Videos for this product" widget if Amazon's algorithm determines the video title is semantically relevant to the product listing. Many influencer videos don't make the cut.

This tool:

1. Loads any Amazon influencer storefront (e.g. `amazon.com/shop/<handle>`)
2. Extracts all videos from the Videos tab
3. Loads each product page with a real browser and checks whether the influencer's video appears in the rendered DOM
4. Streams results to the UI in real time as each product page is checked
5. For the first 10 not-shown videos, calls OpenAI to explain _why_ the title likely failed and suggest a better one

Results are cached in memory for 1 hour — repeat requests for the same URL replay instantly.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  React (Vite + Tailwind)           frontend/                    │
│  EventSource → /scrape/stream                                   │
└────────────────────────┬────────────────────────────────────────┘
                         │  Server-Sent Events (SSE)
┌────────────────────────▼────────────────────────────────────────┐
│  Flask API             backend/api.py                           │
│  GET /scrape/stream    in-memory TTL cache (1 h)                │
└────────────────────────┬────────────────────────────────────────┘
                         │  Python generator
┌────────────────────────▼────────────────────────────────────────┐
│  Scraper               backend/scrape_videos.py                 │
│  Selenium / Chrome     storefront → product pages (parallel)    │
└────────────────────────┬────────────────────────────────────────┘
                         │  API call (per not-shown video)
┌────────────────────────▼────────────────────────────────────────┐
│  Title suggestions     backend/suggest.py                       │
│  OpenAI gpt-4o-mini    reason + suggested title per video       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| Node.js | 18+ |
| Google Chrome | any recent version |
| ChromeDriver | must match your Chrome version |

---

## Setup

### 1. Clone and install Python dependencies

```bash
pip install flask selenium openai python-dotenv
```

### 2. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and add your OpenAI API key:

```
OPENAI_API_KEY=sk-proj-...
```

The key is only used to generate title suggestions for not-shown videos. The scraper works without it — suggestion cards will simply not appear.

---

## Running

You need two processes running simultaneously.

### Backend (Flask API)

```bash
python backend/api.py
```

Starts on `http://localhost:5000`. To show a Chrome window during scraping (useful for debugging):

```bash
FLASK_DEBUG=true python backend/api.py
```

### Frontend (Vite dev server)

```bash
cd frontend
npm run dev
```

Opens at `http://localhost:5173`. The dev server proxies `/scrape/stream` to the Flask backend — no CORS configuration needed.

### Build for production

```bash
cd frontend
npm run build
```

The compiled static files land in `frontend/dist/`. Serve them from Flask or any static host.

---

## Usage

1. Open `http://localhost:5173`
2. Paste an Amazon influencer storefront URL — e.g. `https://www.amazon.com/shop/techthatinterest`
3. Click **Scrape**

The UI streams live progress as each product page is checked:

- A progress bar tracks how many pages have been checked
- Each video card flips from "Checking…" to either a green **Shown on product** or red **Not shown** badge
- Stats update in real time (total / shown / not shown)
- After all pages are checked, AI title suggestions stream in for each not-shown video (amber section on the card)
- A filter bar lets you view all, shown-only, or not-shown-only cards

Submitting the same URL within an hour replays from cache instantly.

---

## API Endpoints

### `GET /health`

```json
{ "status": "ok" }
```

### `GET /scrape/stream?url=<storefront_url>&headless=true`

Streams Server-Sent Events. Each event is a JSON object with a `type` field.

| `type` | Description |
|---|---|
| `status` | Human-readable progress message (e.g. "Opening storefront page…") |
| `found` | Total video count discovered |
| `checking` | A product page check has started (`index`, `title`, `asin`) |
| `video` | A product page check finished — includes all `VideoEntry` fields |
| `done` | All pages checked — `total`, `shown`, `not_shown` |
| `suggestion` | AI title suggestion for one not-shown video — `asin`, `reason`, `suggested_title` |
| `stream_end` | Stream is complete |
| `error` | Something went wrong |

**Parameters:**

| Parameter | Default | Description |
|---|---|---|
| `url` | (required) | Amazon storefront URL (`amazon.com/shop/…`) |
| `headless` | `true` | Set to `false` to show the Chrome window |

**400 response** if `url` is not a valid Amazon storefront URL.

---

## Project Structure

```
.
├── backend/
│   ├── api.py                  # Flask API — SSE endpoint, URL validation, in-memory cache
│   ├── scrape_videos.py        # Selenium scraper — storefront + parallel product page checks
│   ├── suggest.py              # OpenAI title suggestions with retry / backoff
│   └── tests/
│       ├── test_api.py         # 31 tests — endpoints, URL validation, cache
│       ├── test_scrape_videos.py # 26 tests — HTML parsing, product page checks, stream
│       └── test_suggest.py     # 15 tests — OpenAI mock, retry logic, JSON parsing
├── frontend/
│   ├── src/
│   │   ├── App.jsx             # React app — SSE client, video cards, real-time UI
│   │   └── index.css           # Tailwind entry
│   ├── index.html              # Sets page title to AmznInfluencerScraper
│   └── package.json
└── .env                        # OPENAI_API_KEY (gitignored)
```

---

## Running Tests

```bash
python -m pytest backend/tests/ -v
```

72 tests, all unit-level with no live network or browser calls. Selenium is mocked via `unittest.mock`; the OpenAI client is mocked via `@patch("suggest.OpenAI")`.

```
backend/tests/test_api.py            31 passed
backend/tests/test_scrape_videos.py  26 passed
backend/tests/test_suggest.py        15 passed
```

---

## How the Scraper Works

**Storefront loading:** Selenium navigates to the storefront, clicks the Videos tab, waits for the spinner to disappear, then scrolls down 12 times to trigger lazy-loaded video cards. The `data-video-item-click` attributes on the cards contain JSON blobs with title, ASIN, and vendor code.

**Product page check:** For each video, Selenium loads the product page and scrolls to trigger the JS-injected video widget. It then checks whether the influencer's `vendor_code` string appears anywhere in the rendered page source. Amazon sometimes HTML-encodes it (`:` → `&colon;`), so both forms are checked.

**Why Selenium and not HTTP requests:** Amazon aggressively bot-detects plain HTTP requests. The video widget is also injected client-side after the initial HTML is served, so `requests` + BeautifulSoup would miss it even if the bot detection were bypassed.

**Caching:** The API collects all `found`, `video`, `done`, `suggestion`, and `stream_end` events during a scrape and stores them keyed by URL. Transient events (`status`, `checking`) are not cached because they're only meaningful during the live scrape. Cache writes happen _before_ the corresponding `yield` to guarantee execution even if the client disconnects immediately after the last byte.

**AI suggestions:** After the `done` event, `scrape_videos.py` takes the first 10 not-shown entries and calls `suggest.py` for each with a 2-second delay between requests. `suggest.py` uses `gpt-4o-mini` with a prompt that asks the model to explain in two sentences why the current title fails Amazon's matching algorithm and to write a replacement title under 100 characters. Rate-limit errors are retried up to twice with exponential backoff, parsing the `Retry-After` value from the error message when available.

---

## Known Limitations

- **Slow by design:** Each product page load takes several seconds because the browser must wait for JS-rendered widgets. Scraping a storefront with 30 videos takes ~5–10 minutes.
- **Single-threaded:** The Flask server runs in single-threaded mode (`threaded=False`) to avoid multiple Chrome instances competing for resources.
- **In-process cache:** The 1-hour result cache lives in the Flask process. It resets on server restart and is not shared across workers.
- **ChromeDriver must match Chrome:** If ChromeDriver and Chrome are out of sync, Selenium will fail to launch. Use `chromedriver-autoinstaller` or keep them pinned to the same version.
- **Amazon page changes:** Scraping logic depends on specific element IDs (`videoTab`, `videoTabContentContainer`, `productTitle`). Amazon UI changes may require updating selectors.
