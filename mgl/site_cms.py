"""Website copy and site settings for Owner/Admin Site Management.

Missing rows fall back to the catalog defaults (current live wording).
Saving never creates duplicate keys. Player, fixture and token data are
never written here.
"""

from dataclasses import dataclass

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError

from accounts.models import User


@dataclass(frozen=True)
class ContentField:
    key: str
    section: str
    label: str
    kind: str
    default: str


CONTENT_FIELDS = (
    # HOME — current homepage wording
    ContentField("home.hero_title", "home", "Hero Title", "short", "COMPETE. MANAGE. WIN."),
    ContentField(
        "home.hero_subtitle",
        "home",
        "Hero Subtitle",
        "long",
        "Build your club. Manage your squad. Compete against real managers in Meta Gaming League Online Career Mode.",
    ),
    ContentField(
        "home.about_us",
        "home",
        "About Us",
        "long",
        "Premium competitive EA FC career football. Real managers. Official clubs. One squad across the website and the game.",
    ),
    ContentField(
        "home.league_intro",
        "home",
        "League Introduction",
        "long",
        "The website mirrors the manager's official MGL squad. Build it here, then take it into EA FC.",
    ),
    ContentField(
        "home.news_intro",
        "home",
        "News Introduction",
        "long",
        "Official confirmed events only. Pending submissions stay off this feed.",
    ),
    ContentField("home.join_title", "home", "Join Title", "short", "READY TO BUILD YOUR LEGACY?"),
    ContentField("home.join_text", "home", "Join Text", "long", "Join MGL and take control of your club."),
    # LEAGUES
    ContentField(
        "leagues.page_intro",
        "leagues",
        "Leagues Page Introduction",
        "long",
        "Official MGL standings. Click a club to open its squad and club page.",
    ),
    ContentField(
        "leagues.premier_description",
        "leagues",
        "Premier League Description",
        "long",
        "The top active MGL competition.",
    ),
    ContentField(
        "leagues.championship_description",
        "leagues",
        "Championship Description",
        "long",
        "Active division.",
    ),
    ContentField(
        "leagues.league_one_description",
        "leagues",
        "League One Description",
        "long",
        "Active division.",
    ),
    # JOBS
    ContentField(
        "jobs.page_intro",
        "jobs",
        "Jobs Page Introduction",
        "long",
        "Take over an official MGL club. Inspect the squad first. Owner or admin approval is required before you are appointed.",
    ),
    ContentField(
        "jobs.application_instructions",
        "jobs",
        "Application Instructions",
        "long",
        "Applications stay pending until an owner or admin appoints you. Submitting this form does not make you the manager.",
    ),
    # MARKET
    ContentField(
        "market.transfer_intro",
        "market",
        "Transfer Market Introduction",
        "long",
        "Auctions, listed club players and Free Agents. Unassigned FC26 players are a separate admin-only pool. All deals use MGL tokens.",
    ),
    ContentField(
        "market.free_agents_intro",
        "market",
        "Free Agents Introduction",
        "long",
        "Players who went unsold at auction, or were released by a club manager. Eligible managers can sign them for 0 TKN. Unassigned FC26 players are a separate pool and are not listed here.",
    ),
    ContentField(
        "market.auctions_intro",
        "market",
        "Auctions Introduction",
        "long",
        "Timers are enforced on the server. Expired auctions close even if this page is not open.",
    ),
    ContentField(
        "market.scouting_intro",
        "market",
        "Scouting Introduction",
        "long",
        "One scouting network for Bronze, Silver and Gold. Your scout level belongs to you and stays with your account if you leave a club.",
    ),
    # MY CLUB — no invented copy; these pages currently have no static intro
    ContentField("my_club.team_intro", "my_club", "My Team Introduction", "long", ""),
    ContentField("my_club.hub_intro", "my_club", "Manager Hub Introduction", "long", ""),
    # COMMUNITY
    ContentField(
        "community.h2h_intro",
        "community",
        "Head To Head Introduction",
        "long",
        "Head-to-head records will appear here after official Premier League matches are played and approved. No exhibition results are invented.",
    ),
    ContentField(
        "community.history_intro",
        "community",
        "History Introduction",
        "long",
        "Saved MGL seasons and cup history will be recorded here. Live league tables are not rewritten as past winners.",
    ),
    # NEWS
    ContentField(
        "news.newsroom_intro",
        "news",
        "Newsroom Introduction",
        "long",
        "Official news, live league activity and press conferences. Pending submissions stay off this page until they are approved.",
    ),
    ContentField(
        "news.live_activity_intro",
        "news",
        "Live Activity Introduction",
        "long",
        "Official MGL events after approval. Pending results and transfers do not appear here.",
    ),
    ContentField(
        "news.pressroom_intro",
        "news",
        "Pressroom Introduction",
        "long",
        "Manager interviews after they answer a press conference question. Pending questions appear in Notifications until submitted.",
    ),
    # RULES — current HOW IT WORKS cards
    ContentField(
        "rules.league_rules",
        "rules",
        "League Rules",
        "long",
        "Clubs start with 26 players and cannot exceed 30. Squads stay with the club.",
    ),
    ContentField(
        "rules.transfer_rules",
        "rules",
        "Transfer Rules",
        "long",
        "Unassigned FC26 players are not free. Only a no-bid auction or a club release creates a Free Agent.",
    ),
    ContentField(
        "rules.match_rules",
        "rules",
        "Match Rules",
        "long",
        "Play your released fixture, then submit the result for league office approval.",
    ),
    ContentField(
        "rules.manager_rules",
        "rules",
        "Manager Rules",
        "long",
        "Managers only control their own club. Releases and auctions follow the existing rules.",
    ),
    # FOOTER
    ContentField("footer.description", "footer", "Footer Description", "long", "Online Career Mode"),
    ContentField("footer.contact_text", "footer", "Contact Text", "long", ""),
    ContentField("footer.discord_text", "footer", "Discord Text", "short", "JOIN OUR DISCORD"),
    # SETTINGS — stored in the same table, edited on Site Settings
    ContentField("settings.site_name", "settings", "Website Name", "short", "Meta Gaming League"),
    ContentField("settings.site_tagline", "settings", "Website Tagline", "short", "Online Career Mode"),
    ContentField("settings.contact_email", "settings", "Contact Email", "email", ""),
    ContentField("settings.discord_invite_url", "settings", "Discord Invite URL", "url", ""),
    ContentField("settings.discord_display_text", "settings", "Discord Display Text", "short", "DISCORD"),
    ContentField("settings.social_x_url", "settings", "X / Twitter URL", "url", ""),
    ContentField("settings.social_youtube_url", "settings", "YouTube URL", "url", ""),
    ContentField("settings.social_instagram_url", "settings", "Instagram URL", "url", ""),
)

