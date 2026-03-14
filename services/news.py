import time
import logging
from config import TAVILY_API_KEY

log = logging.getLogger(__name__)

_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 600  # 10 minutes

# Tavily free tier: 1000 searches/month (~33/day).
# Strategy: batch all ticker lookups into one search; share market-news cache
# across !debrief and !market so they never double-count.


def _get_client():
    if not TAVILY_API_KEY:
        return None
    try:
        from tavily import TavilyClient
        return TavilyClient(api_key=TAVILY_API_KEY)
    except Exception as e:
        log.warning(f"Tavily client init failed: {e}")
        return None


def _search(cache_key: str, query: str, max_results: int, days: int) -> list[dict]:
    now = time.time()
    if cache_key in _cache:
        ts, results = _cache[cache_key]
        if now - ts < _CACHE_TTL:
            return results

    client = _get_client()
    if client is None:
        return []

    try:
        response = client.search(
            query=query,
            search_depth="basic",
            topic="news",
            days=days,
            max_results=max_results,
        )
        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:200],
                "published_date": r.get("published_date", ""),
            }
            for r in response.get("results", [])
        ]
        _cache[cache_key] = (now, results)
        return results
    except Exception as e:
        log.warning(f"Tavily search failed ({query!r}): {e}")
        return []


# ── Single-ticker helpers (used by !news TICKER) ──────────────────────────────

def get_market_news(max_results: int = 5) -> list[dict]:
    """Top market news headlines from the last 24 hours.
    Result is cached and shared — !debrief and !market both pull from here."""
    # Fetch the ceiling (8) once; callers slice to what they need.
    all_results = _search("market_news_1d", "stock market news today", 8, days=1)
    return all_results[:max_results]


def get_ticker_news(ticker: str, max_results: int = 3) -> list[dict]:
    """News for a single ticker, last 24 h. Only called by !news TICKER."""
    key = f"ticker_news_{ticker.upper()}_1d"
    return _search(key, f"{ticker.upper()} stock news", max_results, days=1)


# ── Batch helpers (used by !weekly / friday_recap) ────────────────────────────

def get_weekly_news(max_results: int = 8) -> list[dict]:
    """Top market news from the last 5 trading days.
    Result is cached and shared across weekly recap calls."""
    all_results = _search("market_news_5d", "stock market news this week", 10, days=5)
    return all_results[:max_results]


def get_batch_ticker_news(tickers: list[str], days: int = 5, per_ticker: int = 2) -> dict[str, list[dict]]:
    """ONE Tavily search covering all tickers; results filtered client-side.

    Returns a dict mapping ticker → list of headlines that mention it.
    Falls back to an empty dict for any ticker with no matches.

    Why one search instead of N:
      • Tavily free tier = 1000 calls/month; weekly recap with 10 tickers
        would otherwise cost 10 calls per trigger vs. 1 here.
      • Tavily ranks results by relevance; a combined query like
        "AAPL MSFT NVDA stock news" returns the most newsworthy
        headlines across all three — identical to what N separate
        narrow queries would surface.
    """
    if not tickers:
        return {}

    tickers = [t.upper() for t in tickers]
    # Sort for a stable cache key regardless of watchlist insertion order
    cache_key = f"batch_ticker_{'_'.join(sorted(tickers))}_{days}d"

    # Use enough results to give each ticker at least per_ticker hits
    max_results = min(len(tickers) * per_ticker + 4, 20)  # Tavily max is 20
    query = " ".join(tickers) + " stock news"
    if days > 1:
        query += " this week"

    all_results = _search(cache_key, query, max_results, days=days)

    # Distribute results to tickers by checking title + snippet
    per_ticker_map: dict[str, list[dict]] = {t: [] for t in tickers}
    for result in all_results:
        text = (result["title"] + " " + result["snippet"]).upper()
        for ticker in tickers:
            if ticker in text and len(per_ticker_map[ticker]) < per_ticker:
                per_ticker_map[ticker].append(result)

    return per_ticker_map
