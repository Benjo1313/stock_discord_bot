"""Multi-timeframe trend analysis — Layer 2 of the composite signal architecture.

Uses:
  - 20-week SMA for weekly trend direction
  - 10-month SMA for monthly trend direction

Slope is measured by comparing the current SMA value to N periods ago:
  - Weekly: 4 weeks ago
  - Monthly: 3 months ago
"""
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class TrendAnalysis:
    weekly_trend: str   # "up" | "down" | "sideways"
    monthly_trend: str  # "up" | "down" | "sideways"
    trend_alignment: str  # "bullish" | "bearish" | "mixed"
    trend_score: int    # -20 to +30
    price_vs_weekly_sma: float | None = None   # % above/below 20w SMA
    price_vs_monthly_sma: float | None = None  # % above/below 10m SMA
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WEEKLY_SMA_WINDOW = 20   # weeks ≈ 5 months (institutional level)
MONTHLY_SMA_WINDOW = 10  # months ≈ 200-day

WEEKLY_SLOPE_LOOKBACK = 4   # weeks to measure SMA slope
MONTHLY_SLOPE_LOOKBACK = 3  # months to measure SMA slope

SCORE_BULLISH = 30
SCORE_BEARISH = -20
SCORE_MIXED = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_trend(
    daily_df: pd.DataFrame,
    weekly_df: pd.DataFrame | None,
    monthly_df: pd.DataFrame | None,
) -> TrendAnalysis:
    """Compute multi-timeframe trend from daily, weekly, and monthly price data.

    Falls back to "sideways" if a timeframe's data is unavailable or too short.
    """
    reasons: list[str] = []

    weekly_trend, weekly_pct, weekly_reasons = _assess_weekly(weekly_df)
    monthly_trend, monthly_pct, monthly_reasons = _assess_monthly(monthly_df)

    reasons.extend(weekly_reasons)
    reasons.extend(monthly_reasons)

    alignment, score = _compute_alignment(weekly_trend, monthly_trend)
    reasons.append(f"Trend alignment: {alignment.title()}")

    return TrendAnalysis(
        weekly_trend=weekly_trend,
        monthly_trend=monthly_trend,
        trend_alignment=alignment,
        trend_score=score,
        price_vs_weekly_sma=weekly_pct,
        price_vs_monthly_sma=monthly_pct,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _assess_weekly(
    weekly_df: pd.DataFrame | None,
) -> tuple[str, float | None, list[str]]:
    """Return (trend, price_vs_sma_pct, reasons) for the weekly timeframe."""
    if weekly_df is None or len(weekly_df) < WEEKLY_SMA_WINDOW + WEEKLY_SLOPE_LOOKBACK:
        return "sideways", None, ["Weekly trend: insufficient data (sideways assumed)"]

    close = weekly_df["Close"]
    sma = close.rolling(window=WEEKLY_SMA_WINDOW).mean()
    current_sma = sma.iloc[-1]
    current_price = float(close.iloc[-1])

    if pd.isna(current_sma):
        return "sideways", None, ["Weekly SMA unavailable (sideways assumed)"]

    # Slope: compare current SMA to value N weeks ago
    lookback_sma = sma.iloc[-1 - WEEKLY_SLOPE_LOOKBACK]
    slope_positive = (not pd.isna(lookback_sma)) and (float(current_sma) > float(lookback_sma))

    price_above_sma = current_price > float(current_sma)
    pct = (current_price - float(current_sma)) / float(current_sma) * 100

    if price_above_sma and slope_positive:
        trend = "up"
        reasons = [f"Weekly: price {pct:+.1f}% above 20w SMA (uptrend)"]
    elif not price_above_sma and not slope_positive:
        trend = "down"
        reasons = [f"Weekly: price {pct:+.1f}% below 20w SMA (downtrend)"]
    else:
        trend = "sideways"
        reasons = [f"Weekly: price {pct:+.1f}% vs 20w SMA (sideways)"]

    return trend, round(pct, 2), reasons


def _assess_monthly(
    monthly_df: pd.DataFrame | None,
) -> tuple[str, float | None, list[str]]:
    """Return (trend, price_vs_sma_pct, reasons) for the monthly timeframe."""
    if monthly_df is None or len(monthly_df) < MONTHLY_SMA_WINDOW + MONTHLY_SLOPE_LOOKBACK:
        return "sideways", None, ["Monthly trend: insufficient data (sideways assumed)"]

    close = monthly_df["Close"]
    sma = close.rolling(window=MONTHLY_SMA_WINDOW).mean()
    current_sma = sma.iloc[-1]
    current_price = float(close.iloc[-1])

    if pd.isna(current_sma):
        return "sideways", None, ["Monthly SMA unavailable (sideways assumed)"]

    lookback_sma = sma.iloc[-1 - MONTHLY_SLOPE_LOOKBACK]
    slope_positive = (not pd.isna(lookback_sma)) and (float(current_sma) > float(lookback_sma))

    price_above_sma = current_price > float(current_sma)
    pct = (current_price - float(current_sma)) / float(current_sma) * 100

    if price_above_sma and slope_positive:
        trend = "up"
        reasons = [f"Monthly: price {pct:+.1f}% above 10m SMA (uptrend)"]
    elif not price_above_sma and not slope_positive:
        trend = "down"
        reasons = [f"Monthly: price {pct:+.1f}% below 10m SMA (downtrend)"]
    else:
        trend = "sideways"
        reasons = [f"Monthly: price {pct:+.1f}% vs 10m SMA (sideways)"]

    return trend, round(pct, 2), reasons


def _compute_alignment(weekly: str, monthly: str) -> tuple[str, int]:
    if weekly == "up" and monthly == "up":
        return "bullish", SCORE_BULLISH
    if weekly == "down" and monthly == "down":
        return "bearish", SCORE_BEARISH
    return "mixed", SCORE_MIXED
