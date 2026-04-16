"""Tests for Debrief cog — _build_market_pulse and related behaviour."""
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal stubs so we can import cogs.debrief without a live Discord bot
# ---------------------------------------------------------------------------

def _make_discord_stub():
    discord = types.ModuleType("discord")

    class Color:
        @staticmethod
        def gold():
            return "gold"
        @staticmethod
        def blue():
            return "blue"

    class Embed:
        def __init__(self, **kwargs):
            self._fields = []
            self.title = kwargs.get("title", "")

        def add_field(self, *, name, value, inline=False):
            self._fields.append({"name": name, "value": value})

        def __len__(self):
            total = len(self.title)
            for f in self._fields:
                total += len(f["name"]) + len(f["value"])
            return total

    discord.Embed = Embed
    discord.Color = Color
    discord.Message = object

    ext = types.ModuleType("discord.ext")
    commands = types.ModuleType("discord.ext.commands")
    tasks_mod = types.ModuleType("discord.ext.tasks")

    # tasks.loop decorator — just returns the function unchanged
    def loop(**kwargs):
        def decorator(fn):
            fn.start = lambda: None
            fn.cancel = lambda: None
            fn.before_loop = lambda fn2: fn2
            return fn
        return decorator

    tasks_mod.loop = loop

    class Cog:
        class listener:
            def __init__(self, fn=None):
                pass
            def __call__(self, fn):
                return fn

    class Bot:
        pass

    class Context:
        pass

    commands.Cog = Cog
    commands.Bot = Bot
    commands.Context = Context

    def command(**kwargs):
        def decorator(fn):
            return fn
        return decorator

    commands.command = command

    discord.ext = ext
    ext.commands = commands
    ext.tasks = tasks_mod

    sys.modules["discord"] = discord
    sys.modules["discord.ext"] = ext
    sys.modules["discord.ext.commands"] = commands
    sys.modules["discord.ext.tasks"] = tasks_mod
    return discord


def _make_stub_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


discord_stub = _make_discord_stub()

_make_stub_module("db", get_watchlist=AsyncMock(return_value=[]))
from zoneinfo import ZoneInfo

_make_stub_module(
    "config",
    ALERT_CHANNEL_ID=123,
    MARKET_TZ=ZoneInfo("US/Eastern"),
)
_make_stub_module(
    "services.market_data",
    get_current_price=MagicMock(return_value=None),
    get_daily_data=MagicMock(return_value=None),
)
_make_stub_module(
    "services.market_summary",
    get_market_overview=MagicMock(return_value={"indices": {}, "sectors": {}}),
)
_make_stub_module(
    "services.news",
    get_market_news=MagicMock(return_value=[]),
    get_ticker_news=MagicMock(return_value=[]),
    get_weekly_news=MagicMock(return_value=[]),
    get_batch_ticker_news=MagicMock(return_value={}),
)
_make_stub_module(
    "indicators.calculator",
    compute_indicators=MagicMock(return_value=None),
)
_make_stub_module(
    "indicators.signals",
    evaluate_signals=MagicMock(return_value=MagicMock(signal_type="HOLD", score=0)),
)

# Now we can safely import the module under test
from cogs.debrief import Debrief, _news_embed_field  # noqa: E402


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

FULL_MARKET_DATA = {
    "indices": {
        "SPY": {"name": "S&P 500",     "price": 500.0, "change": 4.1,  "change_pct": 0.82,  "volume": 1_000_000},
        "QQQ": {"name": "Nasdaq 100",  "price": 440.0, "change": -0.6, "change_pct": -0.14, "volume": 800_000},
        "DIA": {"name": "Dow Jones",   "price": 390.0, "change": 1.75, "change_pct": 0.45,  "volume": 500_000},
        "IWM": {"name": "Russell 2000","price": 210.0, "change": 2.35, "change_pct": 1.12,  "volume": 600_000},
    },
    "sectors": {
        "XLE":  {"name": "Energy",              "price": 92.0, "change_pct": 2.1,  "change": 1.9,  "volume": 400_000},
        "XLK":  {"name": "Technology",          "price": 210.0,"change_pct": 1.4,  "change": 2.9,  "volume": 900_000},
        "XLF":  {"name": "Financials",          "price": 40.0, "change_pct": 0.3,  "change": 0.1,  "volume": 300_000},
        "XLRE": {"name": "Real Estate",         "price": 38.0, "change_pct": -1.8, "change": -0.7, "volume": 200_000},
        "XLU":  {"name": "Utilities",           "price": 66.0, "change_pct": -0.9, "change": -0.6, "volume": 150_000},
    },
}

