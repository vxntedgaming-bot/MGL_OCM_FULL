"""Canonical Discord channel keys.

Channel IDs are never hardcoded. The bot reads `UFL_CHANNELS` or legacy
`MGL_CHANNELS` as `KEY:ID` pairs. None of these keys are required to exist
in the environment; missing keys fall back to NEWS.

Do not put bot tokens or invite secrets in this module.
"""

from mgl.models import NewsPost


CANONICAL_CHANNEL_KEYS = (
    "NEWS",
    "TRANSFERS",
    "AUCTIONS",
    "RECRUITMENT",
    "SCOUTING",
    "RESULTS",
    "REWARDS",
    "JOBS",
    "ANNOUNCEMENTS",
)

# Stored DiscordEvent.channel_key values and env aliases → lookup order.
CHANNEL_ALIASES = {
    "TRANSFER": ("TRANSFERS", "TRANSFER MARKET", "TRANSFER_MARKET"),
    "TRANSFERS": ("TRANSFER", "TRANSFER MARKET", "TRANSFER_MARKET"),
    "TRANSFER MARKET": ("TRANSFERS", "TRANSFER", "TRANSFER_MARKET"),
    "TRANSFER_MARKET": ("TRANSFERS", "TRANSFER", "TRANSFER MARKET"),
    "AUCTION": ("AUCTIONS",),
    "AUCTIONS": ("AUCTION",),
    "FREE AGENTS": ("FREE_AGENTS", "NEWS"),
    "FREE_AGENTS": ("FREE AGENTS", "NEWS"),
    "RESULT": ("RESULTS", "NEWS"),
    "RESULTS": ("RESULT", "NEWS"),
    "REWARD": ("REWARDS", "NEWS"),
    "REWARDS": ("REWARD", "AWARD", "NEWS"),
    "AWARD": ("REWARDS", "REWARD", "NEWS"),
    "ADMIN": ("ANNOUNCEMENTS", "NEWS"),
    "ANNOUNCEMENTS": ("ADMIN", "NEWS"),
    "JOB": ("JOBS", "NEWS"),
    "JOBS": ("JOB", "NEWS"),
    "RECRUITMENT": ("SIGNING", "NEWS"),
    "SCOUTING": ("NEWS",),
    "PRESS": ("NEWS",),
    "MATCH": ("RESULTS", "NEWS"),
    "CLUB": ("NEWS",),
    "SIGNING": ("NEWS",),
    "MANAGER": ("NEWS",),
}

# News / event category → stored channel_key. IDs stay in env.
CATEGORY_TO_CHANNEL_KEY = {
    NewsPost.RESULTS: "RESULTS",
    NewsPost.TRANSFER: "TRANSFERS",
    NewsPost.AUCTION: "AUCTIONS",
    NewsPost.FREE_AGENT: "FREE_AGENTS",
    NewsPost.PRESS: "PRESS",
    NewsPost.MANAGER: "NEWS",
    NewsPost.SIGNING: "NEWS",
    NewsPost.SCOUTING: "SCOUTING",
    NewsPost.REWARD: "REWARDS",
    "RECRUITMENT": "RECRUITMENT",
    "JOB": "JOBS",
    "ADMIN": "ANNOUNCEMENTS",
}

# Backward-compatible name used by discord_queue and older imports.
CHANNEL_FOR_CATEGORY = CATEGORY_TO_CHANNEL_KEY


def channel_key_for_category(category):
    if not category:
        return "NEWS"
    return CATEGORY_TO_CHANNEL_KEY.get(category, "NEWS")


def parse_channel_map(raw):
    """Parse `KEY:ID,KEY:ID` env text. Invalid pairs are skipped."""
    mapping = {}
    for part in (raw or "").split(","):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            continue
        try:
            mapping[key] = int(value)
        except (TypeError, ValueError):
            continue
    return mapping


def resolve_channel_id(channel_map, key):
    """Resolve a stored or canonical key against the env map. Missing → NEWS."""
    channel_map = channel_map or {}
    if not key:
        return channel_map.get("NEWS")
    if key in channel_map:
        return channel_map[key]
    for alias in CHANNEL_ALIASES.get(key, ()):
        if alias in channel_map:
            return channel_map[alias]
    return channel_map.get("NEWS")
