# Implementation Plan: Long-Term Signal Overhaul

## Problem

All buy signals are purely short-term technical indicators (RSI, MACD, EMA crossovers, VWAP, Bollinger bounces). Fundamentals data is fetched but never used in signal scoring. The bot fires BUY on stocks with terrible fundamentals based on short-term technical blips.

## Solution: Three-Layer Signal Architecture

```
Layer 1: Fundamental Gate (pass/fail + 0-40 pts)
  └─ Hard-fail: negative EPS + forward EPS, negative FCF + margins, extreme debt
  └─ Scoring: profitability, growth, financial health, valuation

Layer 2: Trend Confirmation (-20 to +30 pts)
  └─ Weekly trend (20-week SMA direction)
  └─ Monthly trend (10-month SMA direction)
  └─ Bearish alignment caps signal at NEUTRAL

Layer 3: Technical Confirmation (-20 to +30 pts)
  └─ Existing indicators, reweighted lower
  └─ Golden Cross keeps high weight (actually long-term)
  └─ VWAP, Bollinger, EMA 9/21 reduced significantly

Composite: STRONG BUY ≥55, BUY ≥35, NEUTRAL ≥-10
```

## Phases

### Phase 1: Test Infrastructure + Fundamental Gate

1. **Set up test infrastructure** (`tests/__init__.py`, `tests/conftest.py`, `requirements.txt`)
   - Create `tests/` package with pytest fixtures
   - Mock `IndicatorSnapshot` objects and fundamentals dicts for known-good and known-bad stocks
   - Add `pytest` to `requirements.txt`

2. **Write tests for fundamental scoring** (`tests/test_fundamentals.py`)
   - `score_fundamentals(fa_dict) -> FundamentalScore` dataclass with `score` (0-100), `passed_gate` (bool), `reasons` (list[str])
   - Gate hard-fail conditions (AND logic, not OR):
     - Negative EPS trailing AND negative EPS forward
     - Negative FCF AND negative operating margin
     - Debt/equity > 300 AND negative FCF
     - No fundamentals data available
   - Scoring sub-categories (each 0-25):
     - Profitability: profit margin, operating margin, ROE, ROA
     - Growth: revenue growth, earnings growth, forward vs trailing EPS
     - Financial health: debt/equity, current ratio, FCF, cash position
     - Valuation: forward P/E, P/B, analyst consensus
   - Edge cases: all-None fields, partial data

3. **Implement fundamental scoring** (`indicators/fundamentals.py`)
   - `FundamentalScore` dataclass and `score_fundamentals()` pure function
   - Takes the dict `get_fundamentals()` already returns — no new API calls
   - When field is None: sub-category scores 0 but does NOT trigger hard-fail gate
   - `reasons` list includes human-readable strings for Discord embeds

