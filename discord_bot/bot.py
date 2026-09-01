import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
django.setup()
import discord
from discord.ext import tasks
from mgl.discord_channels import parse_channel_map, resolve_channel_id
from mgl.discord_queue import mark_discord_failed, mark_discord_sent, pending_discord_events
from mgl.models import NewsPost

TOKEN=os.getenv("DISCORD_TOKEN")
CHANNEL_RAW=os.getenv("UFL_CHANNELS") or os.getenv("MGL_CHANNELS","")
CHANNEL_MAP=parse_channel_map(CHANNEL_RAW)
intents=discord.Intents.default()
bot=discord.Client(intents=intents)

def _channel_id(key):
    return resolve_channel_id(CHANNEL_MAP, key)


@bot.event
async def on_ready():
    publish_queue.start()
    reconcile_news.start()
    print(f"UFL bot online as {bot.user}")

@tasks.loop(seconds=10)
async def publish_queue():
    """Deliver due DiscordEvent rows only. Never writes football, tokens, or locks."""
    for event in pending_discord_events(10):
        text=(event.payload or {}).get("text") or f"**{(event.payload or {}).get('title','UFL')}**"
        if event.channel_key == "DM":
            discord_id=(event.payload or {}).get("discord_id")
            if not discord_id:
                mark_discord_failed(event, "No Discord User ID on personal event")
                continue
            try:
                member=await bot.fetch_user(int(discord_id))
                await member.send(text)
                mark_discord_sent(event)
            except Exception as exc:
                mark_discord_failed(event, exc)
            continue
        cid=_channel_id(event.channel_key) or _channel_id(event.event_type)
        if not cid:
            mark_discord_failed(event, "No Discord channel configured")
            continue
        channel=bot.get_channel(cid)
        if not channel:
            mark_discord_failed(event, "Channel not found")
            continue
        try:
            await channel.send(text)
            mark_discord_sent(event)
        except Exception as exc:
            mark_discord_failed(event, exc)

@tasks.loop(seconds=20)
async def reconcile_news():
    posts=list(NewsPost.objects.filter(published=True,discord_sent=False).order_by("created_at")[:10])
    for post in posts:
        if post.discord_events.filter(status="SENT").exists():
            post.discord_sent=True
            post.save(update_fields=["discord_sent"])

if __name__=="__main__":
    if not TOKEN: raise SystemExit("DISCORD_TOKEN is not set")
    bot.run(TOKEN)
