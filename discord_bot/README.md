# MGL Discord Bot

Install `discord.py`, set `DISCORD_TOKEN`, then configure `MGL_CHANNELS` as comma-separated `CATEGORY:CHANNEL_ID` pairs, e.g. `RESULTS:123,TRANSFER:456,AUCTION:789,FREE_AGENT:111,REWARD:222,NEWS:333`.

Run from backend with `python -m discord_bot.bot`.
The website remains the source of truth. Approved website events are written to `NewsPost`; the bot publishes them.
