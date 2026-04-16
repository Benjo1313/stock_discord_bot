import time
import yfinance as yf
import pandas as pd

_cache: dict[str, tuple[float, pd.DataFrame]] = {}
_CACHE_TTL = 300  # 5 minutes

_fundamentals_cache: dict[str, tuple[float, dict]] = {}
_FUNDAMENTALS_TTL = 1800  # 30 minutes — fundamentals don't change intraday


def validate_ticker(symbol: str) -> bool:
    try:
        t = yf.Ticker(symbol)
        info = t.info
        return info.get("regularMarketPrice") is not None or info.get("currentPrice") is not None
    except Exception:
        return False


def get_daily_data(symbol: str, period: str = "1y") -> pd.DataFrame | None:
    cache_key = f"{symbol}_{period}_daily"
    now = time.time()
    if cache_key in _cache:
        ts, df = _cache[cache_key]
        if now - ts < _CACHE_TTL:
            return df

    try:
        t = yf.Ticker(symbol)
        df = t.history(period=period, interval="1d")
        if df.empty:
            return None
        _cache[cache_key] = (now, df)
        return df
    except Exception:
        return None


def get_weekly_data(symbol: str, period: str = "2y") -> pd.DataFrame | None:
    """Fetch weekly OHLCV data. Used for 20-week SMA trend analysis."""
    cache_key = f"{symbol}_{period}_weekly"
    now = time.time()
    if cache_key in _cache:
        ts, df = _cache[cache_key]
        if now - ts < _CACHE_TTL:
            return df

    try:
        t = yf.Ticker(symbol)
        df = t.history(period=period, interval="1wk")
        if df.empty:
            return None
        _cache[cache_key] = (now, df)
        return df
    except Exception:
        return None


def get_monthly_data(symbol: str, period: str = "5y") -> pd.DataFrame | None:
    """Fetch monthly OHLCV data. Used for 10-month SMA trend analysis."""
    cache_key = f"{symbol}_{period}_monthly"
    now = time.time()
    if cache_key in _cache:
        ts, df = _cache[cache_key]
        if now - ts < _CACHE_TTL:
            return df

    try:
        t = yf.Ticker(symbol)
        df = t.history(period=period, interval="1mo")
        if df.empty:
            return None
        _cache[cache_key] = (now, df)
        return df
    except Exception:
        return None


def get_intraday_data(symbol: str) -> pd.DataFrame | None:
    cache_key = f"{symbol}_intraday"
    now = time.time()
    if cache_key in _cache:
        ts, df = _cache[cache_key]
        if now - ts < _CACHE_TTL:
            return df

    try:
        t = yf.Ticker(symbol)
        df = t.history(period="1d", interval="5m")
        if df.empty:
            return None
        _cache[cache_key] = (now, df)
        return df
    except Exception:
        return None


def get_fundamentals(symbol: str) -> dict | None:
    """Fetch key fundamental data for a ticker via yfinance .info.

    Uses a 30-minute cache — fundamentals don't change intraday.
    """
    now = time.time()
    if symbol in _fundamentals_cache:
        ts, data = _fundamentals_cache[symbol]
        if now - ts < _FUNDAMENTALS_TTL:
            return data

    try:
        info = yf.Ticker(symbol).info

        def _v(key):
            val = info.get(key)
            return None if val in (None, "N/A", "", 0) else val

        result = {
            # Identity
            "name":               info.get("longName") or info.get("shortName", symbol),
            "sector":             info.get("sector"),
            "industry":           info.get("industry"),
            "quote_type":         info.get("quoteType"),  # "ETF", "EQUITY", etc.
            # Valuation
            "market_cap":         _v("marketCap"),
            "enterprise_value":   _v("enterpriseValue"),
            "pe_trailing":        _v("trailingPE"),
            "pe_forward":         _v("forwardPE"),
            "ps_ratio":           _v("priceToSalesTrailing12Months"),
            "pb_ratio":           _v("priceToBook"),
            "ev_ebitda":          _v("enterpriseToEbitda"),
            # Earnings & Growth
            "eps_trailing":       _v("trailingEps"),
            "eps_forward":        _v("forwardEps"),
            "earnings_growth":    _v("earningsGrowth"),
            "revenue_growth":     _v("revenueGrowth"),
            # Profitability
            "profit_margin":      _v("profitMargins"),
            "operating_margin":   _v("operatingMargins"),
            "roe":                _v("returnOnEquity"),
            "roa":                _v("returnOnAssets"),
            # Financial Health
            "total_revenue":      _v("totalRevenue"),
            "free_cash_flow":     _v("freeCashflow"),
            "total_cash":         _v("totalCash"),
            "total_debt":         _v("totalDebt"),
            "debt_to_equity":     _v("debtToEquity"),
            "current_ratio":      _v("currentRatio"),
            # Dividends
            "dividend_yield":     _v("dividendYield"),
            "payout_ratio":       _v("payoutRatio"),
            # Analyst
            "target_price":       _v("targetMeanPrice"),
            "recommendation":     info.get("recommendationKey"),
            "num_analysts":       _v("numberOfAnalystOpinions"),
        }
        _fundamentals_cache[symbol] = (now, result)
        return result
    except Exception:
        return None


def get_current_price(symbol: str) -> dict | None:
    try:
        t = yf.Ticker(symbol)
        info = t.info
        price = info.get("regularMarketPrice") or info.get("currentPrice")
        prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
        if price is None:
            return None
        change = price - prev_close if prev_close else 0
        change_pct = (change / prev_close * 100) if prev_close else 0
        return {
            "price": price,
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "volume": info.get("regularMarketVolume") or info.get("volume", 0),
            "name": info.get("shortName", symbol),
        }
    except Exception:
        return None
