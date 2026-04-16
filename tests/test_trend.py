"""Tests for indicators.trend — TrendAnalysis and analyze_trend()."""
import pytest
import pandas as pd
import numpy as np
from indicators.trend import TrendAnalysis, analyze_trend


# ---------------------------------------------------------------------------
# Helpers to build synthetic price DataFrames
# ---------------------------------------------------------------------------

def _make_df(prices: list[float], freq: str = "D") -> pd.DataFrame:
    """Build a minimal DataFrame from a price list (integer index — trend logic only needs .rolling/.iloc)."""
    return pd.DataFrame({"Close": pd.Series(prices, dtype=float)})


def _rising(n: int, start: float = 100.0, step: float = 1.0) -> list[float]:
    return [start + i * step for i in range(n)]


def _falling(n: int, start: float = 200.0, step: float = 1.0) -> list[float]:
    return [start - i * step for i in range(n)]


def _flat(n: int, value: float = 100.0) -> list[float]:
    return [value] * n


# ---------------------------------------------------------------------------
# Dataclass structure tests
# ---------------------------------------------------------------------------

class TestTrendAnalysisDataclass:
    def test_returns_trend_analysis_instance(self):
        daily = _make_df(_rising(250))
        weekly = _make_df(_rising(110), freq="W")
        monthly = _make_df(_rising(60), freq="ME")
        result = analyze_trend(daily, weekly, monthly)
        assert isinstance(result, TrendAnalysis)

    def test_has_required_fields(self):
        daily = _make_df(_rising(250))
        weekly = _make_df(_rising(110), freq="W")
        monthly = _make_df(_rising(60), freq="ME")
        result = analyze_trend(daily, weekly, monthly)
        assert hasattr(result, "weekly_trend")
        assert hasattr(result, "monthly_trend")
        assert hasattr(result, "trend_alignment")
        assert hasattr(result, "trend_score")
        assert hasattr(result, "price_vs_weekly_sma")
        assert hasattr(result, "price_vs_monthly_sma")
        assert hasattr(result, "reasons")

    def test_weekly_trend_valid_values(self):
        daily = _make_df(_rising(250))
        weekly = _make_df(_rising(110), freq="W")
        monthly = _make_df(_rising(60), freq="ME")
        result = analyze_trend(daily, weekly, monthly)
        assert result.weekly_trend in ("up", "down", "sideways")

    def test_monthly_trend_valid_values(self):
        daily = _make_df(_rising(250))
        weekly = _make_df(_rising(110), freq="W")
        monthly = _make_df(_rising(60), freq="ME")
        result = analyze_trend(daily, weekly, monthly)
        assert result.monthly_trend in ("up", "down", "sideways")

    def test_alignment_valid_values(self):
        daily = _make_df(_rising(250))
        weekly = _make_df(_rising(110), freq="W")
        monthly = _make_df(_rising(60), freq="ME")
        result = analyze_trend(daily, weekly, monthly)
        assert result.trend_alignment in ("bullish", "bearish", "mixed")

    def test_score_in_range(self):
        daily = _make_df(_rising(250))
        weekly = _make_df(_rising(110), freq="W")
        monthly = _make_df(_rising(60), freq="ME")
        result = analyze_trend(daily, weekly, monthly)
        assert -20 <= result.trend_score <= 30

    def test_reasons_list_of_strings(self):
        daily = _make_df(_rising(250))
        weekly = _make_df(_rising(110), freq="W")
        monthly = _make_df(_rising(60), freq="ME")
        result = analyze_trend(daily, weekly, monthly)
        assert isinstance(result.reasons, list)
        assert all(isinstance(r, str) for r in result.reasons)


# ---------------------------------------------------------------------------
# Trend direction tests
# ---------------------------------------------------------------------------

