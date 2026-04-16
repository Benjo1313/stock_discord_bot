import asyncio
import re
import logging
from datetime import datetime, time as dt_time, timedelta

import discord
from discord.ext import commands, tasks

import db
from config import ALERT_CHANNEL_ID, MARKET_TZ
from services.market_data import get_current_price, get_daily_data
from services.market_summary import get_market_overview
from services.news import get_market_news, get_ticker_news, get_weekly_news, get_batch_ticker_news
from indicators.calculator import compute_indicators
from indicators.signals import evaluate_signals

log = logging.getLogger(__name__)

EOD_TIME = dt_time(hour=16, minute=5, tzinfo=MARKET_TZ)
FRIDAY_RECAP_TIME = dt_time(hour=16, minute=10, tzinfo=MARKET_TZ)


def _news_embed_field(headlines: list[dict], compact: bool = True) -> str:
    """Format news headlines as a field value. compact=True = title+URL only."""
    if not headlines:
        return ""
    lines = []
    for h in headlines:
        if compact:
            lines.append(f"• [{h['title']}]({h['url']})")
        else:
            snippet = h["snippet"][:120] + "…" if len(h["snippet"]) > 120 else h["snippet"]
            lines.append(f"**[{h['title']}]({h['url']})**\n{snippet}")
    return "\n".join(lines)


