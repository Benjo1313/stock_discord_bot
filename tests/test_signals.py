"""Tests for the refactored indicators.signals — evaluate_technical_signals()."""
import pytest
from indicators.signals import evaluate_technical_signals, SignalResult
from indicators.calculator import IndicatorSnapshot


def _snap(**kwargs) -> IndicatorSnapshot:
    defaults = dict(
        ticker="TEST",
        price=100.0,
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
    )
    defaults.update(kwargs)
    return IndicatorSnapshot(**defaults)


class TestTechnicalSignalResult:
    def test_returns_signal_result(self):
        result = evaluate_technical_signals(_snap())
        assert isinstance(result, SignalResult)

    def test_score_capped_at_30(self):
        """Max technicals should not exceed +30."""
        snap = _snap(
            rsi=25.0,  # oversold
            macd_crossover="bullish",
            golden_cross=True,
            volume_spike=True,
            volume_ratio=3.0,
            bb_lower_bounce=True,
            vwap=99.0,
            ema_crossover="bullish",
            sma_20=98.0,
            sma_50=95.0,
            sma_200=90.0,
        )
        result = evaluate_technical_signals(snap)
        assert result.score <= 30

    def test_score_floored_at_minus_20(self):
        """Worst-case technicals should not go below -20."""
        snap = _snap(
            rsi=80.0,  # overbought
            macd_crossover="bearish",
            death_cross=True,
            ema_crossover="bearish",
        )
        result = evaluate_technical_signals(snap)
        assert result.score >= -20

    def test_rsi_oversold_adds_score(self):
        baseline = evaluate_technical_signals(_snap(rsi=50.0))
        oversold = evaluate_technical_signals(_snap(rsi=25.0))
        assert oversold.score > baseline.score

    def test_rsi_overbought_subtracts_score(self):
        baseline = evaluate_technical_signals(_snap(rsi=50.0))
        overbought = evaluate_technical_signals(_snap(rsi=80.0))
        assert overbought.score < baseline.score

    def test_golden_cross_adds_score(self):
        without = evaluate_technical_signals(_snap())
        with_cross = evaluate_technical_signals(_snap(golden_cross=True, sma_50=105.0, sma_200=100.0))
        assert with_cross.score > without.score

    def test_death_cross_subtracts_score(self):
        without = evaluate_technical_signals(_snap())
        with_death = evaluate_technical_signals(_snap(death_cross=True))
        assert with_death.score < without.score

    def test_bullish_macd_adds_score(self):
        without = evaluate_technical_signals(_snap())
        with_macd = evaluate_technical_signals(_snap(macd_crossover="bullish"))
        assert with_macd.score > without.score

    def test_triggers_are_strings(self):
        result = evaluate_technical_signals(_snap(rsi=25.0, golden_cross=True))
        assert isinstance(result.triggers, list)
        assert all(isinstance(t, str) for t in result.triggers)

    def test_price_above_sma20_adds_score(self):
        without = evaluate_technical_signals(_snap(sma_20=None))
        with_sma = evaluate_technical_signals(_snap(price=100.0, sma_20=95.0))
        assert with_sma.score > without.score

    def test_price_above_sma50_adds_score(self):
        without = evaluate_technical_signals(_snap(sma_50=None))
        with_sma = evaluate_technical_signals(_snap(price=100.0, sma_50=95.0))
        assert with_sma.score > without.score


class TestSignalResultHasNewFields:
    """SignalResult should expose technical_score and gate_passed for composite."""

    def test_has_technical_score_field(self):
        result = evaluate_technical_signals(_snap())
        assert hasattr(result, "technical_score")

    def test_has_gate_passed_field(self):
        result = evaluate_technical_signals(_snap())
        assert hasattr(result, "gate_passed")

    def test_technical_score_matches_score_for_standalone(self):
        """When called standalone, technical_score == score."""
        result = evaluate_technical_signals(_snap(rsi=25.0))
        assert result.technical_score == result.score
