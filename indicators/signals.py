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


def evaluate_signals(snap: IndicatorSnapshot) -> SignalResult:
    score = 0
    triggers = []

    # RSI
    if snap.rsi is not None:
        if snap.rsi < 30:
            score += 20
            triggers.append(f"RSI oversold ({snap.rsi:.1f})")
        elif snap.rsi < 40:
            score += 5
            triggers.append(f"RSI low ({snap.rsi:.1f})")
        elif snap.rsi > 70:
            score -= 15
            triggers.append(f"RSI overbought ({snap.rsi:.1f})")

    # MACD crossover
    if snap.macd_crossover == "bullish":
        score += 15
        triggers.append("MACD bullish crossover")
    elif snap.macd_crossover == "bearish":
        score -= 10
        triggers.append("MACD bearish crossover")

    # Golden / death cross
    if snap.golden_cross:
        score += 20
        triggers.append("Golden cross (SMA50 > SMA200)")
    if snap.death_cross:
        score -= 20
        triggers.append("Death cross (SMA50 < SMA200)")

    # Volume spike + price direction
    if snap.volume_spike:
        daily_change = 0
        if snap.sma_20 is not None:
            daily_change = (snap.price - snap.sma_20) / snap.sma_20
        if daily_change > 0:
            score += 15
            triggers.append(f"Volume spike ({snap.volume_ratio:.1f}x) + price up")
        else:
            score -= 5
            triggers.append(f"Volume spike ({snap.volume_ratio:.1f}x) + price down")

    # Bollinger bounce
    if snap.bb_lower_bounce:
        score += 15
        triggers.append("Bollinger lower band bounce")

    # BB squeeze (potential breakout)
    if snap.bb_squeeze:
        score += 5
        triggers.append("Bollinger squeeze (potential breakout)")

    # VWAP cross
    if snap.vwap is not None:
        if snap.price > snap.vwap:
            score += 10
            triggers.append(f"Price above VWAP ({snap.vwap:.2f})")

    # EMA crossover
    if snap.ema_crossover == "bullish":
        score += 10
        triggers.append("EMA9 > EMA21 crossover")
    elif snap.ema_crossover == "bearish":
        score -= 10
        triggers.append("EMA9 < EMA21 crossover")

    # Price vs SMAs
    if snap.sma_20 is not None and snap.price > snap.sma_20:
        score += 10
        triggers.append(f"Price > SMA20 ({snap.sma_20:.2f})")
    if snap.sma_50 is not None and snap.price > snap.sma_50:
        score += 10
        triggers.append(f"Price > SMA50 ({snap.sma_50:.2f})")

    # Determine signal type
    if score >= 40:
        signal_type = "STRONG BUY"
    elif score >= 25:
        signal_type = "BUY"
    elif score >= -15:
        signal_type = "NEUTRAL"
    else:
        signal_type = "CAUTION"

    return SignalResult(
        ticker=snap.ticker,
        score=score,
        signal_type=signal_type,
        triggers=triggers,
        price=snap.price,
        volume=snap.volume,
        rsi=snap.rsi,
        macd_hist=snap.macd_hist,
    )
