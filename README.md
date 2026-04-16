# Stock Scanning Discord Bot

Personal Discord bot that manages a stock watchlist, scans for technical buy signals every 15 minutes during market hours, and delivers on-demand market debriefs.

## Setup

### 1. Discord Developer Portal

1. Go to https://discord.com/developers/applications
2. Click **New Application**, name it, click **Create**
3. Go to **Bot** tab → click **Reset Token** → copy the token
4. Enable **Message Content Intent** under Privileged Gateway Intents
5. Go to **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Read Message History`
6. Copy the generated URL and **paste it into your browser** — this opens a Discord OAuth page where you pick which server to add the bot to. Select your server and click **Authorize**.

### 2. Get Alert Channel ID

The bot needs a text channel in your Discord server to post automatic scan alerts and end-of-day debriefs.

1. In Discord, enable Developer Mode (User Settings → Advanced → Developer Mode)
2. Right-click the text channel you want alerts posted to → **Copy Channel ID**

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your token and channel ID
```

### 4. Install & Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## Commands

| Command | Description |
|---|---|
| `!add AAPL GOOG` | Add tickers to watchlist |
| `!remove TSLA` | Remove a ticker |
| `!watchlist` | Show watchlist with prices |
| `!scan` | Force immediate scan |
| `!check NVDA` | Run indicators on any ticker |
| `!signals [TICKER]` | Recent signal history |
| `!debrief` | Watchlist summary with market pulse (indices + sectors), prices, signals, and headlines with snippets |
| `!market` | Broad market overview + market news |
| `!news [TICKER]` | Recent news headlines (general or ticker-specific) |
| `!weekly` | Full week recap: prices, signals, and news |

Natural language also works: "add GOOG", "remove TSLA", "show watchlist", "news AAPL", "market news".

## Technical Indicators

RSI (14), MACD, SMA 20/50/200, EMA 9/21, VWAP, Bollinger Bands, Volume analysis.

Weighted scoring system: multiple confirming indicators required to trigger BUY/STRONG BUY signals.

## Auto Scanning

- Every 15 min during market hours (9:30 AM – 4:00 PM ET, Mon–Fri)
- End-of-day debrief at 4:05 PM ET (market pulse, watchlist prices, signals, and news with snippets)
- Friday weekly recap auto-posts at 4:10 PM ET
- Anti-spam: same signal suppressed for 2 hours

## Tavily News (optional)

Get a free API key at [tavily.com](https://tavily.com) (1000 searches/month free tier).
Add it to `.env` as `TAVILY_API_KEY=...`. If omitted, news commands return nothing silently — all other features still work.
