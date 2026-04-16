# Stock Discord Bot — Project Notes

## Tech Stack

- **discord.py** ≥2.3 — bot framework, slash-free (prefix `!`)
- **yfinance** — all market data (prices, OHLCV, daily history)
- **ta** — technical indicator calculations (RSI, MACD, Bollinger Bands, etc.)
- **aiosqlite** — async SQLite via `db.py`; database file lives at `data/stock_bot.db`
- **Tavily** — optional news API; gracefully no-ops if `TAVILY_API_KEY` is absent

## Project Structure

```
bot.py                  Entry point; loads cogs
config.py               Env vars + timezone constant (MARKET_TZ = US/Eastern)
db.py                   All database access (watchlist, signals, daily summaries)
cogs/
  debrief.py            EOD debrief, Friday recap, !debrief, !market, !news, !weekly
  watchlist.py          !add, !remove, !watchlist and natural-language listener
  scanner.py            15-min scan loop + !scan, !check, !signals
services/
  market_data.py        get_current_price(), get_daily_data() — thin yfinance wrappers
  market_summary.py     get_market_overview() → {indices, sectors} — uses market_data
  news.py               get_market_news(), get_ticker_news(), get_weekly_news(), get_batch_ticker_news()
indicators/
  calculator.py         compute_indicators(ticker) → snapshot dict
  signals.py            evaluate_signals(snapshot) → SignalResult(signal_type, score)
tests/
  test_debrief.py       Unit tests for Debrief cog (18 tests, fully stubbed)
```

## Environment Variables

| Variable | Required | Notes |
|---|---|---|
| `DISCORD_TOKEN` | Yes | Bot token from Discord Developer Portal |
| `ALERT_CHANNEL_ID` | Yes | Channel ID for auto-posts |
| `TAVILY_API_KEY` | No | News; all other features work without it |
| `SCAN_INTERVAL` | No | Minutes between scans (default: 15) |

## Running Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

Tests stub out all Discord and service dependencies — no live API calls, no bot connection needed.

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

### Signal suppression

Same signal for the same ticker is suppressed for 2 hours to prevent spam (handled in `cogs/scanner.py`).
