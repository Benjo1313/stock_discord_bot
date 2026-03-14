import re
import discord
from discord.ext import commands

import db
from services.market_data import validate_ticker, get_current_price


class Watchlist(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="add")
    async def add_tickers(self, ctx: commands.Context, *tickers: str):
        """Add tickers to the watchlist. Usage: !add AAPL GOOG"""
        if not tickers:
            await ctx.send("Usage: `!add TICKER [TICKER ...]`")
            return

        results = []
        for raw in tickers:
            ticker = raw.upper().strip()
            if not re.match(r"^[A-Z]{1,5}$", ticker):
                results.append(f"**{ticker}** — invalid format")
                continue

            if not validate_ticker(ticker):
                results.append(f"**{ticker}** — not found on yfinance")
                continue

            added = await db.add_ticker(ticker, str(ctx.author))
            if added:
                results.append(f"**{ticker}** — added")
            else:
                results.append(f"**{ticker}** — already on watchlist")

        await ctx.send("\n".join(results))

    @commands.command(name="remove")
    async def remove_ticker(self, ctx: commands.Context, ticker: str):
        """Remove a ticker from the watchlist. Usage: !remove TSLA"""
        ticker = ticker.upper().strip()
        removed = await db.remove_ticker(ticker)
        if removed:
            await ctx.send(f"Removed **{ticker}** from watchlist.")
        else:
            await ctx.send(f"**{ticker}** is not on the watchlist.")

    @commands.command(name="watchlist")
    async def show_watchlist(self, ctx: commands.Context):
        """Show all watched tickers with current price and daily change."""
        tickers = await db.get_watchlist()
        if not tickers:
            await ctx.send("Watchlist is empty. Use `!add TICKER` to add one.")
            return

        embed = discord.Embed(title="Watchlist", color=discord.Color.blue())
        lines = []
        for item in tickers:
            ticker = item["ticker"]
            data = get_current_price(ticker)
            if data:
                arrow = "🟢" if data["change"] >= 0 else "🔴"
                lines.append(
                    f"{arrow} **{ticker}** — ${data['price']:.2f} "
                    f"({data['change_pct']:+.2f}%)"
                )
            else:
                lines.append(f"⚪ **{ticker}** — data unavailable")

        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        content = message.content.strip().lower()

        # "add TICKER"
        m = re.match(r"^add\s+([a-zA-Z\s]+)$", content)
        if m:
            tickers = m.group(1).upper().split()
            ctx = await self.bot.get_context(message)
            await self.add_tickers(ctx, *tickers)
            return

        # "remove TICKER"
        m = re.match(r"^remove\s+([a-zA-Z]{1,5})$", content)
        if m:
            ctx = await self.bot.get_context(message)
            await self.remove_ticker(ctx, m.group(1))
            return

        # "show watchlist" / "watchlist"
        if content in ("show watchlist", "watchlist", "list"):
            ctx = await self.bot.get_context(message)
            await self.show_watchlist(ctx)
            return


async def setup(bot: commands.Bot):
    await bot.add_cog(Watchlist(bot))
