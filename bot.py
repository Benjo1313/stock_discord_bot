import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler

import discord
from discord.ext import commands

from config import DISCORD_TOKEN, DATA_DIR
import db

# Logging setup
os.makedirs(DATA_DIR, exist_ok=True)
log_handler = RotatingFileHandler(
    os.path.join(DATA_DIR, "bot.log"),
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[log_handler, logging.StreamHandler()],
)
log = logging.getLogger("stock_bot")

COGS = [
    "cogs.watchlist",
    "cogs.scanner",
    "cogs.debrief",
]

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    log.info(f"Connected to {len(bot.guilds)} guild(s)")


async def main():
    if not DISCORD_TOKEN:
        log.error("DISCORD_TOKEN not set in .env")
        return

    await db.init_db()

    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                log.info(f"Loaded cog: {cog}")
            except Exception:
                log.exception(f"Failed to load cog: {cog}")
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
