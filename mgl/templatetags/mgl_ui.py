from django import template

from mgl.club_urls import club_page_url as build_club_page_url
from mgl.site_cms import get_content
from players.fc26_faces import card_face_src
from teams.badges import static_badge_path


register = template.Library()


@register.simple_tag
def site_text(key, default=""):
    return get_content(key, default if default != "" else None)


@register.filter
def dict_get(mapping, key):
    if not mapping:
        return ""
    return mapping.get(key, "")


@register.filter
def league_label(league):
    if not league:
        return ""
    display = (getattr(league, "display_name", None) or "").strip()
    return display or getattr(league, "name", "") or ""


NATIONALITY_ISO = {
    "Argentina": "ar",
    "Belgium": "be",
    "Brazil": "br",
    "Croatia": "hr",
    "Denmark": "dk",
    "Egypt": "eg",
    "England": "gb-eng",
    "France": "fr",
    "Germany": "de",
    "Italy": "it",
    "Netherlands": "nl",
    "Norway": "no",
    "Poland": "pl",
    "Portugal": "pt",
    "Scotland": "gb-sct",
    "Senegal": "sn",
    "Spain": "es",
    "Sweden": "se",
    "Switzerland": "ch",
    "Turkey": "tr",
    "United States": "us",
    "Wales": "gb-wls",
    "Uruguay": "uy",
    "Colombia": "co",
    "Mexico": "mx",
    "Japan": "jp",
    "Korea Republic": "kr",
    "South Korea": "kr",
    "Morocco": "ma",
    "Nigeria": "ng",
    "Ivory Coast": "ci",
    "Côte d'Ivoire": "ci",
    "Cote d'Ivoire": "ci",
    "Austria": "at",
    "Serbia": "rs",
    "Ghana": "gh",
    "Algeria": "dz",
    "Cameroon": "cm",
    "Australia": "au",
    "Canada": "ca",
    "Chile": "cl",
    "Ecuador": "ec",
    "Ukraine": "ua",
    "Russia": "ru",
    "Hungary": "hu",
    "Czech Republic": "cz",
    "Slovakia": "sk",
    "Slovenia": "si",
    "Greece": "gr",
    "Republic of Ireland": "ie",
    "Ireland": "ie",
    "Northern Ireland": "gb-nir",
    "Bosnia and Herzegovina": "ba",
    "Albania": "al",
    "Mali": "ml",
    "Tunisia": "tn",
    "Georgia": "ge",
    "Finland": "fi",
    "Romania": "ro",
}


@register.simple_tag
def club_url(team):
    return build_club_page_url(team)


@register.inclusion_tag("mgl/includes/team_logo.html")
def team_logo(team, size="md"):
    has_upload = bool(team and getattr(team, "logo", None))
    return {
        "team": team,
        "size": size or "md",
        "badge_static": "" if has_upload else (static_badge_path(team) if team else ""),
    }


@register.inclusion_tag("mgl/includes/team_logo.html")
def club_badge(team, size="md"):
    has_upload = bool(team and getattr(team, "logo", None))
    return {
        "team": team,
        "size": size or "md",
        "badge_static": "" if has_upload else (static_badge_path(team) if team else ""),
    }


OUTFIELD_CARD_STATS = (
    ("PAC", "pace"),
    ("SHO", "shooting"),
    ("PAS", "passing"),
    ("DRI", "dribbling"),
    ("DEF", "defending"),
    ("PHY", "physical"),
)
GK_CARD_STATS = (
    ("DIV", "fc_gk_diving"),
    ("HAN", "fc_gk_handling"),
    ("KIC", "fc_gk_kicking"),
    ("REF", "fc_gk_reflexes"),
    ("SPE", "fc_gk_speed"),
    ("POS", "fc_gk_positioning"),
)


def card_stat_rows(player):
    pairs = GK_CARD_STATS if (getattr(player, "position", "") or "").upper() == "GK" else OUTFIELD_CARD_STATS
    rows = []
    for label, field in pairs:
        value = getattr(player, field, None)
        rows.append({"label": label, "value": "—" if value is None else value})
    return rows


@register.simple_tag
def player_face_url(player, size="small"):
    return card_face_src(player, size) or ""


@register.inclusion_tag("mgl/includes/player_card.html")
def player_card(player, size="standard", linked=True):
    size = size or "standard"
    return {
        "player": player,
        "size": size,
        "linked": linked,
        "face_url": card_face_src(player, size),
        "card_stats": card_stat_rows(player),
    }


