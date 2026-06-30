import { useRef, useState } from "react";

const DEFAULT_URL = "https://www.amazon.com/shop/techthatinterest/";

// ─── small reusable pieces ────────────────────────────────────────────────────

function Spinner({ className = "h-5 w-5" }) {
  return (
    <svg className={`animate-spin ${className}`} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  );
}

function StatCard({ label, value, color }) {
  return (
    <div className={`rounded-2xl p-5 flex flex-col items-center gap-1 ${color}`}>
      <span className="text-3xl font-bold">{value ?? "—"}</span>
      <span className="text-sm font-medium opacity-80">{label}</span>
    </div>
  );
}

function Badge({ shown }) {
  return shown ? (
    <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold bg-emerald-100 text-emerald-700">
      <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
      </svg>
      Shown on product
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold bg-red-100 text-red-600">
      <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
        <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
      </svg>
      Not shown
    </span>
  );
}

function VideoCard({ video, isChecking, suggestion }) {
  return (
    <div className={`bg-white rounded-2xl shadow-sm border p-5 flex flex-col gap-3 transition-all duration-300 ${isChecking ? "border-indigo-300 ring-2 ring-indigo-200" : "border-gray-100 hover:shadow-md"}`}>
      <div className="flex items-start justify-between gap-3">
        <span className="text-xs font-semibold text-gray-400 mt-0.5">#{video.index}</span>
        {isChecking ? (
          <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold bg-indigo-100 text-indigo-600">
            <Spinner className="h-3 w-3 text-indigo-500" />
            Checking…
          </span>
        ) : (
          <Badge shown={video.shown_on_product_page} />
        )}
      </div>

      <p className="text-sm font-semibold text-gray-800 leading-snug line-clamp-2">
        {video.title}
      </p>

      <div className="flex flex-col gap-1 text-xs text-gray-500">
        {video.product_name && (
          <span className="bg-gray-50 px-2 py-0.5 rounded w-fit">
            Product: {video.product_name.split(" ").slice(0, 5).join(" ") + (video.product_name.split(" ").length > 5 ? "…" : "")}
          </span>
        )}
        {video.asin && (
          <span className="font-mono bg-gray-50 px-2 py-0.5 rounded w-fit">ASIN: {video.asin}</span>
        )}
      </div>

      {video.product_url && video.product_url !== "N/A" && (
        <a
          href={video.product_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
        >
          View on Amazon
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
      )}

      {/* AI title suggestion — only for not-shown videos */}
      {!isChecking && !video.shown_on_product_page && suggestion && (
        <div className="mt-1 pt-3 border-t border-amber-100 flex flex-col gap-1.5">
          <span className="text-xs font-semibold text-amber-600">AI Suggested Title</span>
          <p className="text-xs font-medium text-gray-800">"{suggestion.suggested_title}"</p>
          {suggestion.reason && (
            <p className="text-xs text-gray-400 italic leading-relaxed">{suggestion.reason}</p>
          )}
        </div>
      )}

      {/* Spinner while suggestion is loading */}
      {!isChecking && !video.shown_on_product_page && suggestion === "loading" && (
        <div className="mt-1 pt-3 border-t border-amber-100 flex items-center gap-2 text-xs text-amber-500">
          <Spinner className="h-3 w-3" />
          Generating title suggestion…
        </div>
      )}
    </div>
  );
}

// ─── progress log item ─────────────────────────────────────────────────────────

function LogLine({ icon, text, dim }) {
  return (
    <div className={`flex items-start gap-2 text-xs text-slate-200 ${dim ? "opacity-40" : ""}`}>
      <span className="mt-0.5 shrink-0">{icon}</span>
      <span>{text}</span>
    </div>
  );
}

// ─── main app ─────────────────────────────────────────────────────────────────

export default function App() {
  const [url, setUrl] = useState(DEFAULT_URL);
  const [phase, setPhase] = useState("idle"); // idle | scraping | done | error
  const [log, setLog] = useState([]);         // array of {icon, text}
  const [videos, setVideos] = useState([]);   // fully checked videos
  const [checking, setChecking] = useState(null); // {index, title, asin} — in-flight check
  const [total, setTotal] = useState(null);
  const [summary, setSummary] = useState(null); // {shown, not_shown}
  const [errorMsg, setErrorMsg] = useState("");
  const [filter, setFilter] = useState("all");
  const [suggestions, setSuggestions] = useState({}); // keyed by asin
  const esRef = useRef(null);

  function addLog(icon, text) {
    setLog((prev) => [...prev, { icon, text }]);
  }

  function startScrape(e) {
    e.preventDefault();

    // Close any existing stream
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }

    // Reset state
    setPhase("scraping");
    setLog([]);
    setVideos([]);
    setChecking(null);
    setTotal(null);
    setSummary(null);
    setErrorMsg("");
    setFilter("all");
    setSuggestions({});

    const es = new EventSource(`/scrape/stream?url=${encodeURIComponent(url)}`);
    esRef.current = es;

    es.onmessage = (event) => {
      const msg = JSON.parse(event.data);

      switch (msg.type) {
        case "status":
          addLog("⚙️", msg.message);
          break;

        case "found":
          setTotal(msg.total);
          addLog("🎬", msg.message);
          break;

        case "checking":
          setChecking({ index: msg.index, title: msg.title, asin: msg.asin });
          // Pre-add the card in "checking" state so it animates in
          setVideos((prev) => {
            const alreadyThere = prev.some((v) => v.index === msg.index);
            if (alreadyThere) return prev;
            return [...prev, { index: msg.index, title: msg.title, asin: msg.asin, product_url: `https://www.amazon.com/dp/${msg.asin}`, vendor_code: "", product_name: "", shown_on_product_page: false, _checking: true }];
          });
          break;

        case "video":
          setChecking(null);
          setVideos((prev) => {
            const exists = prev.some((v) => v.index === msg.index);
            if (exists) {
              return prev.map((v) => v.index === msg.index ? { ...msg, _checking: false } : v);
            }
            // Cache replay: no prior "checking" event, so add the card directly
            return [...prev, { ...msg, _checking: false }];
          });
          addLog(
            msg.shown_on_product_page ? "✅" : "❌",
            `${msg.index}/${msg.total} — ${msg.title.slice(0, 60)}`
          );
          break;

        case "done":
          setSummary({ shown: msg.shown, not_shown: msg.not_shown });
          setPhase("done");
          addLog("🏁", `Done! ${msg.shown} of ${msg.total} shown on product pages.`);
          // Mark not-shown videos as awaiting a suggestion (backend may send them next)
          setVideos((prev) => {
            const pending = {};
            prev.filter((v) => !v._checking && !v.shown_on_product_page).slice(0, 10)
              .forEach((v) => { pending[v.asin] = "loading"; });
            if (Object.keys(pending).length > 0) setSuggestions(pending);
            return prev;
          });
          break;

        case "suggestion":
          setSuggestions((prev) => ({
            ...prev,
            [msg.asin]: { reason: msg.reason, suggested_title: msg.suggested_title },
          }));
          addLog("💡", `Title suggestion ready for #${msg.index}`);
          break;

        case "error":
          setErrorMsg(msg.message);
          setPhase("error");
          addLog("🚨", msg.message);
          // Clear any pending "loading" suggestion badges on error
          setSuggestions((prev) => {
            const cleaned = { ...prev };
            Object.keys(cleaned).forEach((k) => { if (cleaned[k] === "loading") delete cleaned[k]; });
            return cleaned;
          });
          es.close();
          esRef.current = null;
          break;

        case "stream_end":
          es.close();
          esRef.current = null;
          break;

        default:
          break;
      }
    };

    es.onerror = () => {
      if (phase !== "done") {
        setErrorMsg("Connection to the scraper was lost. Make sure the Flask API is running.");
        setPhase("error");
      }
      es.close();
      esRef.current = null;
    };
  }

  const isScraping = phase === "scraping";
  const checkedCount = videos.filter((v) => !v._checking).length;

  const filteredVideos = videos.filter((v) => {
    if (filter === "shown") return !v._checking && v.shown_on_product_page;
    if (filter === "not_shown") return !v._checking && !v.shown_on_product_page;
    return true;
  });

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-indigo-950 to-slate-900">
      {/* Header */}
      <header className="px-6 pt-10 pb-6 text-center">
        <div className="inline-flex items-center gap-2 bg-white/10 backdrop-blur rounded-full px-4 py-1.5 text-xs font-semibold text-indigo-200 mb-4">
          Amazon Influencer Scraper
        </div>
        <h1 className="text-4xl font-extrabold text-white tracking-tight">
          Storefront Video Inspector
        </h1>
        <p className="mt-2 text-indigo-300 text-sm max-w-md mx-auto">
          Paste an Amazon influencer storefront URL to see which videos appear on product pages.
        </p>
      </header>

      {/* URL form */}
      <div className="max-w-3xl mx-auto px-4 pb-8">
        <form onSubmit={startScrape} className="flex gap-2">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.amazon.com/shop/..."
            required
            disabled={isScraping}
            className="flex-1 rounded-xl border border-white/20 bg-white/10 backdrop-blur text-white placeholder-indigo-300 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:opacity-50 transition"
          />
          <button
            type="submit"
            disabled={isScraping}
            className="flex items-center gap-2 bg-indigo-500 hover:bg-indigo-400 disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold rounded-xl px-6 py-3 text-sm transition-colors"
          >
            {isScraping ? <><Spinner />Scraping…</> : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                Scrape
              </>
            )}
          </button>
        </form>
      </div>

      {/* Main content */}
      {(isScraping || phase === "done" || phase === "error") && (
        <div className="max-w-6xl mx-auto px-4 pb-16 flex flex-col gap-6">

          {/* Live activity panel */}
          <div className="bg-white/5 backdrop-blur border border-white/10 rounded-2xl overflow-hidden">
            {/* Progress bar + current action */}
            <div className="px-5 py-4 border-b border-white/10">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-white">
                  {phase === "done"
                    ? "Scrape complete"
                    : phase === "error"
                    ? "Scrape failed"
                    : checking
                    ? `Checking product page ${checking.index}${total ? ` of ${total}` : ""}…`
                    : log.length > 0
                    ? log[log.length - 1].text
                    : "Starting…"}
                </span>
                {isScraping && (
                  <span className="text-xs text-indigo-300">
                    {total ? `${checkedCount} / ${total} checked` : "Loading…"}
                  </span>
                )}
              </div>

              {/* Progress bar — only visible once we know the total */}
              {total !== null && (
                <div className="w-full bg-white/10 rounded-full h-1.5">
                  <div
                    className="bg-indigo-400 h-1.5 rounded-full transition-all duration-500"
                    style={{ width: `${Math.round((checkedCount / total) * 100)}%` }}
                  />
                </div>
              )}

              {/* Currently checking pill */}
              {checking && (
                <div className="mt-3 flex items-center gap-2 text-xs text-indigo-200">
                  <Spinner className="h-3.5 w-3.5 text-indigo-400" />
                  <span className="truncate">
                    Loading product page for: <strong>{checking.title.slice(0, 70)}</strong>
                  </span>
                </div>
              )}
            </div>

            {/* Scrollable log */}
            <div className="px-5 py-3 max-h-48 overflow-y-auto flex flex-col gap-1.5">
              {log.map((line, i) => (
                <LogLine
                  key={i}
                  icon={line.icon}
                  text={line.text}
                  dim={i < log.length - 1}
                />
              ))}
              {log.length === 0 && (
                <p className="text-xs text-indigo-400">Waiting for scraper to start…</p>
              )}
            </div>
          </div>

          {/* Error state */}
          {phase === "error" && (
            <div className="rounded-2xl bg-red-500/20 border border-red-400/30 p-5 text-red-200 text-sm">
              <p className="font-semibold mb-1">Something went wrong</p>
              <p className="font-mono text-xs break-all">{errorMsg}</p>
            </div>
          )}

          {/* Stats — show as soon as we know the total */}
          {total !== null && (
            <div className="grid grid-cols-3 gap-4">
              <StatCard label="Total Videos" value={total} color="bg-white/10 backdrop-blur text-white" />
              <StatCard
                label="Shown on Product"
                value={summary?.shown ?? videos.filter((v) => !v._checking && v.shown_on_product_page).length}
                color="bg-emerald-500/20 backdrop-blur text-emerald-200"
              />
              <StatCard
                label="Not Shown"
                value={summary?.not_shown ?? videos.filter((v) => !v._checking && !v.shown_on_product_page).length}
                color="bg-red-500/20 backdrop-blur text-red-200"
              />
            </div>
          )}

          {/* Filter tabs — only when scraping is done */}
          {phase === "done" && summary && (
            <div className="flex gap-2">
              {[
                { key: "all", label: `All (${total})` },
                { key: "shown", label: `Shown (${summary.shown})` },
                { key: "not_shown", label: `Not Shown (${summary.not_shown})` },
              ].map(({ key, label }) => (
                <button
                  key={key}
                  onClick={() => setFilter(key)}
                  className={`rounded-full px-4 py-1.5 text-xs font-semibold transition-colors ${
                    filter === key ? "bg-indigo-500 text-white" : "bg-white/10 text-indigo-200 hover:bg-white/20"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          {/* Video cards grid */}
          {filteredVideos.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredVideos.map((video) => (
                <VideoCard
                  key={video.index}
                  video={video}
                  isChecking={!!video._checking}
                  suggestion={suggestions[video.asin]}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
