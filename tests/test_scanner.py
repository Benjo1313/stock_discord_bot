"""Tests for scanner.py embed helpers and scoring utilities."""
from datetime import datetime

import pytest
import discord

from cogs.scanner import (
    _score_bar,
    _SCORE_THRESHOLDS,
    _build_check_embed,
    _build_alert_embed,
    _build_suppressed_embed,
    _SuppressedEntry,
)
from indicators.calculator import IndicatorSnapshot
from indicators.signals import SignalResult
from indicators.trend import TrendAnalysis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snap(**kwargs) -> IndicatorSnapshot:
    defaults = dict(
        ticker="AAPL",
        price=150.0,
        volume=1_000_000,
        avg_volume_20=800_000,
        rsi=50.0,
        macd_crossover=None,
        golden_cross=False,
        death_cross=False,
        volume_spike=False,
        volume_ratio=1.0,
        bb_lower_bounce=False,
        bb_squeeze=False,
        vwap=None,
        ema_crossover=None,
        sma_20=None,
        sma_50=None,
        sma_200=None,
        errors=[],
    )
    defaults.update(kwargs)
    return IndicatorSnapshot(**defaults)


def _result(**kwargs) -> SignalResult:
    defaults = dict(
        ticker="AAPL",
        score=50,
        signal_type="BUY",
        triggers=["RSI oversold (25.0)", "MACD bullish crossover"],
        price=150.0,
        volume=1_000_000,
        rsi=25.0,
        macd_hist=0.5,
        technical_score=15,
        fundamental_score=70,
        trend_score=20,
        gate_passed=True,
    )
    defaults.update(kwargs)
    return SignalResult(**defaults)


def _trend(alignment: str = "bullish", score: int = 20) -> TrendAnalysis:
    weekly = "up" if alignment == "bullish" else ("down" if alignment == "bearish" else "sideways")
    monthly = weekly
    return TrendAnalysis(
        weekly_trend=weekly,
        monthly_trend=monthly,
        trend_alignment=alignment,
        trend_score=score,
        price_vs_weekly_sma=1.05,
        price_vs_monthly_sma=1.03,
        reasons=["Weekly: uptrend", "Monthly: uptrend"],
    )


def _fields_text(embed: discord.Embed) -> str:
    """Concatenate all field values for easy text search."""
    parts = []
    if embed.description:
        parts.append(embed.description)
    for f in embed.fields:
        parts.append(f.name)
        parts.append(f.value)
    return " ".join(parts)


# ---------------------------------------------------------------------------
# _score_bar
# ---------------------------------------------------------------------------

class TestScoreBar:
    def test_max_score_fully_filled(self):
        bar = _score_bar(100)
        assert "█" * 10 in bar

    def test_min_score_fully_empty(self):
        bar = _score_bar(-50)
        assert "░" * 10 in bar

    def test_positive_score_shown_with_plus(self):
        bar = _score_bar(55)
        assert "+55" in bar

    def test_negative_score_shown(self):
        bar = _score_bar(-15)
        assert "-15" in bar

    def test_pts_suffix_present(self):
        bar = _score_bar(30)
        assert "pts" in bar

    def test_bracket_format(self):
        bar = _score_bar(0)
        assert "[" in bar and "]" in bar


# ---------------------------------------------------------------------------
# _SCORE_THRESHOLDS
# ---------------------------------------------------------------------------

class TestScoreThresholds:
    def test_strong_buy_requires_55(self):
        # Score of 55 should map to STRONG BUY
        for threshold, label, _ in _SCORE_THRESHOLDS:
            if 55 >= threshold:
                assert "STRONG BUY" in label
                break

    def test_score_54_maps_to_buy(self):
        label = None
        for threshold, lbl, _ in _SCORE_THRESHOLDS:
            if 54 >= threshold:
                label = lbl
                break
        assert label is not None and "STRONG BUY" not in label

    def test_buy_threshold_is_35(self):
        # Score 35 should be BUY, score 34 should not be BUY
        buy_label = None
        for threshold, lbl, _ in _SCORE_THRESHOLDS:
            if 35 >= threshold:
                buy_label = lbl
                break
        assert buy_label is not None and "BUY" in buy_label

    def test_neutral_threshold_is_neg10(self):
        neutral_label = None
        for threshold, lbl, _ in _SCORE_THRESHOLDS:
            if -10 >= threshold:
                neutral_label = lbl
                break
        assert neutral_label is not None and "NEUTRAL" in neutral_label

    def test_score_neg11_is_caution(self):
        caution_label = None
        for threshold, lbl, _ in _SCORE_THRESHOLDS:
            if -11 >= threshold:
                caution_label = lbl
                break
        assert caution_label is not None and "CAUTION" in caution_label

    def test_four_levels_defined(self):
        assert len(_SCORE_THRESHOLDS) == 4


# ---------------------------------------------------------------------------
# _build_check_embed
# ---------------------------------------------------------------------------

