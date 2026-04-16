import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime

import discord
from discord.ext import commands, tasks

import db
from config import (
    ALERT_CHANNEL_ID,
    SCAN_INTERVAL,
    MARKET_TZ,
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MINUTE,
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
)
from indicators.calculator import compute_indicators, compute_extended_indicators, IndicatorSnapshot
from indicators.signals import evaluate_signals, evaluate_composite_signal, SignalResult
from indicators.fundamentals import score_fundamentals, FundamentalScore
from indicators.trend import TrendAnalysis
from services.market_data import get_fundamentals

log = logging.getLogger(__name__)


@dataclass
class _SuppressedEntry:
    ticker: str
    signal_type: str
    score: int
    gate_passed: bool
    reason: str
    timestamp: datetime


# Ring buffer — keeps the last 50 suppressed signals (cleared on restart)
_suppressed_buffer: deque[_SuppressedEntry] = deque(maxlen=50)


def _is_market_hours() -> bool:
    now = datetime.now(MARKET_TZ)
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    market_open = now.replace(
        hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0
    )
    market_close = now.replace(
        hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0
    )
    return market_open <= now <= market_close


_SCORE_THRESHOLDS = [
    (55,  "🟢🟢 STRONG BUY",  "Multiple strong bullish signals aligning"),
    (35,  "🟢 BUY",           "Bullish setup with confirming indicators"),
    (-10, "⚪ NEUTRAL",        "No clear directional edge"),
    (-99, "🔴 CAUTION",        "Bearish signals present — watch carefully"),
]

