# Stock Discord Bot — Project Guide

## Tech Stack

- **Discord bot**: `discord.py` ≥2.3 (`discord.ext.commands`, `discord.ext.tasks`)
- **Market data**: `yfinance` (daily, weekly, monthly, intraday)
- **Indicators**: `ta` library (RSI, MACD, SMA, EMA, Bollinger Bands)
- **Database**: SQLite via `aiosqlite` (async)
- **Tavily**: optional news API; gracefully no-ops if `TAVILY_API_KEY` is absent
- **Testing**: `pytest` + `pytest-cov`; run with `python -m pytest -q`

## Project Structure

```
bot.py                  # Bot entry point, loads cogs
config.py               # Env vars + timezone constant (MARKET_TZ = US/Eastern, via zoneinfo)
db.py                   # Async SQLite helpers (watchlist, signal_history, daily_summary)
cogs/
  debrief.py            # EOD debrief, Friday recap, !debrief, !market, !news, !weekly
  scanner.py            # Scan loop, Discord commands, embed builders
  watchlist.py          # !add, !remove, !watchlist and natural-language listener
indicators/
  calculator.py         # compute_indicators(), compute_extended_indicators()
  fundamentals.py       # score_fundamentals() → FundamentalScore
  signals.py            # evaluate_technical_signals(), evaluate_composite_signal() → SignalResult
  trend.py              # analyze_trend() → TrendAnalysis
services/
  market_data.py        # yfinance wrappers with TTL caching
  market_summary.py     # get_market_overview() → {indices, sectors}
  news.py               # get_market_news(), get_ticker_news(), get_weekly_news(), get_batch_ticker_news()
tests/                  # pytest test suite (107 tests as of overhaul)
plans/                  # Implementation plan docs
data/                   # SQLite DB file (gitignored)
```

## Environment Variables (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | — | Bot token (required) |
| `ALERT_CHANNEL_ID` | `0` | Channel for scan alerts |
| `SCAN_INTERVAL` | `15` | Scan loop interval (minutes) |
| `TAVILY_API_KEY` | — | News (optional; all other features work without it) |

## Running the Bot

```bash
python bot.py
```

## Running Tests

```bash
python -m pytest -q
python -m pytest --cov=indicators --cov=cogs --cov=db -q   # with coverage
```

Tests stub out all Discord and service dependencies — no live API calls, no bot connection needed.

## Scoring Architecture (Three-Layer Composite)

| Layer | Range | Source |
|---|---|---|
| Fundamentals | 0–40 pts | `score_fundamentals(fa)` — scales `FundamentalScore.score` (0-100) to 0-40 |
| Trend | −20 to +30 pts | `analyze_trend(daily, weekly, monthly)` |
| Technical | −20 to +30 pts | `evaluate_technical_signals(snap)` |
| **Composite** | **−40 to +100** | Sum of all three |

**Thresholds:** STRONG BUY ≥55 · BUY ≥35 · NEUTRAL ≥−10 · CAUTION <−10

**Gate:** Failed fundamental gate (negative EPS+FCF+high debt) → never BUY regardless of score.

**ETFs:** Detected via `quote_type == "ETF"`, skip earnings gate, use neutral `FundamentalScore(score=50, passed_gate=True)`.

## Key Design Decisions

- `compute_extended_indicators(ticker)` returns `(IndicatorSnapshot | None, TrendAnalysis)` — use this everywhere instead of the bare `compute_indicators()`.
- `score_fundamentals(None)` returns a gate-failed score (graceful degradation when FA unavailable).
- Suppressed signals (non-BUY) are stored in an in-memory ring buffer (`_suppressed_buffer`, maxlen=50) and exposed via `!suppressed`.
- Fundamentals cache TTL: 30 min. Market data cache TTL: 5 min.

## Key Conventions

### `get_market_overview()` return shape

```python
{
  "indices": { "SPY": {"name": str, "price": float, "change": float, "change_pct": float, "volume": int}, ... },
  "sectors": { "XLK": {"name": str, "price": float, "change": float, "change_pct": float, "volume": int}, ... },
}
```

Indices tracked: SPY, QQQ, DIA, IWM. Sectors: 11 XL* ETFs.

### Embed size limit

Discord hard limit is 6000 chars. `_build_debrief_embed` checks `len(embed) > 5800` after building all fields and drops the Market Pulse field as graceful degradation. `discord.Embed.__len__()` returns total character count across all fields.

### `_news_embed_field(headlines, compact)`

- `compact=True` → title + URL only (used in `!market`, `!weekly`)
- `compact=False` → bold title + URL + 120-char snippet (used in EOD `!debrief`)

## Discord Commands

| Command | Description |
|---|---|
| `!scan` | Force immediate scan of watchlist |
| `!check TICKER` | Full three-layer analysis for any ticker |
| `!fundamentals TICKER` | Raw fundamental data |
| `!signals [TICKER]` | Recent signal history from DB |
| `!suppressed [N]` | Last N suppressed signals from in-memory buffer |
| `!debrief` | Manual EOD debrief embed |
| `!market` | Current market pulse (indices + sectors) |
| `!news` | Latest market news |
| `!weekly` | Friday recap |

## Database Schema

- `watchlist` — tickers being monitored
- `signal_history` — fired BUY/STRONG BUY signals (includes `fundamental_score`, `trend_score`, `technical_score`)
- `daily_summary` — daily OHLCV summaries
