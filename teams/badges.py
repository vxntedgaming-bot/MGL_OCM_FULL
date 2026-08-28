"""Static club-badge lookup for official Super League 1 short names.

Uploaded Team.logo always wins. These files are fallbacks when the
ImageField is empty so the 14 official clubs still show a crest.
"""

from pathlib import Path

from django.conf import settings


OFFICIAL_BADGE_STATIC = {
    "RMA": "core/img/clubs/RMA.svg",
    "BAR": "core/img/clubs/BAR.svg",
    "ATM": "core/img/clubs/ATM.svg",
    "MUN": "core/img/clubs/MUN.svg",
    "CHE": "core/img/clubs/CHE.svg",
    "MCI": "core/img/clubs/MCI.svg",
    "ARS": "core/img/clubs/ARS.svg",
    "LIV": "core/img/clubs/LIV.svg",
    "TOT": "core/img/clubs/TOT.svg",
    "PSG": "core/img/clubs/PSG.svg",
    "OL": "core/img/clubs/OL.svg",
    "OM": "core/img/clubs/OM.svg",
    "B04": "core/img/clubs/B04.svg",
    "FCB": "core/img/clubs/FCB.svg",
}


def static_badge_path(team):
    if team is None:
        return ""
    short = (getattr(team, "short_name", "") or "").upper()
    rel = OFFICIAL_BADGE_STATIC.get(short, "")
    if not rel:
        return ""
    # Prefer the file only if it actually exists in this checkout.
    candidate = Path(settings.BASE_DIR) / "core" / "static" / rel
    if candidate.exists():
        return rel
    collected = Path(settings.STATIC_ROOT) / rel
    if collected.exists():
        return rel
    return ""
