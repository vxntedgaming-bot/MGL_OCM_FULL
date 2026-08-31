"""Shared player display helpers. Never invent ratings, ages, or playstyles."""

from __future__ import annotations

from datetime import date, datetime


def parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def player_age(player, today=None):
    """One age for every MGL surface.

    Prefer a stored date of birth (current age). Otherwise use the stored
    FC26 age integer. Return None when neither exists.
    """
    dob = getattr(player, "date_of_birth", None)
    if dob:
        today = today or date.today()
        years = today.year - dob.year
        if (today.month, today.day) < (dob.month, dob.day):
            years -= 1
        if years >= 0:
            return years
    age = getattr(player, "age", None)
    if age in (None, ""):
        return None
    try:
        return int(age)
    except (TypeError, ValueError):
        return None


def star_rating(value, maximum=5):
    if value in (None, ""):
        return ""
    try:
        filled = int(value)
    except (TypeError, ValueError):
        return ""
    filled = max(0, min(int(maximum), filled))
    return ("★" * filled) + ("☆" * (int(maximum) - filled))


def parse_playstyles(raw):
    if not raw:
        return [], []
    if isinstance(raw, (list, tuple)):
        parts = [str(item).strip() for item in raw]
    else:
        parts = [part.strip() for part in str(raw).replace(";", ",").split(",")]
    styles = []
    plus = []
    seen_styles = set()
    seen_plus = set()
    for item in parts:
        if not item:
            continue
        if item.endswith("+"):
            if item not in seen_plus:
                plus.append(item)
                seen_plus.add(item)
            continue
        if item not in seen_styles:
            styles.append(item)
            seen_styles.add(item)
    return styles, plus


def _split_names(raw):
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return [part.strip() for part in str(raw).replace(";", ",").split(",") if part.strip()]


def playstyles_for_player(player):
    styles, plus_from_styles = parse_playstyles(getattr(player, "fc_playstyles", "") or "")
    plus = []
    seen = set()
    for item in _split_names(getattr(player, "fc_playstyle_plus", "") or "") + plus_from_styles:
        if item not in seen:
            plus.append(item)
            seen.add(item)
    return styles, plus


def apply_fc26_identity(player, row) -> list[str]:
    """Fill DOB, age (if empty), and playstyles from an FC26 CSV row."""
    changed = []
    dob = parse_date(row.get("dob"))
    if dob and getattr(player, "date_of_birth", None) != dob:
        if getattr(player, "date_of_birth", None) is None:
            player.date_of_birth = dob
            changed.append("date_of_birth")
    if getattr(player, "age", None) in (None, ""):
        csv_age = row.get("age")
        parsed_age = None
        if csv_age not in (None, ""):
            try:
                parsed_age = int(float(csv_age))
            except (TypeError, ValueError):
                parsed_age = None
        if parsed_age is None and dob:
            parsed_age = player_age(type("P", (), {"date_of_birth": dob, "age": None})())
        if parsed_age is not None:
            player.age = parsed_age
            changed.append("age")
    raw_traits = (row.get("player_traits") or "").strip()
    styles, plus = parse_playstyles(raw_traits)
    styles_text = ", ".join(styles)
    plus_text = ", ".join(plus)
    if styles_text and not (getattr(player, "fc_playstyles", "") or "").strip():
        player.fc_playstyles = styles_text
        changed.append("fc_playstyles")
    if plus_text and not (getattr(player, "fc_playstyle_plus", "") or "").strip():
        player.fc_playstyle_plus = plus_text
        changed.append("fc_playstyle_plus")
    return changed
