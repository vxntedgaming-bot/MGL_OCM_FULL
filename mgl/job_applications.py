"""Helpers for the existing ClubApplication flow. No second job system."""

GAMES_PER_WEEK_CHOICES = ("1", "2", "3", "4", "5+")
JOBS_DISCORD_INVITE = "https://discord.gg/Jmf29wBafP"


def parse_club_application(post):
    gamertag = (post.get("gamertag") or "").strip()
    discord_id = (post.get("discord_id") or "").strip()
    discord_username = (post.get("discord_username") or discord_id or "").strip()
    games_per_week = (post.get("games_per_week") or "").strip()
    referred_by = (post.get("referred_by") or "").strip()
    new_gen = (post.get("new_gen_confirmed") or "").strip().lower() in {
        "on",
        "1",
        "true",
        "yes",
    }
    errors = []
    if not gamertag:
        errors.append("EA ID / Gamertag is required.")
    if discord_id and not discord_id.isdigit():
        errors.append("Discord User ID must be numeric, not a username.")
    if not discord_username:
        errors.append("Discord User ID is required.")
    if games_per_week not in GAMES_PER_WEEK_CHOICES:
        errors.append("Games per week is required.")
    if not new_gen:
        errors.append("New gen confirmation is required.")
    return {
        "gamertag": gamertag,
        "discord_username": discord_username,
        "games_per_week": games_per_week,
        "referred_by": referred_by,
        "new_gen_confirmed": new_gen,
        "errors": errors,
    }
