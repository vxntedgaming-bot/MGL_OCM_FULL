import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
django.setup()
import discord
from discord.ext import tasks
from mgl.discord_queue import mark_discord_failed, mark_discord_sent, pending_discord_events
from mgl.models import NewsPost

TOKEN=os.getenv("DISCORD_TOKEN")
CHANNEL_RAW=os.getenv("UFL_CHANNELS") or os.getenv("MGL_CHANNELS","")
CHANNEL_MAP={k:int(v) for k,v in [x.split(":",1) for x in CHANNEL_RAW.split(",") if ":" in x]}
intents=discord.Intents.default()
bot=discord.Client(intents=intents)

@bot.event
async def on_ready():
    publish_queue.start()
    publish_news.start()
    print(f"UFL bot online as {bot.user}")

@tasks.loop(seconds=10)
async def publish_queue():
    for event in pending_discord_events(10):
        cid=CHANNEL_MAP.get(event.channel_key) or CHANNEL_MAP.get(event.event_type) or CHANNEL_MAP.get("NEWS")
        if not cid:
            mark_discord_failed(event, "No Discord channel configured")
            continue
        channel=bot.get_channel(cid)
        if not channel:
            mark_discord_failed(event, "Channel not found")
            continue
        text=(event.payload or {}).get("text") or f"**{(event.payload or {}).get('title','UFL')}**"
        try:
            await channel.send(text)
            mark_discord_sent(event)
        except Exception as exc:
            mark_discord_failed(event, exc)

@tasks.loop(seconds=20)
async def publish_news():
    posts=list(NewsPost.objects.filter(published=True,discord_sent=False).order_by("created_at")[:10])
    for post in posts:
        if post.discord_events.filter(status="SENT").exists():
            post.discord_sent=True
            post.save(update_fields=["discord_sent"])
            continue
        cid=CHANNEL_MAP.get(post.category) or CHANNEL_MAP.get("NEWS")
        if not cid:
            continue
        channel=bot.get_channel(cid)
        if channel:
            try:
                await channel.send(f"**{post.title}**\n{post.body}")
                post.discord_sent=True
                post.save(update_fields=["discord_sent"])
            except Exception:
                continue

if __name__=="__main__":
    if not TOKEN: raise SystemExit("DISCORD_TOKEN is not set")
    bot.run(TOKEN)
