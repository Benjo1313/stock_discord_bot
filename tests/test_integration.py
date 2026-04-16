"""Integration tests: full pipeline with mocked market-data layer.

Exercises the path:
  market data (mocked) → compute_extended_indicators
    → score_fundamentals → evaluate_composite_signal
and verifies end-to-end contract properties without touching yfinance.
"""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from indicators.calculator import compute_extended_indicators
from indicators.fundamentals import score_fundamentals, FundamentalScore
from indicators.signals import evaluate_composite_signal


# ---------------------------------------------------------------------------
# Synthetic data builders
# ---------------------------------------------------------------------------

def _daily_df(n: int = 200, start: float = 100.0, end: float = 150.0) -> pd.DataFrame:
    """Steady linear-trend daily OHLCV with n rows."""
    prices = np.linspace(start, end, n)
    idx = pd.bdate_range("2022-01-01", periods=n)
    close = pd.Series(prices, index=idx, dtype=float)
    return pd.DataFrame({
        "Close": close,
        "High": close * 1.01,
        "Low": close * 0.99,
        "Volume": pd.Series([1_000_000.0] * n, index=idx),
    })


def _weekly_df(n: int = 104, trend: str = "up") -> pd.DataFrame:
    prices = np.linspace(80.0, 150.0, n) if trend == "up" else np.linspace(150.0, 80.0, n)
    idx = pd.date_range("2020-01-01", periods=n, freq="W")
    close = pd.Series(prices, index=idx, dtype=float)
    return pd.DataFrame({
        "Close": close,
        "High": close * 1.01,
        "Low": close * 0.99,
        "Volume": pd.Series([1_000_000.0] * n, index=idx),
    })


def _monthly_df(n: int = 60, trend: str = "up") -> pd.DataFrame:
    prices = np.linspace(80.0, 150.0, n) if trend == "up" else np.linspace(150.0, 80.0, n)
    idx = pd.date_range("2017-01-01", periods=n, freq="MS")
    close = pd.Series(prices, index=idx, dtype=float)
    return pd.DataFrame({
        "Close": close,
        "High": close * 1.01,
        "Low": close * 0.99,
        "Volume": pd.Series([1_000_000.0] * n, index=idx),
    })


# ---------------------------------------------------------------------------
# Fundamental data fixtures
# ---------------------------------------------------------------------------

_GOOD_FA = {
    "quote_type": "EQUITY",
    "eps_trailing": 4.5,
    "eps_forward": 5.2,
    "free_cash_flow": 5_000_000_000,
    "operating_margin": 0.24,
    "profit_margin": 0.18,
    "roe": 0.22,
    "roa": 0.12,
    "debt_to_equity": 40.0,
    "current_ratio": 2.1,
    "total_cash": 10_000_000_000,
    "total_debt": 5_000_000_000,
    "pe_forward": 18.0,
    "pb_ratio": 3.0,
    "earnings_growth": 0.15,
    "revenue_growth": 0.12,
    "total_revenue": 50_000_000_000,
    "dividend_yield": None,
    "recommendation": "buy",
    "target_price": 180.0,
    "num_analysts": 25,
    "name": "Fake Corp",
    "sector": "Technology",
    "industry": "Software",
    "market_cap": 200_000_000_000,
    "enterprise_value": 195_000_000_000,
    "pe_trailing": 22.0,
    "ps_ratio": 5.0,
    "ev_ebitda": 15.0,
    "eps_trailing": 4.5,
    "payout_ratio": None,
}