PARTIAL_MARKET_DATA = {
    "indices": {
        "SPY": {"name": "S&P 500", "price": 500.0, "change": 4.1, "change_pct": 0.82, "volume": 1_000_000},
        # QQQ, DIA, IWM missing
    },
    "sectors": {
        "XLE": {"name": "Energy", "price": 92.0, "change_pct": 2.1, "change": 1.9, "volume": 400_000},
        # only one sector
    },
}

EMPTY_MARKET_DATA = {"indices": {}, "sectors": {}}


# ---------------------------------------------------------------------------
# _build_market_pulse
# ---------------------------------------------------------------------------

class TestBuildMarketPulse(unittest.TestCase):

    def test_normal_data_line1_contains_all_four_indices(self):
        result = Debrief._build_market_pulse(FULL_MARKET_DATA)
        line1 = result.split("\n")[0]
        for name in ("S&P 500", "Nasdaq 100", "Dow Jones", "Russell 2000"):
            self.assertIn(name, line1, f"Missing index '{name}' in line 1")

    def test_normal_data_line1_contains_change_pct(self):
        result = Debrief._build_market_pulse(FULL_MARKET_DATA)
        line1 = result.split("\n")[0]
        self.assertIn("+0.82%", line1)
        self.assertIn("-0.14%", line1)

    def test_normal_data_line1_uses_pipe_separator(self):
        result = Debrief._build_market_pulse(FULL_MARKET_DATA)
        line1 = result.split("\n")[0]
        self.assertGreater(line1.count("|"), 0)

    def test_normal_data_line2_contains_top2_and_bottom2_sectors(self):
        result = Debrief._build_market_pulse(FULL_MARKET_DATA)
        lines = result.split("\n")
        self.assertEqual(len(lines), 2, "Expected exactly 2 lines")
        line2 = lines[1]
        # Top 2: Energy (+2.1), Technology (+1.4)
        self.assertIn("Energy", line2)
        self.assertIn("Technology", line2)
        # Bottom 2: Real Estate (-1.8), Utilities (-0.9)
        self.assertIn("Real Estate", line2)
        self.assertIn("Utilities", line2)

    def test_normal_data_line2_up_down_arrows(self):
        result = Debrief._build_market_pulse(FULL_MARKET_DATA)
        line2 = result.split("\n")[1]
        self.assertIn("▲", line2)
        self.assertIn("▼", line2)

    def test_normal_data_total_length_under_250_chars(self):
        result = Debrief._build_market_pulse(FULL_MARKET_DATA)
        self.assertLessEqual(len(result), 250, f"Output too long: {len(result)} chars")

    def test_partial_data_only_available_indices_shown(self):
        result = Debrief._build_market_pulse(PARTIAL_MARKET_DATA)
        self.assertIn("S&P 500", result)
        self.assertNotIn("Nasdaq 100", result)

    def test_partial_data_single_sector_no_crash(self):
        result = Debrief._build_market_pulse(PARTIAL_MARKET_DATA)
        self.assertIn("Energy", result)

    def test_empty_data_returns_string(self):
        result = Debrief._build_market_pulse(EMPTY_MARKET_DATA)
        self.assertIsInstance(result, str)

    def test_green_emoji_for_positive_index(self):
        result = Debrief._build_market_pulse(FULL_MARKET_DATA)
        line1 = result.split("\n")[0]
        self.assertIn("🟢", line1)

    def test_red_emoji_for_negative_index(self):
        result = Debrief._build_market_pulse(FULL_MARKET_DATA)
        line1 = result.split("\n")[0]
        self.assertIn("🔴", line1)


# ---------------------------------------------------------------------------
# _build_debrief_embed — Market Pulse field + non-compact headlines
# ---------------------------------------------------------------------------