CATALOG = {field.key: field for field in CONTENT_FIELDS}

PUBLIC_SECTION_ORDER = (
    ("home", "HOME"),
    ("leagues", "LEAGUES"),
    ("jobs", "JOBS"),
    ("market", "MARKET"),
    ("my_club", "MY CLUB"),
    ("community", "COMMUNITY"),
    ("news", "NEWS"),
    ("rules", "RULES"),
    ("footer", "FOOTER"),
)

SETTINGS_KEYS = tuple(field.key for field in CONTENT_FIELDS if field.section == "settings")


def _clip(value, limit=500):
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def actor_label(user):
    if user is None:
        return "Someone"
    role = getattr(user, "role", "")
    if role == User.OWNER:
        return "Owner"
    if role == User.ADMIN:
        return "Admin"
    return getattr(user, "username", None) or "Someone"


def invalidate_content_cache():
    return None


def stored_value(key):
    """Return the saved value, or None if this key has never been saved."""
    from mgl.models import SiteContent

    try:
        row = SiteContent.objects.filter(key=key).only("value").first()
    except (OperationalError, ProgrammingError):
        return None
    if row is None:
        return None
    return row.value


def get_content(key, default=None):
    field = CATALOG.get(key)
    fallback = default if default is not None else (field.default if field else "")
    stored = stored_value(key)
    if stored is None:
        return fallback
    return stored


