"""Signal evaluation — three-layer composite scoring architecture.

Layer weights:
  Fundamentals  0-40 pts  (scaled from 0-100 FundamentalScore.score)
  Trend        -20 to +30 pts  (from TrendAnalysis.trend_score)
  Technicals   -20 to +30 pts  (reweighted, capped)

Composite thresholds:
  STRONG BUY  ≥ 55
  BUY         ≥ 35
  NEUTRAL     ≥ -10
  CAUTION     < -10
"""
from dataclasses import dataclass, field

from indicators.calculator import IndicatorSnapshot


@dataclass
class SignalResult:
    ticker: str
    score: int
    signal_type: str  # "STRONG BUY", "BUY", "NEUTRAL", "CAUTION"
    triggers: list[str] = field(default_factory=list)
    price: float = 0.0
    volume: float = 0.0
    rsi: float | None = None
    macd_hist: float | None = None
    # Per-layer scores (populated by composite; technical-only fills technical_score)
    technical_score: int = 0
    fundamental_score: int | None = None
    trend_score: int | None = None
    gate_passed: bool = True


# ---------------------------------------------------------------------------
# Technical scoring weights (reweighted from original; cap ±30/−20)
# ---------------------------------------------------------------------------

_TECH_MAX = 30
_TECH_MIN = -20


def evaluate_technical_signals(snap: IndicatorSnapshot) -> SignalResult:
    """Score purely on technical indicators (Layer 3).

    Returns a SignalResult where:
      - score = technical_score (capped to -20…+30)
      - signal_type uses the composite thresholds for consistency
      - technical_score == score
      - gate_passed = True (technical layer never blocks)
    """
    raw, triggers = _compute_technical_score(snap)
    score = max(_TECH_MIN, min(_TECH_MAX, raw))
    signal_type = _classify(score)
    return SignalResult(
        ticker=snap.ticker,
        score=score,
        signal_type=signal_type,
        triggers=triggers,
        price=snap.price,
        volume=snap.volume,
        rsi=snap.rsi,
        macd_hist=snap.macd_hist,
        technical_score=score,
        fundamental_score=None,
        trend_score=None,
        gate_passed=True,
    )


def evaluate_composite_signal(
    snap: IndicatorSnapshot,
    fundamental_score,   # FundamentalScore (avoid circular import with type-hint only)
    trend_analysis,      # TrendAnalysis
) -> SignalResult:
    """Combine all three layers into a composite SignalResult.

    Gate logic:
      - fundamental gate failed  → NEUTRAL/CAUTION only, no BUY
      - bearish trend alignment  → suppress BUY and STRONG BUY
      - mixed trend alignment    → suppress STRONG BUY
    """
    triggers: list[str] = []

    # --- Layer 1: Fundamentals (0-40 pts, scaled from 0-100) ----------------
    gate_passed = fundamental_score.passed_gate
    fund_pts = round(fundamental_score.score / 100 * 40) if gate_passed else 0
    if not gate_passed:
        triggers.extend(fundamental_score.reasons)
    else:
        triggers.append(f"Fundamentals: {fundamental_score.score}/100 → {fund_pts}/40 pts")

    # --- Layer 2: Trend (-20 to +30 pts) ------------------------------------
    trend_pts = trend_analysis.trend_score
    triggers.extend(trend_analysis.reasons)

    # --- Layer 3: Technical (-20 to +30 pts) --------------------------------
    raw_tech, tech_triggers = _compute_technical_score(snap)
    tech_pts = max(_TECH_MIN, min(_TECH_MAX, raw_tech))
    triggers.extend(tech_triggers)

    # --- Composite -----------------------------------------------------------
    composite = fund_pts + trend_pts + tech_pts

    # Gate suppression
    if not gate_passed:
        # Failed fundamental gate → cap at NEUTRAL
        signal_type = _classify(min(composite, -11))  # ensures NEUTRAL or CAUTION
    elif trend_analysis.trend_alignment == "bearish":
        # Bearish macro trend → suppress BUY signals
        signal_type = _classify(min(composite, -11))
    elif trend_analysis.trend_alignment == "mixed":
        # Mixed trend → allow BUY but not STRONG BUY (cap at 54)
        signal_type = _classify(min(composite, 54))
    else:
        signal_type = _classify(composite)

    return SignalResult(
        ticker=snap.ticker,
        score=composite,
        signal_type=signal_type,
        triggers=triggers,
        price=snap.price,
        volume=snap.volume,
        rsi=snap.rsi,
        macd_hist=snap.macd_hist,
        technical_score=tech_pts,
        fundamental_score=fundamental_score.score,
        trend_score=trend_pts,
        gate_passed=gate_passed,
    )


