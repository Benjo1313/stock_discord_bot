"""Shared pytest fixtures for the stock_discord_bot test suite."""
import pytest
from indicators.calculator import IndicatorSnapshot


# ---------------------------------------------------------------------------
# Fundamentals fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def good_fundamentals():
    """Healthy, profitable company — should pass the gate and score well."""
    return {
        "name": "GoodCo Inc",
        "sector": "Technology",
        "industry": "Software",
        "market_cap": 50_000_000_000,
        "enterprise_value": 48_000_000_000,
        "pe_trailing": 22.0,
        "pe_forward": 18.0,
        "ps_ratio": 5.0,
        "pb_ratio": 4.0,
        "ev_ebitda": 15.0,
        "eps_trailing": 5.00,
        "eps_forward": 6.50,
        "earnings_growth": 0.20,
        "revenue_growth": 0.18,
        "profit_margin": 0.22,
        "operating_margin": 0.28,
        "roe": 0.25,
        "roa": 0.12,
        "total_revenue": 10_000_000_000,
        "free_cash_flow": 2_000_000_000,
        "total_cash": 5_000_000_000,
        "total_debt": 2_000_000_000,
        "debt_to_equity": 40.0,  # yfinance returns this as a percentage (40 = 40%)
        "current_ratio": 2.5,
        "dividend_yield": 0.01,
        "payout_ratio": 0.15,
        "target_price": 130.0,
        "recommendation": "buy",
        "num_analysts": 20,
    }


@pytest.fixture
def bad_fundamentals():
    """Distressed company — should hard-fail the gate."""
    return {
        "name": "BadCo Inc",
        "sector": "Retail",
        "industry": "Department Stores",
        "market_cap": 500_000_000,
        "enterprise_value": 2_000_000_000,
        "pe_trailing": None,
        "pe_forward": None,
        "ps_ratio": 0.3,
        "pb_ratio": 0.8,
        "ev_ebitda": None,
        "eps_trailing": -3.00,
        "eps_forward": -1.50,
        "earnings_growth": -0.40,
        "revenue_growth": -0.15,
        "profit_margin": -0.12,
        "operating_margin": -0.08,
        "roe": -0.25,
        "roa": -0.10,
        "total_revenue": 1_500_000_000,
        "free_cash_flow": -300_000_000,
        "total_cash": 100_000_000,
        "total_debt": 1_800_000_000,
        "debt_to_equity": 450.0,
        "current_ratio": 0.6,
        "dividend_yield": None,
        "payout_ratio": None,
        "target_price": 4.0,
        "recommendation": "sell",
        "num_analysts": 5,
    }


@pytest.fixture
def partial_fundamentals():
    """Partially populated dict — missing data should not trigger hard-fail."""
    return {
        "name": "PartialCo",
        "sector": None,
        "industry": None,
        "market_cap": 1_000_000_000,
        "enterprise_value": None,
        "pe_trailing": None,
        "pe_forward": None,
        "ps_ratio": None,
        "pb_ratio": None,
        "ev_ebitda": None,
        "eps_trailing": 1.50,   # positive — not a hard-fail trigger
        "eps_forward": None,
        "earnings_growth": None,
        "revenue_growth": None,
        "profit_margin": None,
        "operating_margin": None,
        "roe": None,
        "roa": None,
        "total_revenue": None,
        "free_cash_flow": None,
        "total_cash": None,
        "total_debt": None,
        "debt_to_equity": None,
        "current_ratio": None,
        "dividend_yield": None,
        "payout_ratio": None,
        "target_price": None,
        "recommendation": None,
        "num_analysts": None,
    }


# ---------------------------------------------------------------------------
# IndicatorSnapshot fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def base_snapshot():
    """A baseline IndicatorSnapshot for signal tests."""
    return IndicatorSnapshot(
        ticker="TEST",
        price=100.0,
        volume=1_000_000,
        avg_volume_20=800_000,
        rsi=50.0,
        macd_crossover=None,
        golden_cross=False,
        death_cross=False,
        volume_spike=False,
        volume_ratio=1.25,
        bb_lower_bounce=False,
        bb_squeeze=False,
        vwap=99.0,
        ema_crossover=None,
        sma_20=98.0,
        sma_50=95.0,
        sma_200=90.0,
    )