def fields_for_section(section):
    return [field for field in CONTENT_FIELDS if field.section == section]


def public_sections():
    rows = []
    for section_id, label in PUBLIC_SECTION_ORDER:
        rows.append(
            {
                "id": section_id,
                "label": label,
                "fields": fields_for_section(section_id),
            }
        )
    return rows


def settings_fields():
    return fields_for_section("settings")


def resolved_discord_invite():
    """CMS URL wins when non-empty; otherwise keep the env setting. Empty still hides buttons."""
    stored = stored_value("settings.discord_invite_url")
    if stored is not None and str(stored).strip():
        return str(stored).strip()
    return (getattr(settings, "DISCORD_INVITE_URL", "") or "").strip()


def site_chrome():
    keys = [
        "settings.site_name",
        "settings.site_tagline",
        "settings.contact_email",
        "settings.discord_invite_url",
        "settings.discord_display_text",
        "settings.social_x_url",
        "settings.social_youtube_url",
        "settings.social_instagram_url",
        "footer.description",
        "footer.contact_text",
        "footer.discord_text",
    ]
    stored = {}
    try:
        from mgl.models import SiteContent

        stored = dict(
            SiteContent.objects.filter(key__in=keys).values_list("key", "value")
        )
    except (OperationalError, ProgrammingError):
        stored = {}

    def value(key):
        if key in stored:
            return stored[key]
        field = CATALOG.get(key)
        return field.default if field else ""

    discord_stored = stored.get("settings.discord_invite_url")
    if discord_stored is not None and str(discord_stored).strip():
        discord_url = str(discord_stored).strip()
    else:
        discord_url = (getattr(settings, "DISCORD_INVITE_URL", "") or "").strip()

    return {
        "site_name": value("settings.site_name"),
        "site_tagline": value("settings.site_tagline"),
        "site_contact_email": value("settings.contact_email"),
        "discord_invite_url": discord_url,
        "discord_display_text": value("settings.discord_display_text") or "DISCORD",
        "social_x_url": value("settings.social_x_url"),
        "social_youtube_url": value("settings.social_youtube_url"),
        "social_instagram_url": value("settings.social_instagram_url"),
        "footer_description": value("footer.description"),
        "footer_contact_text": value("footer.contact_text"),
        "footer_discord_text": value("footer.discord_text") or "JOIN OUR DISCORD",
    }


def log_site_change(
    user,
    *,
    action,
    object_type,
    object_id="",
    object_label="",
    old_value="",
    new_value="",
    summary="",
):
    from mgl.models import SiteChangeLog

    SiteChangeLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        object_type=object_type,
        object_id=str(object_id or ""),
        object_label=object_label or "",
        old_value=_clip(old_value),
        new_value=_clip(new_value),
        summary=_clip(summary, 400),
    )


def save_content_fields(user, fields, posted, *, action_prefix="content"):
    """Create or update SiteContent rows for the given fields. No duplicates."""
    from mgl.models import SiteContent

    saved = []
    for field in fields:
        if field.key not in posted:
            continue
        new_value = posted.get(field.key, "")
        if new_value is None:
            new_value = ""
        else:
            new_value = str(new_value)
        row, created = SiteContent.objects.get_or_create(
            key=field.key,
            defaults={
                "section": field.section,
                "value": new_value,
                "updated_by": user,
            },
        )
        old_value = "" if created else row.value
        if created:
            saved.append(field)
            log_site_change(
                user,
                action=field.key,
                object_type="SiteContent",
                object_id=row.pk,
                object_label=field.label,
                old_value=field.default,
                new_value=new_value,
                summary=f"{actor_label(user)} changed {field.label}.",
            )
            continue
        if old_value == new_value and row.section == field.section:
            continue
        row.value = new_value
        row.section = field.section
        row.updated_by = user
        row.save(update_fields=["value", "section", "updated_by", "updated_at"])
        saved.append(field)
        log_site_change(
            user,
            action=field.key,
            object_type="SiteContent",
            object_id=row.pk,
            object_label=field.label,
            old_value=old_value,
            new_value=new_value,
            summary=f"{actor_label(user)} changed {field.label}.",
        )
    return saved
