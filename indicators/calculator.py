from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator, EMAIndicator
from ta.volatility import BollingerBands

from services.market_data import get_daily_data, get_intraday_data, get_weekly_data, get_monthly_data
from indicators.trend import TrendAnalysis, analyze_trend


@dataclass
class IndicatorSnapshot:
    ticker: str
    price: float
    volume: float
    avg_volume_20: float

    # RSI
    rsi: float | None = None

    # MACD
    macd_line: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    macd_crossover: str | None = None  # "bullish", "bearish", or None

    # Moving Averages
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_9: float | None = None
    ema_21: float | None = None
    golden_cross: bool = False
    death_cross: bool = False
    ema_crossover: str | None = None  # "bullish", "bearish", or None

    # Volume
    volume_ratio: float = 0.0
    volume_spike: bool = False

    # VWAP
    vwap: float | None = None

    # Bollinger Bands
    bb_upper: float | None = None
    bb_middle: float | None = None
    bb_lower: float | None = None
    bb_squeeze: bool = False
    bb_lower_bounce: bool = False

    errors: list[str] = field(default_factory=list)


def compute_indicators(ticker: str) -> IndicatorSnapshot | None:
    df = get_daily_data(ticker)
    if df is None or len(df) < 50:
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    price = float(close.iloc[-1])
    curr_volume = float(volume.iloc[-1])
    avg_vol_20 = float(volume.tail(20).mean())

    snap = IndicatorSnapshot(
        ticker=ticker.upper(),
        price=price,
        volume=curr_volume,
        avg_volume_20=avg_vol_20,
    )

    # RSI
    try:
        rsi_ind = RSIIndicator(close=close, window=14)
        rsi_vals = rsi_ind.rsi()
        snap.rsi = float(rsi_vals.iloc[-1]) if not pd.isna(rsi_vals.iloc[-1]) else None
    except Exception as e:
        snap.errors.append(f"RSI: {e}")

    # MACD
    try:
        macd_ind = MACD(close=close)
        macd_line = macd_ind.macd()
        macd_signal = macd_ind.macd_signal()
        macd_hist = macd_ind.macd_diff()

        snap.macd_line = _safe_float(macd_line.iloc[-1])
        snap.macd_signal = _safe_float(macd_signal.iloc[-1])
        snap.macd_hist = _safe_float(macd_hist.iloc[-1])

        if len(macd_hist) >= 2:
            prev = macd_hist.iloc[-2]
            curr = macd_hist.iloc[-1]
            if not pd.isna(prev) and not pd.isna(curr):
                if prev <= 0 and curr > 0:
                    snap.macd_crossover = "bullish"
                elif prev >= 0 and curr < 0:
                    snap.macd_crossover = "bearish"
    except Exception as e:
        snap.errors.append(f"MACD: {e}")

    # Moving Averages
    try:
        snap.sma_20 = _safe_float(SMAIndicator(close=close, window=20).sma_indicator().iloc[-1])
        snap.sma_50 = _safe_float(SMAIndicator(close=close, window=50).sma_indicator().iloc[-1])
        if len(close) >= 200:
            snap.sma_200 = _safe_float(SMAIndicator(close=close, window=200).sma_indicator().iloc[-1])
        snap.ema_9 = _safe_float(EMAIndicator(close=close, window=9).ema_indicator().iloc[-1])
        snap.ema_21 = _safe_float(EMAIndicator(close=close, window=21).ema_indicator().iloc[-1])

        # Golden/death cross (SMA50 vs SMA200)
        if snap.sma_50 is not None and snap.sma_200 is not None and len(close) >= 200:
            sma50_series = SMAIndicator(close=close, window=50).sma_indicator()
            sma200_series = SMAIndicator(close=close, window=200).sma_indicator()
            if len(sma50_series) >= 2 and len(sma200_series) >= 2:
                prev_50 = _safe_float(sma50_series.iloc[-2])
                prev_200 = _safe_float(sma200_series.iloc[-2])
                if prev_50 is not None and prev_200 is not None:
                    if prev_50 <= prev_200 and snap.sma_50 > snap.sma_200:
                        snap.golden_cross = True
                    elif prev_50 >= prev_200 and snap.sma_50 < snap.sma_200:
                        snap.death_cross = True

        # EMA 9/21 crossover
        if snap.ema_9 is not None and snap.ema_21 is not None:
            ema9_series = EMAIndicator(close=close, window=9).ema_indicator()
            ema21_series = EMAIndicator(close=close, window=21).ema_indicator()
            if len(ema9_series) >= 2 and len(ema21_series) >= 2:
                prev_9 = _safe_float(ema9_series.iloc[-2])
                prev_21 = _safe_float(ema21_series.iloc[-2])
                if prev_9 is not None and prev_21 is not None:
                    if prev_9 <= prev_21 and snap.ema_9 > snap.ema_21:
                        snap.ema_crossover = "bullish"
                    elif prev_9 >= prev_21 and snap.ema_9 < snap.ema_21:
                        snap.ema_crossover = "bearish"
    except Exception as e:
        snap.errors.append(f"MA: {e}")

    # Volume
    snap.volume_ratio = curr_volume / avg_vol_20 if avg_vol_20 > 0 else 0
    snap.volume_spike = snap.volume_ratio >= 2.0

    # VWAP (from intraday data)
    try:
        intraday = get_intraday_data(ticker)
        if intraday is not None and len(intraday) > 0:
            tp = (intraday["High"] + intraday["Low"] + intraday["Close"]) / 3
            cum_tp_vol = (tp * intraday["Volume"]).cumsum()
            cum_vol = intraday["Volume"].cumsum()
            vwap_series = cum_tp_vol / cum_vol
            snap.vwap = _safe_float(vwap_series.iloc[-1])
    except Exception as e:
        snap.errors.append(f"VWAP: {e}")

    # Bollinger Bands
    try:
        bb = BollingerBands(close=close, window=20, window_dev=2)
        snap.bb_upper = _safe_float(bb.bollinger_hband().iloc[-1])
        snap.bb_middle = _safe_float(bb.bollinger_mavg().iloc[-1])
        snap.bb_lower = _safe_float(bb.bollinger_lband().iloc[-1])

        # Squeeze: bandwidth narrowing
        bw = bb.bollinger_wband()
        if len(bw) >= 20:
            recent_bw = float(bw.iloc[-1]) if not pd.isna(bw.iloc[-1]) else None
            avg_bw = float(bw.tail(20).mean())
            if recent_bw is not None and avg_bw > 0:
                snap.bb_squeeze = recent_bw < avg_bw * 0.75

        # Lower band bounce: price was near/below lower band recently and now moving up
        if snap.bb_lower is not None and len(close) >= 3:
            recent_low = float(low.iloc[-3:].min())
            if recent_low <= snap.bb_lower * 1.01 and price > snap.bb_lower:
                snap.bb_lower_bounce = True
    except Exception as e:
        snap.errors.append(f"BB: {e}")

    return snap


def compute_extended_indicators(ticker: str) -> tuple[IndicatorSnapshot | None, TrendAnalysis | None]:
    """Compute all indicators plus multi-timeframe trend analysis.

    Returns (snap, trend) where either can be None if data is unavailable.
    """
    snap = compute_indicators(ticker)
    if snap is None:
        return None, None

    daily_df = get_daily_data(ticker)
    weekly_df = get_weekly_data(ticker)
    monthly_df = get_monthly_data(ticker)
    trend = analyze_trend(daily_df, weekly_df, monthly_df)
    return snap, trend


def _safe_float(val) -> float | None:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