class Debrief(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _build_market_pulse(market_data: dict) -> str:
        """Return a 2-line compact market summary string from get_market_overview() output."""
        INDEX_ORDER = ["SPY", "QQQ", "DIA", "IWM"]
        indices = market_data.get("indices", {})

        index_parts = []
        for sym in INDEX_ORDER:
            info = indices.get(sym)
            if not info:
                continue
            arrow = "🟢" if info["change_pct"] >= 0 else "🔴"
            index_parts.append(f"{arrow} {info['name']} {info['change_pct']:+.2f}%")
        line1 = " | ".join(index_parts)

        sectors = market_data.get("sectors", {})
        sorted_sectors = sorted(sectors.items(), key=lambda x: x[1].get("change_pct", 0), reverse=True)
        top2 = sorted_sectors[:2]
        bottom2 = sorted_sectors[-2:] if len(sorted_sectors) >= 2 else []
        # avoid overlap when there are fewer than 4 sectors
        bottom2 = [s for s in bottom2 if s not in top2]

        up_parts = [f"{info['name']} {info['change_pct']:+.1f}%" for _, info in top2]
        down_parts = [f"{info['name']} {info['change_pct']:+.1f}%" for _, info in bottom2]

        line2_parts = []
        if up_parts:
            line2_parts.append("▲ " + ", ".join(up_parts))
        if down_parts:
            line2_parts.append("▼ " + ", ".join(down_parts))
        line2 = " | ".join(line2_parts)

        return f"{line1}\n{line2}" if line2 else line1

    async def cog_load(self):
        self.eod_debrief.start()
        self.friday_recap.start()

    async def cog_unload(self):
        self.eod_debrief.cancel()
        self.friday_recap.cancel()

    # ── Scheduled tasks ──────────────────────────────────────────────────────

    @tasks.loop(time=EOD_TIME)
    async def eod_debrief(self):
        now = datetime.now(MARKET_TZ)
        if now.weekday() >= 5:
            return
        channel = self.bot.get_channel(ALERT_CHANNEL_ID)
        if channel is None:
            return
        embed = await self._build_debrief_embed()
        if embed:
            await channel.send(embed=embed)
        await self._save_daily_summaries()

    @eod_debrief.before_loop
    async def before_eod(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=FRIDAY_RECAP_TIME)
    async def friday_recap(self):
        now = datetime.now(MARKET_TZ)
        if now.weekday() != 4:  # Friday only
            return
        channel = self.bot.get_channel(ALERT_CHANNEL_ID)
        if channel is None:
            return
        embeds = await self._build_weekly_embeds()
        for embed in embeds:
            await channel.send(embed=embed)

    @friday_recap.before_loop
    async def before_friday_recap(self):
        await self.bot.wait_until_ready()

    # ── Embed builders ────────────────────────────────────────────────────────

    async def _build_debrief_embed(self) -> discord.Embed | None:
        tickers = await db.get_watchlist()
        if not tickers:
            return None

        embed = discord.Embed(
            title="End-of-Day Debrief",
            color=discord.Color.gold(),
            timestamp=datetime.now(MARKET_TZ),
        )

        # Market Pulse — broad market context
        market_data = await asyncio.to_thread(get_market_overview)
        pulse_text = self._build_market_pulse(market_data)
        embed.add_field(name="Market Pulse", value=pulse_text, inline=False)

        lines = []
        signals_today = []
        for item in tickers:
            ticker = item["ticker"]
            data = await asyncio.to_thread(get_current_price, ticker)
            if data:
                arrow = "🟢" if data["change"] >= 0 else "🔴"
                lines.append(
                    f"{arrow} **{ticker}** ${data['price']:.2f} "
                    f"({data['change_pct']:+.2f}%) vol: {data['volume']:,.0f}"
                )
            snap = await asyncio.to_thread(compute_indicators, ticker)
            if snap:
                result = evaluate_signals(snap)
                if result.signal_type in ("BUY", "STRONG BUY"):
                    signals_today.append(
                        f"**{ticker}** — {result.signal_type} (score: {result.score})"
                    )

        embed.add_field(
            name="Watchlist Summary",
            value="\n".join(lines) or "No data",
            inline=False,
        )
        if signals_today:
            embed.add_field(
                name="Signals Triggered",
                value="\n".join(signals_today),
                inline=False,
            )

        # News headlines (top 3, with snippets)
        headlines = await asyncio.to_thread(get_market_news, max_results=3)
        news_text = _news_embed_field(headlines, compact=False)
        if news_text:
            embed.add_field(name="Headlines", value=news_text, inline=False)

        # Embed size guard: drop Market Pulse if total chars exceed Discord's safe limit
        if len(embed) > 5800:
            embed._fields = [f for f in embed._fields if f["name"] != "Market Pulse"]

        return embed

    async def _build_weekly_embeds(self) -> list[discord.Embed]:
        now = datetime.now(MARKET_TZ)
        # Monday of this week
        monday = now - timedelta(days=now.weekday())
        monday_open = monday.replace(hour=9, minute=30, second=0, microsecond=0)

        tickers_rows = await db.get_watchlist()
        tickers = [r["ticker"] for r in tickers_rows]

        embeds = []

        # ── Embed 1: Weekly Market Recap ──────────────────────────────────────
        market_data = await asyncio.to_thread(get_market_overview)
        index_lines = []
        for sym, info in market_data["indices"].items():
            # Use 5d yfinance data for weekly change
            df = await asyncio.to_thread(get_daily_data, sym, "5d")
            if df is not None and len(df) >= 2:
                week_open = float(df.iloc[0]["Open"])
                week_close = float(df.iloc[-1]["Close"])
                change_pct = (week_close - week_open) / week_open * 100 if week_open else 0
                arrow = "🟢" if change_pct >= 0 else "🔴"
                index_lines.append(f"{arrow} **{info['name']}** ({sym}) {change_pct:+.2f}%")

        market_embed = discord.Embed(
            title="Weekly Market Recap",
            color=discord.Color.gold(),
            timestamp=now,
        )
        if index_lines:
            market_embed.add_field(
                name="Index Performance (Week)",
                value="\n".join(index_lines),
                inline=False,
            )

        weekly_headlines = await asyncio.to_thread(get_weekly_news, max_results=8)
        news_text = _news_embed_field(weekly_headlines[:6], compact=True)
        if news_text:
            market_embed.add_field(name="Top Stories This Week", value=news_text, inline=False)

        embeds.append(market_embed)

        # ── Embed 2: Watchlist Week in Review ────────────────────────────────
        if tickers:
            watchlist_embed = discord.Embed(
                title="Watchlist — Week in Review",
                color=discord.Color.blue(),
                timestamp=now,
            )

            monday_str = monday_open.strftime("%Y-%m-%d %H:%M:%S")
            weekly_signals = await db.get_signals(limit=200)
            weekly_signals = [
                s for s in weekly_signals
                if s["created_at"] >= monday_str
            ]

            # One batch search covers all tickers (vs. N separate calls)
            ticker_news_map = await asyncio.to_thread(get_batch_ticker_news, tickers, 5, 2)

            for ticker in tickers:
                lines = []

                # Weekly price change
                df = await asyncio.to_thread(get_daily_data, ticker, "5d")
                if df is not None and len(df) >= 2:
                    week_open = float(df.iloc[0]["Open"])
                    week_close = float(df.iloc[-1]["Close"])
                    change_pct = (week_close - week_open) / week_open * 100 if week_open else 0
                    arrow = "🟢" if change_pct >= 0 else "🔴"
                    lines.append(f"{arrow} ${week_close:.2f} ({change_pct:+.2f}% this week)")

                # Signals this week
                ticker_signals = [s for s in weekly_signals if s["ticker"] == ticker]
                if ticker_signals:
                    sig_summary = ", ".join(
                        f"{s['signal_type']}@${s['price']:.2f}" for s in ticker_signals[:3]
                    )
                    lines.append(f"Signals: {sig_summary}")

                # News from batch results (no extra API call)
                for h in ticker_news_map.get(ticker, []):
                    lines.append(f"• [{h['title']}]({h['url']})")

                if lines:
                    watchlist_embed.add_field(
                        name=ticker,
                        value="\n".join(lines),
                        inline=False,
                    )

            embeds.append(watchlist_embed)

        return embeds

    async def _save_daily_summaries(self):
        tickers = await db.get_watchlist()
        today = datetime.now(MARKET_TZ).strftime("%Y-%m-%d")
        for item in tickers:
            ticker = item["ticker"]
            try:
                df = await asyncio.to_thread(get_daily_data, ticker, "5d")
                if df is None or df.empty:
                    continue
                last = df.iloc[-1]
                prev_close = float(df.iloc[-2]["Close"]) if len(df) >= 2 else float(last["Open"])
                change_pct = ((float(last["Close"]) - prev_close) / prev_close * 100) if prev_close else 0
                signals = await db.get_signals(ticker=ticker, limit=50)
                today_signals = sum(1 for s in signals if s["created_at"].startswith(today))
                await db.save_daily_summary(
                    ticker=ticker,
                    date=today,
                    open_=float(last["Open"]),
                    close=float(last["Close"]),
                    high=float(last["High"]),
                    low=float(last["Low"]),
                    volume=float(last["Volume"]),
                    change_pct=change_pct,
                    signals_triggered=today_signals,
                )
            except Exception:
                log.exception(f"Error saving daily summary for {ticker}")

    # ── Commands ──────────────────────────────────────────────────────────────

    @commands.command(name="debrief")
    async def debrief(self, ctx: commands.Context):
        """Watchlist summary with prices, volume, signals, and headlines."""
        async with ctx.typing():
            embed = await self._build_debrief_embed()
            if embed:
                await ctx.send(embed=embed)
            else:
                await ctx.send("Watchlist is empty.")

    @commands.command(name="market")
    async def market_overview(self, ctx: commands.Context):
        """Broad market overview: indices, sector performance, and market news."""
        async with ctx.typing():
            data = await asyncio.to_thread(get_market_overview)
            embed = discord.Embed(title="Market Overview", color=discord.Color.blue())

            index_lines = []
            for sym, info in data["indices"].items():
                arrow = "🟢" if info["change"] >= 0 else "🔴"
                index_lines.append(
                    f"{arrow} **{info['name']}** (${sym}) "
                    f"${info['price']:.2f} ({info['change_pct']:+.2f}%)"
                )
            embed.add_field(
                name="Indices",
                value="\n".join(index_lines) or "Unavailable",
                inline=False,
            )

            sector_lines = []
            sorted_sectors = sorted(
                data["sectors"].items(),
                key=lambda x: x[1].get("change_pct", 0),
                reverse=True,
            )
            for sym, info in sorted_sectors:
                arrow = "🟢" if info["change_pct"] >= 0 else "🔴"
                sector_lines.append(
                    f"{arrow} **{info['name']}** ({sym}) ({info['change_pct']:+.2f}%)"
                )
            embed.add_field(
                name="Sectors (best → worst)",
                value="\n".join(sector_lines) or "Unavailable",
                inline=False,
            )

            headlines = await asyncio.to_thread(get_market_news, max_results=3)
            news_text = _news_embed_field(headlines, compact=True)
            if news_text:
                embed.add_field(name="Market News", value=news_text, inline=False)

            await ctx.send(embed=embed)

    @commands.command(name="news")
    async def news(self, ctx: commands.Context, ticker: str | None = None):
        """Recent news headlines. Usage: !news [TICKER]"""
        async with ctx.typing():
            if ticker:
                ticker = ticker.upper().strip()
                headlines = await asyncio.to_thread(get_ticker_news, ticker, max_results=3)
                title = f"News — {ticker}"
                color = discord.Color.blue()
            else:
                headlines = await asyncio.to_thread(get_market_news, max_results=5)
                title = "Market News"
                color = discord.Color.blue()

            if not headlines:
                await ctx.send("No news available right now.")
                return

            embed = discord.Embed(title=title, color=color)
            for h in headlines:
                snippet = h["snippet"][:150] + "…" if len(h["snippet"]) > 150 else h["snippet"]
                embed.add_field(
                    name=h["title"][:256],
                    value=f"{snippet}\n[Read more]({h['url']})",
                    inline=False,
                )

            await ctx.send(embed=embed)

    @commands.command(name="weekly")
    async def weekly(self, ctx: commands.Context):
        """Full week recap: index performance, watchlist changes, signals, and news."""
        async with ctx.typing():
            embeds = await self._build_weekly_embeds()
            if not embeds:
                await ctx.send("No data available for weekly recap.")
                return
            for embed in embeds:
                await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        content = message.content.strip().lower()

        # "news TICKER" or "news"
        m = re.match(r"^news\s+([a-zA-Z]{1,5})$", content)
        if m:
            ctx = await self.bot.get_context(message)
            await self.news(ctx, m.group(1))
            return

        if content == "market news":
            ctx = await self.bot.get_context(message)
            await self.news(ctx)
            return


async def setup(bot: commands.Bot):
    await bot.add_cog(Debrief(bot))