class TestBuildDebriefEmbed(unittest.IsolatedAsyncioTestCase):

    async def _run_with_mocks(self, market_data=None, tickers=None, headlines=None):
        import cogs.debrief as debrief_mod

        if market_data is None:
            market_data = FULL_MARKET_DATA
        if tickers is None:
            tickers = [{"ticker": "SPY"}]
        if headlines is None:
            headlines = [
                {"title": "Markets rise", "url": "http://x.com", "snippet": "Stocks climbed today on strong earnings data from major tech firms."},
            ]

        with (
            patch.object(debrief_mod, "get_market_overview", return_value=market_data),
            patch("db.get_watchlist", AsyncMock(return_value=tickers)),
            patch.object(debrief_mod, "get_market_news", return_value=headlines),
            patch.object(debrief_mod, "get_current_price", return_value={"price": 500.0, "change": 1.0, "change_pct": 0.2, "volume": 1_000_000}),
            patch.object(debrief_mod, "compute_indicators", return_value=None),
        ):
            bot = MagicMock()
            cog = Debrief(bot)
            return await cog._build_debrief_embed()

    async def test_market_pulse_field_is_first(self):
        embed = await self._run_with_mocks()
        self.assertEqual(embed._fields[0]["name"], "Market Pulse")

    async def test_watchlist_summary_is_second(self):
        embed = await self._run_with_mocks()
        self.assertEqual(embed._fields[1]["name"], "Watchlist Summary")

    async def test_market_pulse_value_contains_sp500(self):
        embed = await self._run_with_mocks()
        self.assertIn("S&P 500", embed._fields[0]["value"])

    async def test_headlines_use_non_compact_format(self):
        embed = await self._run_with_mocks()
        headlines_field = next(f for f in embed._fields if f["name"] == "Headlines")
        # Non-compact format shows the snippet, not just the title+link
        self.assertIn("Stocks climbed", headlines_field["value"])

    async def test_returns_none_when_watchlist_empty(self):
        embed = await self._run_with_mocks(tickers=[])
        self.assertIsNone(embed)


# ---------------------------------------------------------------------------
# Embed size guard
# ---------------------------------------------------------------------------

class TestEmbedSizeGuard(unittest.IsolatedAsyncioTestCase):

    async def test_market_pulse_dropped_when_embed_oversized(self):
        import cogs.debrief as debrief_mod

        # Generate a watchlist large enough to push embed over 5800 chars
        big_tickers = [{"ticker": f"T{i:03d}"} for i in range(60)]

        def fat_price(ticker):
            return {"price": 123.45, "change": 0.5, "change_pct": 0.40, "volume": 9_999_999}

        with (
            patch.object(debrief_mod, "get_market_overview", return_value=FULL_MARKET_DATA),
            patch("db.get_watchlist", AsyncMock(return_value=big_tickers)),
            patch.object(debrief_mod, "get_market_news", return_value=[]),
            patch.object(debrief_mod, "get_current_price", side_effect=fat_price),
            patch.object(debrief_mod, "compute_indicators", return_value=None),
        ):
            bot = MagicMock()
            cog = Debrief(bot)
            embed = await cog._build_debrief_embed()

        if embed is not None and len(embed) > 5800:
            field_names = [f["name"] for f in embed._fields]
            self.assertNotIn("Market Pulse", field_names, "Market Pulse should be dropped when embed > 5800 chars")

    async def test_market_pulse_present_when_embed_within_limit(self):
        import cogs.debrief as debrief_mod

        with (
            patch.object(debrief_mod, "get_market_overview", return_value=FULL_MARKET_DATA),
            patch("db.get_watchlist", AsyncMock(return_value=[{"ticker": "SPY"}])),
            patch.object(debrief_mod, "get_market_news", return_value=[]),
            patch.object(debrief_mod, "get_current_price", return_value={"price": 500.0, "change": 1.0, "change_pct": 0.2, "volume": 1_000_000}),
            patch.object(debrief_mod, "compute_indicators", return_value=None),
        ):
            bot = MagicMock()
            cog = Debrief(bot)
            embed = await cog._build_debrief_embed()

        field_names = [f["name"] for f in embed._fields]
        self.assertIn("Market Pulse", field_names)
