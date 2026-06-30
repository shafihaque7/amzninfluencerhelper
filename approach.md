# Approach

## What I built and why I picked this problem

I run an Amazon influencer storefront as a side hustle — creating product review videos and earning commissions when those videos surface in the "Videos for this product" widget on Amazon product pages. The catch: Amazon only shows a video if its title is semantically relevant to the product listing. A title like "5 Things Nobody Tells You About This Printer" won't match a product page for the Brother HL-L2350DW, even if the video is excellent. I learned this the hard way after producing dozens of videos that were never shown.

There was no tooling to tell me which videos were actually surfacing and why the others weren't. I was flying blind. This project is something I genuinely needed — and building it let me go from a problem I understood deeply to a working solution I can use.

The core output is simple: for each video on a storefront, was it shown on its product page or not? And for every video that wasn't shown, what's a better title that would be?

---

## Key decisions and tradeoffs

**Real browsers over HTTP requests.** Amazon aggressively bot-detects plain HTTP requests and injects the video widget client-side after initial HTML delivery. The only reliable way to see whether a video appears is to load the product page in a real browser, scroll to trigger lazy-loaded widgets, and inspect the fully-rendered DOM. This made Selenium unavoidable — and made the scraper inherently slow (~5 seconds per product page).

**Parallelising product page checks.** A storefront with 95 videos would take over 8 minutes sequentially. I addressed this with a `ThreadPoolExecutor` and a pool of 4 Chrome instances running product page checks in parallel, cutting wall-clock time by roughly 4×. The tradeoff is memory — 4 Chrome instances consume ~2 GB RAM — so the pool size is capped.

**Server-Sent Events over WebSockets or polling.** Results stream in over the course of several minutes. SSE is the right primitive here: unidirectional server push, no upgrade handshake, works over plain HTTP, and trivially resumable by the browser. Results are cached server-side for one hour, so returning to the same URL replays instantly without re-scraping.

**Showing the most actionable data first.** The UI prioritises the not-shown videos, since those are the ones with something to act on. AI title suggestions auto-generate for the first 10 not-shown videos immediately after the scrape completes. For storefronts with more than 10, a per-card button lets the user generate suggestions on demand, avoiding unnecessary API calls.

**Stateless by design (for now).** There's no login, no database, no accounts. Users paste a public storefront URL and get results. This was a deliberate choice — it keeps the tool simple, removes authentication complexity, and respects user privacy. The tradeoff is that results don't persist across sessions and can't be compared over time.

---

## What I intentionally left out

**The last mile.** The tool tells you what title to use and why — but it doesn't change the title for you. Doing that would require authenticating as the influencer's Amazon account, navigating the Creator Hub, and updating the video metadata programmatically. That's a meaningful amount of additional surface area: OAuth flows, session management, Amazon's (undocumented) internal APIs, and real liability if something goes wrong. For this version, the suggestion is the deliverable; applying it is a deliberate human step.

**Persistent storage and user accounts.** Everything lives in an in-process Python dict with a 1-hour TTL. There's no cross-session history, no comparison of results over time, no per-user data. Adding a database would enable trend tracking and scheduled reports, but it would also require authentication, data modelling, and privacy handling that were out of scope.


---

## What breaks first under pressure

**Scraping reliability at scale.** Amazon's selectors (`#videoTab`, `#videoTabContentContainer`, `data-video-item-click`) are undocumented and can change without notice. Storefronts with 200+ videos will push the memory ceiling of a 4-worker Chrome pool. And Amazon's bot detection, while currently bypassed for local runs, could tighten at any time.

**The in-process cache.** The 1-hour result cache is a Python dict that lives in the Flask process. It resets on restart, isn't shared across processes or replicas, and can grow unbounded on a busy server. It works fine for a single-user deployment but wouldn't survive horizontal scaling.

**The OpenAI rate limit budget.** Suggestions use `gpt-4o-mini` with a 2-second delay between requests to stay under rate limits. A user with a large storefront hitting the endpoint repeatedly in parallel would exhaust the rate limit quickly. There's no per-user throttling.

---

## What I'd build next

**Scheduled monitoring with email reports.** The most useful version of this tool runs automatically — once a week, check the storefront, diff the results against last week, and email the influencer a report: "3 videos started showing this week, 5 new videos aren't showing, here are suggested titles." This turns a one-off diagnostic into an ongoing feedback loop.

**Automated title updates (the last mile).** Once the optimal title is known, the tool should be able to update it directly in Amazon's Creator Hub on the user's behalf. This requires building an authenticated flow (likely browser-based since Amazon doesn't offer a public API for this), but it's the step that closes the loop and delivers the most value.

**Thumbnail optimisation.** Amazon's matching algorithm considers more than just the title — thumbnail relevance, watch time, and engagement metrics all play a role. A natural extension is analysing whether the thumbnail clearly shows the product and suggesting improvements, treating it as the same "why isn't this video shown?" problem applied to a different input.

**Multi-storefront dashboards.** Agencies managing multiple influencer accounts need to monitor dozens of storefronts at once. A dashboard aggregating shown/not-shown rates, title suggestion status, and week-over-week deltas across accounts would be the natural evolution for a B2B version of this tool.