class TestTrendDirections:
    def test_rising_weekly_data_gives_up_trend(self):
        # 110 weeks of rising prices → price above 20w SMA, slope positive
        weekly = _make_df(_rising(110, start=50.0, step=1.0), freq="W")
        monthly = _make_df(_rising(60, start=50.0, step=1.0), freq="ME")
        daily = _make_df(_rising(250, start=50.0, step=0.5))
        result = analyze_trend(daily, weekly, monthly)
        assert result.weekly_trend == "up"

    def test_falling_weekly_data_gives_down_trend(self):
        weekly = _make_df(_falling(110, start=200.0, step=1.0), freq="W")
        monthly = _make_df(_falling(60, start=200.0, step=1.5), freq="ME")
        daily = _make_df(_falling(250, start=200.0, step=0.5))
        result = analyze_trend(daily, weekly, monthly)
        assert result.weekly_trend == "down"

    def test_rising_monthly_data_gives_up_trend(self):
        weekly = _make_df(_rising(110, start=50.0, step=1.0), freq="W")
        monthly = _make_df(_rising(60, start=50.0, step=1.0), freq="ME")
        daily = _make_df(_rising(250, start=50.0, step=0.5))
        result = analyze_trend(daily, weekly, monthly)
        assert result.monthly_trend == "up"

    def test_falling_monthly_data_gives_down_trend(self):
        weekly = _make_df(_falling(110, start=200.0, step=1.0), freq="W")
        monthly = _make_df(_falling(60, start=200.0, step=1.5), freq="ME")
        daily = _make_df(_falling(250, start=200.0, step=0.5))
        result = analyze_trend(daily, weekly, monthly)
        assert result.monthly_trend == "down"


# ---------------------------------------------------------------------------
# Alignment and score tests
# ---------------------------------------------------------------------------

class TestTrendAlignment:
    def test_both_up_gives_bullish_alignment(self):
        weekly = _make_df(_rising(110, start=50.0, step=1.0), freq="W")
        monthly = _make_df(_rising(60, start=50.0, step=1.0), freq="ME")
        daily = _make_df(_rising(250, start=50.0, step=0.5))
        result = analyze_trend(daily, weekly, monthly)
        assert result.trend_alignment == "bullish"
        assert result.trend_score == 30

    def test_both_down_gives_bearish_alignment(self):
        weekly = _make_df(_falling(110, start=200.0, step=1.0), freq="W")
        monthly = _make_df(_falling(60, start=200.0, step=1.5), freq="ME")
        daily = _make_df(_falling(250, start=200.0, step=0.5))
        result = analyze_trend(daily, weekly, monthly)
        assert result.trend_alignment == "bearish"
        assert result.trend_score == -20

    def test_mixed_gives_mixed_alignment_and_zero_score(self):
        # weekly up, monthly down
        weekly = _make_df(_rising(110, start=50.0, step=1.0), freq="W")
        monthly = _make_df(_falling(60, start=200.0, step=1.5), freq="ME")
        daily = _make_df(_rising(250, start=50.0, step=0.5))
        result = analyze_trend(daily, weekly, monthly)
        assert result.trend_alignment == "mixed"
        assert result.trend_score == 0


# ---------------------------------------------------------------------------
# Fallback behavior
# ---------------------------------------------------------------------------

class TestFallbacks:
    def test_none_weekly_falls_back_gracefully(self):
        daily = _make_df(_rising(250))
        monthly = _make_df(_rising(60), freq="ME")
        result = analyze_trend(daily, None, monthly)
        assert isinstance(result, TrendAnalysis)
        assert result.weekly_trend == "sideways"

    def test_none_monthly_falls_back_gracefully(self):
        daily = _make_df(_rising(250))
        weekly = _make_df(_rising(110), freq="W")
        result = analyze_trend(daily, weekly, None)
        assert isinstance(result, TrendAnalysis)
        assert result.monthly_trend == "sideways"

    def test_too_short_weekly_falls_back(self):
        daily = _make_df(_rising(250))
        weekly = _make_df(_rising(5), freq="W")   # way too short for 20w SMA
        monthly = _make_df(_rising(60), freq="ME")
        result = analyze_trend(daily, weekly, monthly)
        assert result.weekly_trend == "sideways"

    def test_too_short_monthly_falls_back(self):
        daily = _make_df(_rising(250))
        weekly = _make_df(_rising(110), freq="W")
        monthly = _make_df(_rising(3), freq="ME")  # too short for 10m SMA
        result = analyze_trend(daily, weekly, monthly)
        assert result.monthly_trend == "sideways"
