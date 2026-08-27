from discord_bot.bot import bot, TOKEN
if __name__ == "__main__":
    if not TOKEN: raise SystemExit("Set DISCORD_TOKEN first")
    bot.run(TOKEN)