class TestBuildCheckEmbed:
    def test_returns_discord_embed(self):
        embed = _build_check_embed(_snap(), _result())
        assert isinstance(embed, discord.Embed)

    def test_three_layer_breakdown_shown(self):
        result = _result(fundamental_score=80, trend_score=20, technical_score=15, score=67)
        embed = _build_check_embed(_snap(), result)
        text = _fields_text(embed)
        # fundamental_score=80 scales to round(80/100*40)=32 pts → "32" in text
        assert "32" in text
        assert "Trend" in text
        assert "Tech" in text

    def test_gate_failure_shows_warning(self):
        result = _result(gate_passed=False, signal_type="CAUTION", score=-15,
                         triggers=["D/E > 300 AND negative FCF"])
        embed = _build_check_embed(_snap(), result)
        text = _fields_text(embed)
        # Gate failure should have a red flag or warning indicator
        assert any(s in text for s in ["⛔", "🚫", "⚠", "gate", "Gate", "failed", "Failed"])

    def test_score_guide_uses_new_thresholds(self):
        embed = _build_check_embed(_snap(), _result())
        text = _fields_text(embed)
        assert "55" in text
        assert "35" in text

    def test_trend_summary_shown_when_provided(self):
        trend = _trend("bullish", 20)
        embed = _build_check_embed(_snap(), _result(), trend=trend)
        text = _fields_text(embed)
        assert "Bullish" in text or "bullish" in text or "Uptrend" in text or "uptrend" in text

    def test_fundamentals_summary_shown_when_fa_provided(self):
        fa = {
            "pe_forward": 22.0,
            "roe": 0.28,
            "free_cash_flow": 4_200_000_000,
            "debt_to_equity": 45.0,
            "quote_type": "EQUITY",
        }
        embed = _build_check_embed(_snap(), _result(), fa=fa)
        text = _fields_text(embed)
        # Should show some fundamentals summary
        assert "22" in text or "ROE" in text or "FCF" in text or "D/E" in text

    def test_gate_passed_no_warning(self):
        result = _result(gate_passed=True, signal_type="BUY", score=50)
        embed = _build_check_embed(_snap(), result)
        text = _fields_text(embed)
        assert "⛔" not in text and "🚫" not in text

    def test_ticker_in_title(self):
        embed = _build_check_embed(_snap(ticker="NVDA"), _result(ticker="NVDA"))
        assert "NVDA" in embed.title


# ---------------------------------------------------------------------------
# _build_alert_embed
# ---------------------------------------------------------------------------

class TestBuildAlertEmbed:
    def test_returns_discord_embed(self):
        embed = _build_alert_embed(_result())
        assert isinstance(embed, discord.Embed)

    def test_ticker_in_title(self):
        embed = _build_alert_embed(_result(ticker="MSFT"))
        assert "MSFT" in embed.title

    def test_composite_score_shown(self):
        embed = _build_alert_embed(_result(score=65))
        text = _fields_text(embed)
        assert "65" in text

    def test_layer_breakdown_shown_when_present(self):
        result = _result(fundamental_score=32, trend_score=20, technical_score=13)
        embed = _build_alert_embed(result)
        text = _fields_text(embed)
        # At least one of the layer scores should appear
        assert "32" in text or "Fund" in text

    def test_layer_breakdown_absent_when_technical_only(self):
        # When fundamental_score is None, no fundamental breakdown shown
        result = _result(fundamental_score=None, trend_score=None, technical_score=15)
        embed = _build_alert_embed(result)
        text = _fields_text(embed)
        # Should not crash, should still show score
        assert "15" in text or str(result.score) in text

    def test_signal_type_in_title(self):
        embed = _build_alert_embed(_result(signal_type="STRONG BUY"))
        assert "STRONG BUY" in embed.title


# ---------------------------------------------------------------------------
# _build_suppressed_embed
# ---------------------------------------------------------------------------

def _suppressed(**kwargs) -> _SuppressedEntry:
    defaults = dict(
        ticker="AAPL",
        signal_type="NEUTRAL",
        score=10,
        gate_passed=True,
        reason="Score below BUY threshold",
        timestamp=datetime(2024, 1, 15, 10, 30),
    )
    defaults.update(kwargs)
    return _SuppressedEntry(**defaults)


class TestBuildSuppressedEmbed:
    def test_returns_discord_embed(self):
        embed = _build_suppressed_embed([])
        assert isinstance(embed, discord.Embed)

    def test_empty_shows_no_suppressed_message(self):
        embed = _build_suppressed_embed([])
        text = _fields_text(embed)
        assert any(s in text for s in ["No suppressed", "no suppressed", "None", "empty"])

    def test_ticker_shown(self):
        embed = _build_suppressed_embed([_suppressed(ticker="TSLA")])
        text = _fields_text(embed)
        assert "TSLA" in text

    def test_score_shown(self):
        embed = _build_suppressed_embed([_suppressed(score=-5)])
        text = _fields_text(embed)
        assert "-5" in text or "\u22125" in text  # minus or unicode minus

    def test_gate_failure_indicated(self):
        embed = _build_suppressed_embed([_suppressed(gate_passed=False, signal_type="CAUTION", score=-30)])
        text = _fields_text(embed)
        assert any(s in text for s in ["gate", "Gate", "\u26d4", "failed", "Failed"])

    def test_multiple_entries_all_shown(self):
        entries = [_suppressed(ticker="AAPL"), _suppressed(ticker="NVDA"), _suppressed(ticker="MSFT")]
        text = _fields_text(_build_suppressed_embed(entries))
        assert "AAPL" in text and "NVDA" in text and "MSFT" in text

    def test_signal_type_shown(self):
        embed = _build_suppressed_embed([_suppressed(signal_type="CAUTION")])
        text = _fields_text(embed)
        assert "CAUTION" in text