_FAILED_FA = {
    "quote_type": "EQUITY",
    "eps_trailing": -2.0,
    "eps_forward": -1.5,
    "free_cash_flow": -500_000_000,
    "operating_margin": -0.05,
    "debt_to_equity": 350.0,
    "roe": -0.10,
    "profit_margin": -0.08,
    "roa": -0.03,
    "earnings_growth": None,
    "revenue_growth": None,
    "pe_forward": None,
    "pb_ratio": None,
    "current_ratio": None,
    "total_cash": None,
    "total_debt": None,
    "name": "Distressed Corp",
    "sector": None,
    "industry": None,
    "market_cap": None,
    "enterprise_value": None,
    "pe_trailing": None,
    "ps_ratio": None,
    "ev_ebitda": None,
    "eps_trailing": -2.0,
    "dividend_yield": None,
    "payout_ratio": None,
    "recommendation": None,
    "target_price": None,
    "num_analysts": None,
    "total_revenue": None,
    "quote_type": "EQUITY",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_pipeline(daily, weekly, monthly, fa_dict):
    """Run the full indicator + composite pipeline with mocked data fetchers."""
    with (
        patch("indicators.calculator.get_daily_data", return_value=daily),
        patch("indicators.calculator.get_weekly_data", return_value=weekly),
        patch("indicators.calculator.get_monthly_data", return_value=monthly),
        patch("indicators.calculator.get_intraday_data", return_value=None),
    ):
        snap, trend = compute_extended_indicators("FAKE")

    fs = score_fundamentals(fa_dict)
    result = evaluate_composite_signal(snap, fs, trend)
    return snap, trend, fs, result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPipelineContract:
    """Verify structural contracts on the full pipeline output."""

    def test_snap_not_none_with_sufficient_data(self):
        snap, _, _, _ = _run_pipeline(
            _daily_df(), _weekly_df(), _monthly_df(), _GOOD_FA
        )
        assert snap is not None

    def test_result_has_all_score_fields(self):
        _, _, _, result = _run_pipeline(
            _daily_df(), _weekly_df(), _monthly_df(), _GOOD_FA
        )
        assert isinstance(result.fundamental_score, int)
        assert isinstance(result.trend_score, int)
        assert isinstance(result.technical_score, int)
        assert isinstance(result.score, int)

    def test_result_signal_type_is_valid(self):
        _, _, _, result = _run_pipeline(
            _daily_df(), _weekly_df(), _monthly_df(), _GOOD_FA
        )
        assert result.signal_type in ("STRONG BUY", "BUY", "NEUTRAL", "CAUTION")

    def test_result_gate_passed_matches_fundamentals(self):
        _, _, fs_good, result_good = _run_pipeline(
            _daily_df(), _weekly_df(), _monthly_df(), _GOOD_FA
        )
        assert result_good.gate_passed == fs_good.passed_gate

    def test_triggers_is_list(self):
        _, _, _, result = _run_pipeline(
            _daily_df(), _weekly_df(), _monthly_df(), _GOOD_FA
        )
        assert isinstance(result.triggers, list)


class TestGateBlocking:
    """Failed fundamental gate must prevent any BUY signal."""

    def test_gate_failure_blocks_buy_regardless_of_technicals(self):
        _, _, _, result = _run_pipeline(
            _daily_df(), _weekly_df(), _monthly_df(), _FAILED_FA
        )
        assert result.gate_passed is False
        assert result.signal_type not in ("BUY", "STRONG BUY")

    def test_gate_failure_score_fields_still_present(self):
        _, _, _, result = _run_pipeline(
            _daily_df(), _weekly_df(), _monthly_df(), _FAILED_FA
        )
        # Even for failed gate, score components should be populated
        assert result.technical_score is not None


class TestTrendInfluence:
    """Bearish multi-timeframe trend must suppress BUY signals."""

    def test_bearish_trend_with_good_fundamentals_not_buy(self):
        _, _, _, result = _run_pipeline(
            _daily_df(), _weekly_df(trend="down"), _monthly_df(trend="down"), _GOOD_FA
        )
        # Bearish trend caps at NEUTRAL or CAUTION
        assert result.signal_type in ("NEUTRAL", "CAUTION")

    def test_bullish_trend_with_good_fundamentals_is_buy_or_strong_buy(self):
        _, _, _, result = _run_pipeline(
            _daily_df(), _weekly_df(trend="up"), _monthly_df(trend="up"), _GOOD_FA
        )
        assert result.signal_type in ("BUY", "STRONG BUY")


class TestMissingData:
    """Pipeline must not crash when optional data is unavailable."""

    def test_no_weekly_data_still_returns_result(self):
        with (
            patch("indicators.calculator.get_daily_data", return_value=_daily_df()),
            patch("indicators.calculator.get_weekly_data", return_value=None),
            patch("indicators.calculator.get_monthly_data", return_value=None),
            patch("indicators.calculator.get_intraday_data", return_value=None),
        ):
            snap, trend = compute_extended_indicators("FAKE")

        assert snap is not None
        fs = score_fundamentals(_GOOD_FA)
        result = evaluate_composite_signal(snap, fs, trend)
        assert result.signal_type in ("STRONG BUY", "BUY", "NEUTRAL", "CAUTION")

    def test_none_fundamentals_still_produces_result(self):
        """score_fundamentals(None) should gate-fail gracefully."""
        _, _, fs, result = _run_pipeline(
            _daily_df(), _weekly_df(), _monthly_df(), None
        )
        assert fs.passed_gate is False
        assert result.gate_passed is False
        assert result.signal_type not in ("BUY", "STRONG BUY")

    def test_insufficient_daily_data_returns_none_snap(self):
        short_df = _daily_df(n=30)  # < 50 rows required
        with (
            patch("indicators.calculator.get_daily_data", return_value=short_df),
            patch("indicators.calculator.get_weekly_data", return_value=None),
            patch("indicators.calculator.get_monthly_data", return_value=None),
            patch("indicators.calculator.get_intraday_data", return_value=None),
        ):
            snap, trend = compute_extended_indicators("FAKE")
        assert snap is None