4. **Integrate fundamental gate into scanner** (`cogs/scanner.py`)
   - In `_run_scan()`: after `compute_indicators()`, before `evaluate_signals()`
   - Call `get_fundamentals(ticker)` then `score_fundamentals(fa)`
   - If `passed_gate` is False, skip ticker (log, don't alert)
   - Pass `FundamentalScore` through to alert embed for display

5. **Add fundamentals cache TTL override** (`services/market_data.py`)
   - Separate `_fundamentals_cache` with 30-minute TTL (fundamentals don't change intraday)
   - Reduces API calls during 15-minute scan loops

### Phase 2: Multi-Timeframe Trend

6. **Add weekly/monthly data fetching** (`services/market_data.py`)
   - `get_weekly_data(symbol, period="2y")` — `interval="1wk"`
   - `get_monthly_data(symbol, period="5y")` — `interval="1mo"`
   - Same caching pattern as `get_daily_data()`, 15-minute TTL

7. **Write tests for trend analysis** (`tests/test_trend.py`)
   - `analyze_trend(daily_df, weekly_df, monthly_df) -> TrendAnalysis` dataclass:
     - `weekly_trend`: "up" | "down" | "sideways"
     - `monthly_trend`: "up" | "down" | "sideways"
     - `trend_alignment`: "bullish" | "bearish" | "mixed"
     - `trend_score`: -20 to +30
     - `price_vs_weekly_sma`, `price_vs_monthly_sma`
     - `reasons`: list[str]
   - Weekly: price above 20-week SMA AND slope positive = "up"
   - Monthly: price above 10-month SMA AND slope positive = "up"
   - Alignment: both up = "bullish" (+30), both down = "bearish" (-30), mixed = "mixed" (0)

8. **Implement trend analysis** (`indicators/trend.py`)
   - `TrendAnalysis` dataclass and `analyze_trend()` function
   - 20-week SMA (≈100-day, institutional level) and 10-month SMA (≈200-day)
   - Slope via comparing current SMA to N periods ago (4 weeks, 3 months)

9. **Integrate trend into compute pipeline** (`indicators/calculator.py`)
   - Add trend fields to `IndicatorSnapshot`
   - New `compute_extended_indicators(ticker)` = existing + weekly/monthly trend
   - Existing `compute_indicators()` stays unchanged for backward compat

10. **Wire trend confirmation into scanner** (`cogs/scanner.py`)
    - Use `compute_extended_indicators()` instead of `compute_indicators()`
    - Bearish trend alignment → suppress BUY signals
    - Mixed trend → allows BUY but not STRONG BUY
    - Log suppressed signals for tuning

### Phase 3: Composite Scoring

11. **Write tests for composite scoring** (`tests/test_composite.py`)
    - `evaluate_composite_signal(snap, fundamental_score, trend_analysis) -> SignalResult`
    - Score composition: Fundamentals 0-40 (40%), Trend -20 to +30 (25%), Technicals -20 to +30 (35%)
    - New thresholds: STRONG BUY ≥55, BUY ≥35, NEUTRAL ≥-10, CAUTION <-10
    - Test scenarios: great all-around = STRONG BUY, great technicals + failed gate = never BUY, good fundamentals + bearish trend = NEUTRAL max

12. **Refactor signals.py** (`indicators/signals.py`)
    - Rename `evaluate_signals()` → `evaluate_technical_signals()`
    - Reweight technicals: RSI 10 (was 20), MACD 8 (was 15), Golden Cross 15 (was 20), Volume 5 (was 15), Bollinger 5 (was 15), VWAP 3 (was 10), EMA crossover 5 (was 10), Price>SMA20 3 (was 10), Price>SMA50 5 (was 10)
    - Cap technical score at +30, floor at -20
    - Add `evaluate_composite_signal()` combining all three layers
    - Update `SignalResult` with `fundamental_score`, `trend_score`, `technical_score`, `gate_passed`

13. **Update embed formatting** (`cogs/scanner.py`)
    - Three-layer breakdown: "Fundamentals: 32/40 | Trend: +20/30 | Technicals: +18/30 | Total: 70"
    - Fundamentals summary line: "P/E 22x | ROE 28% | FCF $4.2B | D/E 45%"
    - Trend summary: "Weekly: Uptrend | Monthly: Uptrend | Aligned: Bullish"
    - Gate failure: red banner with reason
    - Update `_score_bar()` for new range, `_SCORE_THRESHOLDS` for new values

14. **Update database schema** (`db.py`)
    - Add `fundamental_score`, `trend_score`, `technical_score` columns to `signal_history`
    - `ALTER TABLE` with existence check, old rows get NULL for new columns

15. **Update `_run_scan()` for composite** (`cogs/scanner.py`)
    - Replace Phase 1/2 ad-hoc gating with unified `evaluate_composite_signal()`
    - Composite function handles gating internally
    - `!check` fallback: if fundamentals/weekly data unavailable, show technical-only with warning

### Phase 4: Edge Cases & Polish

16. **Handle data unavailability gracefully**
    - Fundamentals fetch fails → treat as gate-failed ("Unable to verify fundamentals")
    - Weekly/monthly data too short → fall back to daily SMA50/SMA200 as trend proxy
    - ETFs (no earnings): detect via `quoteType == "ETF"`, use trend+technicals only, skip earnings gate
    - Add `quoteType` to fundamentals dict

17. **Add logging for suppressed signals**
    - Log suppressed signals at INFO with reason
    - Add `!suppressed` command showing last N filtered signals

18. **Integration tests** (`tests/test_composite.py`)
    - Full pipeline with mocked yfinance responses
    - Verify: daily data → extended indicators → fundamentals → composite signal → correct result

## Key Design Decisions

- **AND conditions for hard-fail** — multiple bad metrics required to reject. Avoids filtering turnaround stories or cyclical stocks temporarily bad on one metric.
- **Missing fields score 0, don't hard-fail** — only explicit bad values trigger the gate.
- **ETFs get separate path** — skip earnings-based checks, use trend+technicals.
- **Conservative start** — let more through initially, tighten based on monitoring.
- **30-min fundamentals cache** — they don't change intraday, saves API calls.

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Gate too aggressive, filters legitimate opportunities | AND conditions for hard-fail, log suppressed, tune thresholds |
| API rate limits from extra yfinance calls | 30-min fundamentals cache, 15-min weekly/monthly cache |
| Incomplete data for SPACs, ADRs, foreign stocks | Graceful fallback to "cannot verify" |
| ETFs always fail earnings gate | Detect via `quoteType`, separate evaluation path |
| Increased scan loop duration | Cache heavily after first scan, add timing logs |
| New score range breaks anti-spam | Cooldown is on `signal_type` string, not score — no change needed |

## New/Modified Files

**New:**
- `indicators/fundamentals.py` — Fundamental scoring and gating
- `indicators/trend.py` — Multi-timeframe trend analysis
- `tests/__init__.py`
- `tests/conftest.py` — Shared fixtures
- `tests/test_fundamentals.py`
- `tests/test_trend.py`
- `tests/test_signals.py`
- `tests/test_composite.py`

**Modified:**
- `indicators/signals.py` — Refactored scoring, composite signal
- `indicators/calculator.py` — Extended indicators with trend
- `services/market_data.py` — Weekly/monthly data, fundamentals cache
- `cogs/scanner.py` — Composite pipeline, updated embeds
- `db.py` — New score columns

## Success Criteria

- [x] Stocks with negative EPS, negative FCF, and high debt never trigger BUY/STRONG BUY
- [x] Stocks in monthly downtrend with RSI bounce don't trigger BUY
- [x] Fundamentally strong stock + confirmed uptrend + bullish technicals = STRONG BUY
- [x] `!check TICKER` shows three-layer score breakdown
- [x] `!fundamentals TICKER` unchanged from current behavior
- [x] All tests pass with ≥80% coverage on indicators package (107 tests, all passing)
- [ ] Scan loop completes within 2x current duration (not measured — requires live run)

## Implementation Status

All 18 steps complete as of 2026-04-15.

### Phase 1 ✅
Steps 1–5: test infrastructure, `indicators/fundamentals.py` (`FundamentalScore`, `score_fundamentals()`), fundamentals cache TTL (30 min).

### Phase 2 ✅
Steps 6–10: `get_weekly_data()` / `get_monthly_data()`, `indicators/trend.py` (`TrendAnalysis`, `analyze_trend()`), `compute_extended_indicators()` in `indicators/calculator.py`.

### Phase 3 ✅
Steps 11–15: `evaluate_composite_signal()` in `indicators/signals.py`, reweighted technicals (cap ±30), three-layer embeds in `cogs/scanner.py`, DB schema migration for `fundamental_score` / `trend_score` / `technical_score`.

### Phase 4 ✅
Step 16: ETF detection (`quote_type == "ETF"` → neutral gate bypass), graceful degradation when data unavailable.
Step 17: `_suppressed_buffer` (in-memory deque, maxlen=50), `!suppressed [N]` command.
Step 18: `tests/test_integration.py` — 12 tests covering full pipeline with mocked market data.
