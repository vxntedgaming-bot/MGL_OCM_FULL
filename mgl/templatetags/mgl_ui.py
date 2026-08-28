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


@register.inclusion_tag("mgl/includes/player_card.html")
def player_card(player, size="standard", linked=True):
    size = size or "standard"
    return {
        "player": player,
        "size": size,
        "linked": linked,
        "face_url": card_face_src(player, size),
    }


@register.inclusion_tag("mgl/includes/player_attribute_group.html")
def player_attribute_group(title, items):
    visible = [row for row in (items or []) if row.get("value") not in (None, "", 0, "0")]
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
def card_name(player):
    name = getattr(player, "name", "") or str(player)
    latin = []
    for char in name:
        if ord(char) > 900 and not char.isspace() and char not in "-'.":
            break
        latin.append(char)
    cleaned = "".join(latin).strip(" -") or name
    parts = [part for part in cleaned.replace(".", " ").split() if part]
    if len(parts) <= 2:
        return " ".join(parts).upper()
    return parts[-1].upper()


@register.filter
def flag_code(nationality):
    if not nationality:
        return ""
    return NATIONALITY_ISO.get(nationality.strip(), "")