@register.inclusion_tag("mgl/includes/player_attribute_group.html")
def player_attribute_group(title, items):
    visible = []
    for row in items or []:
        value = row.get("value")
        if value is None or value == "":
            display = "—"
        else:
            display = value
        visible.append({"label": row.get("label"), "value": display})
    return {"title": title, "items": visible}


@register.inclusion_tag("mgl/includes/player_stats_panel.html")
def player_stats_panel(player):
    goals = getattr(player, "goals", 0) or 0
    assists = getattr(player, "assists", 0) or 0
    appearances = getattr(player, "appearances", 0) or 0
    has_data = bool(goals or assists or appearances)
    return {
        "player": player,
        "has_data": has_data,
        "goals": goals,
        "assists": assists,
        "appearances": appearances,
        "average_rating": getattr(player, "average_rating", None),
    }


@register.filter
def player_tier(player):
    overall = getattr(player, "overall", 0) or 0
    if overall >= 75:
        return "GOLD"
    if overall >= 65:
        return "SILVER"
    return "BRONZE"


@register.filter
def market_status_label(player):
    from mgl.player_state import market_status_label as label

    return label(player)


@register.filter
def market_status_slug(player):
    from mgl.player_state import market_status

    return market_status(player).lower().replace(" ", "-")


@register.filter
def card_name(player):
    """Uppercase the stored FC26 recognised name. Do not take only the last token."""
    name = getattr(player, "name", "") or str(player)
    latin = []
    for char in name:
        if ord(char) > 900 and not char.isspace() and char not in "-'.":
            break
        latin.append(char)
    cleaned = "".join(latin).strip(" -") or name
    return " ".join(cleaned.split()).upper()


@register.filter
def time_left(ends_at):
    from django.utils import timezone

    if not ends_at:
        return "—"
    remaining = ends_at - timezone.now()
    total = int(remaining.total_seconds())
    if total <= 0:
        return "Expired"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days:
        return f"{days:02d}d {hours:02d}h {minutes:02d}m"
    return f"{hours:02d}h {minutes:02d}m {seconds:02d}s"


@register.filter
def wait_left(delta):
    if delta is None:
        return "Available"
    total = int(delta.total_seconds())
    if total <= 0:
        return "Available"
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {seconds:02d}s"


@register.filter
def flag_code(nationality):
    if not nationality:
        return ""
    return NATIONALITY_ISO.get(nationality.strip(), "")


@register.filter
def player_age(player):
    from players.display import player_age as resolve_age

    age = resolve_age(player)
    return "" if age is None else age


@register.filter
def star_rating(value):
    from players.display import star_rating as stars

    return stars(value)


@register.filter
def ufl_roster_cap(team):
    from mgl.ufl_settings import effective_roster_limit

    return effective_roster_limit(team)


@register.filter
def pos_line(position):
    pos = (position or "").upper()
    if pos == "GK":
        return "gk"
    if pos in {"CB", "LB", "RB", "LWB", "RWB"}:
        return "def"
    if pos in {"ST", "CF", "LW", "RW"}:
        return "att"
    if pos:
        return "mid"
    return ""


@register.filter
def ovr_band(value):
    try:
        overall = int(value or 0)
    except (TypeError, ValueError):
        overall = 0
    if overall >= 80:
        return "high"
    if overall >= 65:
        return "mid"
    return "low"


@register.filter
def ovr_band_label(value):
    return {"high": "HIGH", "mid": "MID", "low": "LOW"}.get(ovr_band(value), "LOW")


@register.filter
def cup_art(slug):
    files = {
        "champions-league": "core/img/cups/champions-league.jpg",
        "europa-league": "core/img/cups/europa-league.jpg",
        "conference-league": "core/img/cups/conference-league.jpg",
        "phantom-cup": "core/img/cups/phantom-cup.jpg",
    }
    return files.get(slug or "", f"core/img/cups/{slug}.jpg")


@register.inclusion_tag("mgl/includes/ufl_coin.html")
def ufl_coin(amount, size="sm"):
    return {"amount": amount, "size": size or "sm"}


@register.inclusion_tag("mgl/includes/ufl_rating.html")
def ufl_rating(player_or_value):
    if hasattr(player_or_value, "overall"):
        overall = getattr(player_or_value, "overall", 0) or 0
    else:
        overall = player_or_value or 0
    try:
        overall = int(overall)
    except (TypeError, ValueError):
        overall = 0
    band = "high" if overall >= 80 else "mid" if overall >= 65 else "low"
    label = {"high": "HIGH", "mid": "MID", "low": "LOW"}[band]
    return {"overall": overall, "band": band, "label": label}
