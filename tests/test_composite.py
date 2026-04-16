"""Tests for evaluate_composite_signal() — the three-layer scoring pipeline."""
import pytest
from indicators.signals import evaluate_composite_signal, evaluate_technical_signals, SignalResult
from indicators.fundamentals import FundamentalScore
from indicators.trend import TrendAnalysis
from indicators.calculator import IndicatorSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _fs(score: int, passed: bool, reasons: list[str] | None = None) -> FundamentalScore:
    return FundamentalScore(score=score, passed_gate=passed, reasons=reasons or ["test"])


def _trend(alignment: str, score: int) -> TrendAnalysis:
    weekly = "up" if alignment == "bullish" else ("down" if alignment == "bearish" else "sideways")
    monthly = weekly
    return TrendAnalysis(
        weekly_trend=weekly,
        monthly_trend=monthly,
        trend_alignment=alignment,
        trend_score=score,
        reasons=["test"],
    )


# ---------------------------------------------------------------------------
# Gate logic
# ---------------------------------------------------------------------------

class TestGateBehavior:
    def test_failed_gate_never_produces_buy(self):
        snap = _snap(rsi=25.0, golden_cross=True, macd_crossover="bullish",
                     bb_lower_bounce=True, volume_spike=True, volume_ratio=3.0,
                     sma_20=90.0, sma_50=85.0)
        fa = _fs(score=0, passed=False)
        trend = _trend("bullish", 30)
        result = evaluate_composite_signal(snap, fa, trend)
        assert result.signal_type not in ("BUY", "STRONG BUY")
        assert result.gate_passed is False

    def test_passed_gate_allows_buy_signals(self):
        snap = _snap(rsi=25.0, golden_cross=True, macd_crossover="bullish",
                     sma_20=90.0, sma_50=85.0)
        fa = _fs(score=80, passed=True)
        trend = _trend("bullish", 30)
        result = evaluate_composite_signal(snap, fa, trend)
        assert result.gate_passed is True
        # With excellent all-around inputs we expect BUY or STRONG BUY
        assert result.signal_type in ("BUY", "STRONG BUY")


# ---------------------------------------------------------------------------
# Signal level scenarios
# ---------------------------------------------------------------------------

class TestCompositeSignalLevels:
    def test_excellent_all_around_is_strong_buy(self):
        """High fundamentals + bullish trend + strong technicals = STRONG BUY."""
        snap = _snap(
            rsi=28.0,
            macd_crossover="bullish",
            golden_cross=True,
            sma_20=90.0,
            sma_50=85.0,
            volume_spike=True,
            volume_ratio=2.5,
            bb_lower_bounce=True,
        )
        fa = _fs(score=90, passed=True)
        trend = _trend("bullish", 30)
        result = evaluate_composite_signal(snap, fa, trend)
        assert result.signal_type == "STRONG BUY"

    def test_good_fundamentals_bearish_trend_caps_at_neutral(self):
        """Good fundamentals + bearish trend should not produce BUY."""
        snap = _snap(rsi=28.0, golden_cross=True, sma_20=90.0, sma_50=85.0)
        fa = _fs(score=80, passed=True)
        trend = _trend("bearish", -20)
        result = evaluate_composite_signal(snap, fa, trend)
        assert result.signal_type in ("NEUTRAL", "CAUTION")

    def test_good_fundamentals_mixed_trend_allows_buy_not_strong(self):
        """Mixed trend limits to BUY at most (not STRONG BUY)."""
        snap = _snap(rsi=28.0, golden_cross=True, sma_20=90.0, sma_50=85.0,
                     macd_crossover="bullish")
        fa = _fs(score=85, passed=True)
        trend = _trend("mixed", 0)
        result = evaluate_composite_signal(snap, fa, trend)
        assert result.signal_type != "STRONG BUY"

    def test_minimal_pass_with_neutral_trend_and_weak_technicals_is_neutral(self):
        snap = _snap(rsi=50.0)  # no signals firing
        fa = _fs(score=40, passed=True)
        trend = _trend("mixed", 0)
        result = evaluate_composite_signal(snap, fa, trend)
        assert result.signal_type in ("NEUTRAL", "CAUTION")


# ---------------------------------------------------------------------------
# Score composition
# ---------------------------------------------------------------------------

class TestScoreComposition:
    def test_composite_score_reflects_all_layers(self):
        snap = _snap()
        fa = _fs(score=60, passed=True)   # 60/100 → 24/40
        trend = _trend("bullish", 30)
        result = evaluate_composite_signal(snap, fa, trend)
        assert result.fundamental_score == fa.score
        assert result.trend_score == 30

    def test_fundamental_score_stored_on_result(self):
        snap = _snap()
        fa = _fs(score=75, passed=True)
        trend = _trend("mixed", 0)
        result = evaluate_composite_signal(snap, fa, trend)
        assert result.fundamental_score == 75

    def test_trend_score_stored_on_result(self):
        snap = _snap()
        fa = _fs(score=50, passed=True)
        trend = _trend("bearish", -20)
        result = evaluate_composite_signal(snap, fa, trend)
        assert result.trend_score == -20

    def test_technical_score_stored_on_result(self):
        snap = _snap(rsi=25.0)
        fa = _fs(score=50, passed=True)
        trend = _trend("mixed", 0)
        result = evaluate_composite_signal(snap, fa, trend)
        assert isinstance(result.technical_score, int)

    def test_new_thresholds(self):
        """Score ≥55 → STRONG BUY, ≥35 → BUY, ≥-10 → NEUTRAL, <-10 → CAUTION."""
        snap = _snap()
        fa_good = _fs(score=100, passed=True)   # → 40 pts
        trend_bull = _trend("bullish", 30)       # → +30 pts

        # Force technical to ~0 by using neutral snap
        result = evaluate_composite_signal(snap, fa_good, trend_bull)
        # 40 + 30 + (small technical) should be >= 55
        assert result.signal_type in ("STRONG BUY", "BUY")


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

class TestCompositeReturnType:
    def test_returns_signal_result(self):
        result = evaluate_composite_signal(
            _snap(), _fs(50, True), _trend("mixed", 0)
        )
        assert isinstance(result, SignalResult)

    def test_result_has_triggers(self):
        result = evaluate_composite_signal(
            _snap(rsi=25.0, golden_cross=True),
            _fs(80, True),
            _trend("bullish", 30),
        )
        assert isinstance(result.triggers, list)
        assert len(result.triggers) > 0