def _score_bar(score: int) -> str:
    """Visual bar showing score on a -50 → 100 scale."""
    clamped = max(-50, min(100, score))
    filled = round((clamped + 50) / 150 * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"`[{bar}]` {score:+d} pts"


def _rsi_label(rsi: float) -> str:
    if rsi < 30:   return f"🟢 {rsi:.1f} — Oversold (potential reversal up)"
    if rsi < 40:   return f"🟡 {rsi:.1f} — Low (leaning bullish)"
    if rsi <= 60:  return f"⚪ {rsi:.1f} — Neutral"
    if rsi <= 70:  return f"🟡 {rsi:.1f} — High (leaning bearish)"
    return             f"🔴 {rsi:.1f} — Overbought (potential reversal down)"


def _macd_label(hist: float, crossover: str | None) -> str:
    base = f"{hist:+.4f}"
    if crossover == "bullish":  return f"🟢 {base} — Bullish crossover"
    if crossover == "bearish":  return f"🔴 {base} — Bearish crossover"
    if hist > 0:                return f"🟡 {base} — Above zero (bullish momentum)"
    return                             f"🟡 {base} — Below zero (bearish momentum)"


def _ma_label(price: float, ma: float, label: str) -> str:
    if price > ma:  return f"🟢 ${ma:.2f} — Price above {label} (bullish)"
    return              f"🔴 ${ma:.2f} — Price below {label} (bearish)"


def _volume_label(ratio: float, spike: bool) -> str:
    if spike:       return f"🟢 {ratio:.1f}x avg — Volume spike"
    if ratio >= 1:  return f"⚪ {ratio:.1f}x avg — Normal"
    return              f"🟡 {ratio:.1f}x avg — Below average"


def _vwap_label(price: float, vwap: float) -> str:
    if price > vwap:  return f"🟢 ${vwap:.2f} — Price above VWAP (intraday bullish)"
    return                f"🔴 ${vwap:.2f} — Price below VWAP (intraday bearish)"


def _bb_label(price: float, lower: float, middle: float, upper: float,
              squeeze: bool, bounce: bool) -> str:
    pct = (price - lower) / (upper - lower) * 100 if upper != lower else 50
    if bounce:   note = "🟢 Lower band bounce"
    elif squeeze: note = "🟡 Squeeze — breakout pending"
    elif pct > 90: note = "🔴 Near upper band (overbought zone)"
    elif pct < 10: note = "🟢 Near lower band (oversold zone)"
    else:          note = "⚪ Mid-band range"
    return f"{note} | L${lower:.2f} M${middle:.2f} U${upper:.2f}"


def _build_check_embed(
    snap: IndicatorSnapshot,
    result: SignalResult,
    trend: TrendAnalysis | None = None,
    fa: dict | None = None,
) -> discord.Embed:
    color_map = {
        "STRONG BUY": discord.Color.green(),
        "BUY": discord.Color.dark_green(),
        "NEUTRAL": discord.Color.greyple(),
        "CAUTION": discord.Color.red(),
    }
    embed = discord.Embed(
        title=f"{snap.ticker} Analysis",
        color=color_map.get(result.signal_type, discord.Color.greyple()),
    )

    # ── Score / verdict ───────────────────────────────────────────────────────
    for threshold, label, desc in _SCORE_THRESHOLDS:
        if result.score >= threshold:
            verdict_label = label
            verdict_desc  = desc
            break

    # Three-layer breakdown line
    breakdown_parts = []
    if result.fundamental_score is not None:
        fund_pts = round(result.fundamental_score / 100 * 40)
        breakdown_parts.append(f"Fund: {fund_pts}/40")
    if result.trend_score is not None:
        breakdown_parts.append(f"Trend: {result.trend_score:+d}/30")
    breakdown_parts.append(f"Tech: {result.technical_score:+d}/30")
    breakdown_str = " | ".join(breakdown_parts)
    if result.fundamental_score is not None:
        breakdown_str += f" | **Total: {result.score}**"

    embed.add_field(
        name="Overall Signal",
        value=f"{verdict_label}\n{_score_bar(result.score)}\n*{verdict_desc}*\n"
              f"{breakdown_str}\n"
              f"Score guide: ≥55 Strong Buy · ≥35 Buy · ≥−10 Neutral · <−10 Caution",
        inline=False,
    )

    # ── Gate failure banner ───────────────────────────────────────────────────
    if not result.gate_passed:
        gate_reasons = "\n".join(f"• {r}" for r in result.triggers[:5]) or "Fundamental gate not passed"
        embed.add_field(
            name="⛔ Fundamental Gate Failed",
            value=gate_reasons,
            inline=False,
        )

    # ── Fundamentals summary (when fa available) ──────────────────────────────
    if fa:
        fa_parts = []
        if fa.get("pe_forward") is not None:
            fa_parts.append(f"P/E {fa['pe_forward']:.0f}x")
        if fa.get("roe") is not None:
            fa_parts.append(f"ROE {fa['roe'] * 100:.0f}%")
        if fa.get("free_cash_flow") is not None:
            fa_parts.append(f"FCF {_fmt_large(fa['free_cash_flow'])}")
        if fa.get("debt_to_equity") is not None:
            fa_parts.append(f"D/E {fa['debt_to_equity']:.0f}%")
        if fa_parts:
            embed.add_field(name="Fundamentals", value=" | ".join(fa_parts), inline=False)

    # ── Price & Volume ────────────────────────────────────────────────────────
    embed.add_field(name="Price",  value=f"${snap.price:.2f}", inline=True)
    embed.add_field(
        name="Volume",
        value=_volume_label(snap.volume_ratio, snap.volume_spike),
        inline=True,
    )

    # ── Momentum ─────────────────────────────────────────────────────────────
    momentum_lines = []
    if snap.rsi is not None:
        momentum_lines.append(f"**RSI(14):** {_rsi_label(snap.rsi)}")
    if snap.macd_hist is not None:
        momentum_lines.append(f"**MACD Hist:** {_macd_label(snap.macd_hist, snap.macd_crossover)}")
    if momentum_lines:
        embed.add_field(name="Momentum", value="\n".join(momentum_lines), inline=False)

    # ── Trend (multi-timeframe + moving averages) ─────────────────────────────
    trend_lines = []
    if trend is not None:
        weekly_lbl = {"up": "Uptrend 📈", "down": "Downtrend 📉", "sideways": "Sideways ➡"}[trend.weekly_trend]
        monthly_lbl = {"up": "Uptrend 📈", "down": "Downtrend 📉", "sideways": "Sideways ➡"}[trend.monthly_trend]
        align_icon = "🟢" if trend.trend_alignment == "bullish" else ("🔴" if trend.trend_alignment == "bearish" else "🟡")
        trend_lines.append(
            f"**Multi-Timeframe:** Weekly: {weekly_lbl} | Monthly: {monthly_lbl} | "
            f"{align_icon} Aligned: {trend.trend_alignment.capitalize()}"
        )
    if snap.sma_20 is not None:
        trend_lines.append(f"**SMA20:** {_ma_label(snap.price, snap.sma_20, 'SMA20')}")
    if snap.sma_50 is not None:
        trend_lines.append(f"**SMA50:** {_ma_label(snap.price, snap.sma_50, 'SMA50')}")
    if snap.sma_200 is not None:
        trend_lines.append(f"**SMA200:** {_ma_label(snap.price, snap.sma_200, 'SMA200')}")
    if snap.ema_9 is not None and snap.ema_21 is not None:
        cross = snap.ema_crossover
        icon = "🟢" if cross == "bullish" else "🔴" if cross == "bearish" else "⚪"
        trend_lines.append(
            f"**EMA9/21:** {icon} ${snap.ema_9:.2f} / ${snap.ema_21:.2f}"
            + (" — Bullish crossover" if cross == "bullish"
               else " — Bearish crossover" if cross == "bearish"
               else (" — EMA9 > EMA21 (uptrend)" if snap.ema_9 > snap.ema_21
                     else " — EMA9 < EMA21 (downtrend)"))
        )
    if snap.golden_cross:
        trend_lines.append("🟢 **Golden Cross** — SMA50 just crossed above SMA200 (major bullish)")
    if snap.death_cross:
        trend_lines.append("🔴 **Death Cross** — SMA50 just crossed below SMA200 (major bearish)")
    if trend_lines:
        embed.add_field(name="Trend", value="\n".join(trend_lines), inline=False)

    # ── Volatility ────────────────────────────────────────────────────────────
    vol_lines = []
    if snap.vwap is not None:
        vol_lines.append(f"**VWAP:** {_vwap_label(snap.price, snap.vwap)}")
    if snap.bb_upper is not None:
        vol_lines.append(
            f"**Bollinger Bands:** {_bb_label(snap.price, snap.bb_lower, snap.bb_middle, snap.bb_upper, snap.bb_squeeze, snap.bb_lower_bounce)}"
        )
    if vol_lines:
        embed.add_field(name="Volatility", value="\n".join(vol_lines), inline=False)

    # ── Active triggers ───────────────────────────────────────────────────────
    if result.triggers:
        embed.add_field(
            name="What fired this score",
            value="\n".join(f"• {t}" for t in result.triggers),
            inline=False,
        )

    if snap.errors:
        embed.set_footer(text=f"Calc errors: {', '.join(snap.errors)}")

    return embed


def _build_alert_embed(result: SignalResult) -> discord.Embed:
    color = discord.Color.green() if result.signal_type == "STRONG BUY" else discord.Color.dark_green()
    embed = discord.Embed(
        title=f"Signal: {result.ticker} — {result.signal_type}",
        color=color,
    )
    embed.add_field(name="Score", value=str(result.score), inline=True)
    embed.add_field(name="Price", value=f"${result.price:.2f}", inline=True)
    if result.rsi is not None:
        embed.add_field(name="RSI", value=f"{result.rsi:.1f}", inline=True)
    if result.fundamental_score is not None:
        fund_pts = round(result.fundamental_score / 100 * 40)
        layer_parts = [f"Fund: {fund_pts}/40"]
        if result.trend_score is not None:
            layer_parts.append(f"Trend: {result.trend_score:+d}/30")
        layer_parts.append(f"Tech: {result.technical_score:+d}/30")
        embed.add_field(name="Score Breakdown", value=" | ".join(layer_parts), inline=False)
    embed.add_field(
        name="Triggers",
        value="\n".join(f"• {t}" for t in result.triggers) or "None",
        inline=False,
    )
    return embed


def _build_suppressed_embed(entries: list[_SuppressedEntry]) -> discord.Embed:
    embed = discord.Embed(
        title="Suppressed Signals (last scan cycles)",
        color=discord.Color.greyple(),
    )
    if not entries:
        embed.description = "No suppressed signals recorded since last restart."
        return embed

    lines = []
    for e in entries:
        gate_note = " ⛔ gate failed" if not e.gate_passed else ""
        lines.append(
            f"**{e.ticker}** [{e.signal_type}] score={e.score:+d}{gate_note}"
            f"\n  _{e.reason}_ · {e.timestamp.strftime('%H:%M')} UTC"
        )
    embed.description = "\n".join(lines)
    return embed


def _fmt_large(val: float | None) -> str:
    """Format large numbers as $1.23B / $456M / $78K."""
    if val is None:
        return "N/A"
    abs_val = abs(val)
    prefix = "-" if val < 0 else ""
    if abs_val >= 1e12:
        return f"{prefix}${abs_val/1e12:.2f}T"
    if abs_val >= 1e9:
        return f"{prefix}${abs_val/1e9:.2f}B"
    if abs_val >= 1e6:
        return f"{prefix}${abs_val/1e6:.2f}M"
    if abs_val >= 1e3:
        return f"{prefix}${abs_val/1e3:.2f}K"
    return f"{prefix}${abs_val:.2f}"


def _fmt_pct(val: float | None) -> str:
    return f"{val*100:.1f}%" if val is not None else "N/A"


def _fmt_x(val: float | None, decimals: int = 1) -> str:
    return f"{val:.{decimals}f}x" if val is not None else "N/A"


def _pe_label(pe: float | None) -> str:
    if pe is None:              return "N/A"
    if pe < 0:                  return f"🔴 {pe:.1f}x — Negative (company losing money)"
    if pe < 15:                 return f"🟢 {pe:.1f}x — Low (value territory)"
    if pe < 25:                 return f"🟡 {pe:.1f}x — Fair value"
    if pe < 40:                 return f"🟡 {pe:.1f}x — Elevated (growth premium)"
    return                             f"🔴 {pe:.1f}x — High (expensive)"


def _pb_label(pb: float | None) -> str:
    if pb is None:  return "N/A"
    if pb < 1:      return f"🟢 {pb:.2f}x — Below book (potential undervalue)"
    if pb < 3:      return f"🟡 {pb:.2f}x — Moderate"
    if pb < 6:      return f"🟡 {pb:.2f}x — Elevated"
    return                 f"🔴 {pb:.2f}x — High"


def _de_label(de: float | None) -> str:
    if de is None:  return "N/A"
    if de < 50:     return f"🟢 {de:.0f}% — Low leverage"
    if de < 150:    return f"🟡 {de:.0f}% — Moderate"
    if de < 300:    return f"🟡 {de:.0f}% — High"
    return                 f"🔴 {de:.0f}% — Very high leverage"


def _cr_label(cr: float | None) -> str:
    if cr is None:  return "N/A"
    if cr >= 2:     return f"🟢 {cr:.2f} — Strong liquidity"
    if cr >= 1:     return f"🟡 {cr:.2f} — Adequate"
    return                 f"🔴 {cr:.2f} — Below 1 (potential liquidity risk)"


def _margin_label(m: float | None, name: str) -> str:
    if m is None:   return "N/A"
    pct = m * 100
    if pct >= 20:   return f"🟢 {pct:.1f}% — Strong {name}"
    if pct >= 10:   return f"🟡 {pct:.1f}% — Moderate {name}"
    if pct >= 0:    return f"🟡 {pct:.1f}% — Thin {name}"
    return                 f"🔴 {pct:.1f}% — Negative {name}"


def _roe_label(roe: float | None) -> str:
    if roe is None: return "N/A"
    pct = roe * 100
    if pct >= 20:   return f"🟢 {pct:.1f}% — Excellent returns"
    if pct >= 10:   return f"🟡 {pct:.1f}% — Decent"
    if pct >= 0:    return f"🟡 {pct:.1f}% — Low"
    return                 f"🔴 {pct:.1f}% — Negative ROE"


def _growth_label(g: float | None, name: str) -> str:
    if g is None:   return "N/A"
    pct = g * 100
    if pct >= 20:   return f"🟢 {pct:.1f}% — Strong {name} growth"
    if pct >= 5:    return f"🟡 {pct:.1f}% — Moderate {name} growth"
    if pct >= 0:    return f"🟡 {pct:.1f}% — Slow {name} growth"
    return                 f"🔴 {pct:.1f}% — Declining {name}"


def _fcf_label(fcf: float | None) -> str:
    if fcf is None: return "N/A"
    if fcf > 0:     return f"🟢 {_fmt_large(fcf)} — Positive (healthy)"
    return                 f"🔴 {_fmt_large(fcf)} — Negative (burning cash)"


def _rec_label(rec: str | None) -> str:
    mapping = {
        "strongBuy":  "🟢 Strong Buy",
        "buy":        "🟢 Buy",
        "hold":       "🟡 Hold",
        "underperform": "🔴 Underperform",
        "sell":       "🔴 Sell",
        "strongSell": "🔴 Strong Sell",
    }
    return mapping.get(rec or "", f"⚪ {rec}" if rec else "N/A")


def _build_fundamentals_embed(ticker: str, fa: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"{ticker} — Fundamentals",
        description=(
            f"**{fa['name']}**"
            + (f"\n{fa['sector']} · {fa['industry']}" if fa.get("sector") else "")
        ),
        color=discord.Color.blue(),
    )

    # ── Valuation ─────────────────────────────────────────────────────────────
    embed.add_field(
        name="Valuation",
        value=(
            f"**Market Cap:** {_fmt_large(fa['market_cap'])}\n"
            f"**Enterprise Value:** {_fmt_large(fa['enterprise_value'])}\n"
            f"**P/E (trailing):** {_pe_label(fa['pe_trailing'])}\n"
            f"**P/E (forward):** {_pe_label(fa['pe_forward'])}\n"
            f"**P/S:** {_fmt_x(fa['ps_ratio'], 2)}\n"
            f"**P/B:** {_pb_label(fa['pb_ratio'])}\n"
            f"**EV/EBITDA:** {_fmt_x(fa['ev_ebitda'])}"
        ),
        inline=False,
    )

    # ── Earnings & Growth ─────────────────────────────────────────────────────
    eps_note = ""
    if fa["eps_trailing"] and fa["eps_forward"]:
        if fa["eps_forward"] > fa["eps_trailing"]:
            eps_note = " 🟢 (earnings expected to grow)"
        else:
            eps_note = " 🔴 (earnings expected to shrink)"
    embed.add_field(
        name="Earnings & Growth",
        value=(
            f"**EPS (trailing):** ${fa['eps_trailing']:.2f}" if fa["eps_trailing"] else "**EPS (trailing):** N/A"
        ) + "\n" + (
            f"**EPS (forward):** ${fa['eps_forward']:.2f}{eps_note}" if fa["eps_forward"] else "**EPS (forward):** N/A"
        ) + "\n" +
            f"**Earnings Growth:** {_growth_label(fa['earnings_growth'], 'earnings')}\n"
            f"**Revenue Growth:** {_growth_label(fa['revenue_growth'], 'revenue')}\n"
            f"**Revenue:** {_fmt_large(fa['total_revenue'])}",
        inline=False,
    )

    # ── Profitability ─────────────────────────────────────────────────────────
    embed.add_field(
        name="Profitability",
        value=(
            f"**Profit Margin:** {_margin_label(fa['profit_margin'], 'net margin')}\n"
            f"**Operating Margin:** {_margin_label(fa['operating_margin'], 'op. margin')}\n"
            f"**ROE:** {_roe_label(fa['roe'])}\n"
            f"**ROA:** {_roe_label(fa['roa'])}"
        ),
        inline=False,
    )

    # ── Financial Health ──────────────────────────────────────────────────────
    embed.add_field(
        name="Financial Health",
        value=(
            f"**Free Cash Flow:** {_fcf_label(fa['free_cash_flow'])}\n"
            f"**Cash:** {_fmt_large(fa['total_cash'])}\n"
            f"**Debt:** {_fmt_large(fa['total_debt'])}\n"
            f"**Debt/Equity:** {_de_label(fa['debt_to_equity'])}\n"
            f"**Current Ratio:** {_cr_label(fa['current_ratio'])}"
        ),
        inline=False,
    )

    # ── Dividends (only show if paying one) ───────────────────────────────────
    if fa.get("dividend_yield"):
        embed.add_field(
            name="Dividends",
            value=(
                f"**Yield:** {_fmt_pct(fa['dividend_yield'])}\n"
                f"**Payout Ratio:** {_fmt_pct(fa['payout_ratio'])}"
            ),
            inline=False,
        )

    # ── Analyst Consensus ─────────────────────────────────────────────────────
    if fa.get("recommendation") or fa.get("target_price"):
        analysts = f" ({fa['num_analysts']} analysts)" if fa.get("num_analysts") else ""
        target = f"${fa['target_price']:.2f}" if fa.get("target_price") else "N/A"
        embed.add_field(
            name="Analyst Consensus",
            value=(
                f"**Recommendation:** {_rec_label(fa['recommendation'])}{analysts}\n"
                f"**Price Target:** {target}"
            ),
            inline=False,
        )

    return embed


class Scanner(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.scan_loop.start()

    async def cog_unload(self):
        self.scan_loop.cancel()

    @tasks.loop(minutes=SCAN_INTERVAL)
    async def scan_loop(self):
        if not _is_market_hours():
            return
        await self._run_scan()

    @scan_loop.before_loop
    async def before_scan_loop(self):
        await self.bot.wait_until_ready()

    async def _run_scan(self, channel: discord.abc.Messageable | None = None):
        tickers = await db.get_watchlist()
        if not tickers:
            return

        alert_channel = channel
        if alert_channel is None and ALERT_CHANNEL_ID:
            alert_channel = self.bot.get_channel(ALERT_CHANNEL_ID)

        for item in tickers:
            ticker = item["ticker"]
            try:
                snap, trend = await asyncio.to_thread(compute_extended_indicators, ticker)
                if snap is None:
                    continue

                fa = await asyncio.to_thread(get_fundamentals, ticker)
                fs = score_fundamentals(fa)

                # ETFs have no earnings — skip the earnings gate, use neutral fundamentals
                if fa and fa.get("quote_type") == "ETF":
                    fs = FundamentalScore(score=50, passed_gate=True, reasons=["ETF — earnings gate skipped"])

                result = evaluate_composite_signal(snap, fs, trend)

                # Only alert on BUY or STRONG BUY
                if result.signal_type not in ("BUY", "STRONG BUY"):
                    reason = (
                        "Fundamental gate failed" if not result.gate_passed
                        else f"Score {result.score} below BUY threshold (35)"
                    )
                    log.info(
                        "Suppressed %s: %s (score=%d, gate_passed=%s)",
                        ticker, result.signal_type, result.score, result.gate_passed,
                    )
                    _suppressed_buffer.append(_SuppressedEntry(
                        ticker=ticker,
                        signal_type=result.signal_type,
                        score=result.score,
                        gate_passed=result.gate_passed,
                        reason=reason,
                        timestamp=datetime.utcnow(),
                    ))
                    continue

                # Anti-spam: skip if same signal in last 2 hours
                if await db.get_recent_signal(ticker, result.signal_type):
                    continue

                # Save signal
                await db.save_signal(
                    ticker=ticker,
                    signal_type=result.signal_type,
                    strength=result.score,
                    triggers=result.triggers,
                    price=result.price,
                    volume=result.volume,
                    rsi=result.rsi,
                    macd_hist=result.macd_hist,
                    fundamental_score=result.fundamental_score,
                    trend_score=result.trend_score,
                    technical_score=result.technical_score,
                )

                if alert_channel:
                    embed = _build_alert_embed(result)
                    await alert_channel.send(embed=embed)
            except Exception:
                log.exception(f"Error scanning {ticker}")

    @commands.command(name="scan")
    async def scan_now(self, ctx: commands.Context):
        """Force an immediate scan of all watchlist tickers."""
        await ctx.send("Scanning watchlist...")
        await self._run_scan(channel=ctx.channel)
        await ctx.send("Scan complete.")

    @commands.command(name="check")
    async def check_ticker(self, ctx: commands.Context, ticker: str):
        """Run full composite analysis on any ticker. Usage: !check NVDA"""
        ticker = ticker.upper().strip()
        async with ctx.typing():
            snap, trend = await asyncio.to_thread(compute_extended_indicators, ticker)
            if snap is None:
                await ctx.send(f"Could not fetch data for **{ticker}**.")
                return

            fa = await asyncio.to_thread(get_fundamentals, ticker)
            fs = score_fundamentals(fa)

            # ETFs have no earnings — skip the earnings gate
            if fa and fa.get("quote_type") == "ETF":
                fs = FundamentalScore(score=50, passed_gate=True, reasons=["ETF — earnings gate skipped"])

            result = evaluate_composite_signal(snap, fs, trend)
            embed = _build_check_embed(snap, result, trend=trend, fa=fa)

            if fa is None:
                embed.set_footer(text="⚠ Fundamentals unavailable — composite uses technical signals only")

            await ctx.send(embed=embed)

    @commands.command(name="fundamentals", aliases=["fa"])
    async def fundamentals(self, ctx: commands.Context, ticker: str):
        """Show fundamental financial data for a ticker. Usage: !fundamentals AAPL"""
        ticker = ticker.upper().strip()
        async with ctx.typing():
            fa = await asyncio.to_thread(get_fundamentals, ticker)
            if fa is None:
                await ctx.send(f"Could not fetch fundamentals for **{ticker}**.")
                return
            embed = _build_fundamentals_embed(ticker, fa)
            await ctx.send(embed=embed)

    @commands.command(name="signals")
    async def show_signals(self, ctx: commands.Context, ticker: str | None = None):
        """Show recent signal history. Usage: !signals [TICKER]"""
        signals = await db.get_signals(ticker=ticker, limit=15)
        if not signals:
            msg = f"No signals recorded for **{ticker}**." if ticker else "No signals recorded yet."
            await ctx.send(msg)
            return

        embed = discord.Embed(
            title=f"Signal History{f' — {ticker.upper()}' if ticker else ''}",
            color=discord.Color.blue(),
        )
        lines = []
        for s in signals:
            triggers = json.loads(s["triggers"]) if s["triggers"] else []
            trigger_str = ", ".join(triggers[:3])
            lines.append(
                f"**{s['ticker']}** [{s['signal_type']}] "
                f"score={s['strength']} @ ${s['price']:.2f} — "
                f"{s['created_at']}\n  _{trigger_str}_"
            )
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)


    @commands.command(name="suppressed")
    async def show_suppressed(self, ctx: commands.Context, limit: int = 20):
        """Show recently suppressed signals (filtered by gate or score). Usage: !suppressed [limit]"""
        entries = list(_suppressed_buffer)[-limit:]
        embed = _build_suppressed_embed(entries)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Scanner(bot))