# Keep backward-compatible alias so existing scanner call still works
# (will be removed once scanner is updated to call composite)
def evaluate_signals(snap: IndicatorSnapshot) -> SignalResult:
    """Legacy alias → evaluate_technical_signals.  Will be removed in Phase 3."""
    return evaluate_technical_signals(snap)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_technical_score(snap: IndicatorSnapshot) -> tuple[int, list[str]]:
    """Compute raw (uncapped) technical score and triggers."""
    score = 0
    triggers: list[str] = []

    # RSI (max +10)
    if snap.rsi is not None:
        if snap.rsi < 30:
            score += 10
            triggers.append(f"RSI oversold ({snap.rsi:.1f})")
        elif snap.rsi < 40:
            score += 5
            triggers.append(f"RSI low ({snap.rsi:.1f})")
        elif snap.rsi > 70:
            score -= 10
            triggers.append(f"RSI overbought ({snap.rsi:.1f})")

    # MACD crossover (max +8)
    if snap.macd_crossover == "bullish":
        score += 8
        triggers.append("MACD bullish crossover")
    elif snap.macd_crossover == "bearish":
        score -= 8
        triggers.append("MACD bearish crossover")

    # Golden / death cross (max +15)
    if snap.golden_cross:
        score += 15
        triggers.append("Golden cross (SMA50 > SMA200)")
    if snap.death_cross:
        score -= 15
        triggers.append("Death cross (SMA50 < SMA200)")

    # Volume spike (max +5)
    if snap.volume_spike:
        daily_change = 0.0
        if snap.sma_20 is not None:
            daily_change = (snap.price - snap.sma_20) / snap.sma_20
        if daily_change >= 0:
            score += 5
            triggers.append(f"Volume spike ({snap.volume_ratio:.1f}x) + price up")
        else:
            score -= 3
            triggers.append(f"Volume spike ({snap.volume_ratio:.1f}x) + price down")

    # Bollinger bounce (max +5)
    if snap.bb_lower_bounce:
        score += 5
        triggers.append("Bollinger lower band bounce")

    # BB squeeze
    if snap.bb_squeeze:
        score += 3
        triggers.append("Bollinger squeeze (potential breakout)")

    # VWAP (max +3)
    if snap.vwap is not None:
        if snap.price > snap.vwap:
            score += 3
            triggers.append(f"Price above VWAP ({snap.vwap:.2f})")

    # EMA crossover (max +5)
    if snap.ema_crossover == "bullish":
        score += 5
        triggers.append("EMA9 > EMA21 crossover")
    elif snap.ema_crossover == "bearish":
        score -= 5
        triggers.append("EMA9 < EMA21 crossover")

    # Price vs SMAs (+3/+5)
    if snap.sma_20 is not None and snap.price > snap.sma_20:
        score += 3
        triggers.append(f"Price > SMA20 ({snap.sma_20:.2f})")
    if snap.sma_50 is not None and snap.price > snap.sma_50:
        score += 5
        triggers.append(f"Price > SMA50 ({snap.sma_50:.2f})")

    return score, triggers


def _classify(score: int) -> str:
    """Map composite score to signal type using the new thresholds."""
    if score >= 55:
        return "STRONG BUY"
    if score >= 35:
        return "BUY"
    if score >= -10:
        return "NEUTRAL"
    return "CAUTION"
