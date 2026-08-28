from django import template

from players.fc26_faces import card_face_src
from teams.badges import static_badge_path


register = template.Library()


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


@register.inclusion_tag("mgl/includes/team_logo.html")
def team_logo(team, size="md"):
    return {
        "team": team,
        "size": size or "md",
        "badge_static": static_badge_path(team) if team else "",
    }


@register.inclusion_tag("mgl/includes/team_logo.html")
def club_badge(team, size="md"):
    return {
        "team": team,
        "size": size or "md",
        "badge_static": static_badge_path(team) if team else "",
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
