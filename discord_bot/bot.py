import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
django.setup()
import discord
from discord.ext import tasks
from mgl.models import NewsPost

TOKEN=os.getenv("DISCORD_TOKEN")
CHANNEL_MAP={k:int(v) for k,v in [x.split(":",1) for x in os.getenv("MGL_CHANNELS","").split(",") if ":" in x]}
intents=discord.Intents.default()
bot=discord.Client(intents=intents)

@bot.event
async def on_ready():
    publish_news.start()
    print(f"MGL bot online as {bot.user}")

@tasks.loop(seconds=10)
async def publish_news():
    posts=list(NewsPost.objects.filter(published=True,discord_sent=False).order_by("created_at")[:10])
    for post in posts:
        cid=CHANNEL_MAP.get(post.category) or CHANNEL_MAP.get("NEWS")
        if not cid: continue
        channel=bot.get_channel(cid)
        if channel:
            await channel.send(f"**{post.title}**\n{post.body}")
            post.discord_sent=True; post.save(update_fields=["discord_sent"])

if __name__=="__main__":
    if not TOKEN: raise SystemExit("DISCORD_TOKEN is not set")
    bot.run(TOKEN)
