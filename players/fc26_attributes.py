"""FC26 individual attribute mapping.

Card ratings (pace, shooting, passing, dribbling, defending, physical, overall)
stay on ``Player`` as they already are. These helpers map the FC26 CSV's
detailed skill columns onto nullable ``fc_*`` fields and build the profile
attribute groups from stored values. Missing source values stay ``None``
and render as "—"; nothing is invented.
"""

from __future__ import annotations


# (Player field, CSV column)
ATTR_COLUMNS = (
    ("fc_sprint_speed", "movement_sprint_speed"),
    ("fc_acceleration", "movement_acceleration"),
    ("fc_positioning", "mentality_positioning"),
    ("fc_finishing", "attacking_finishing"),
    ("fc_shot_power", "power_shot_power"),
    ("fc_long_shots", "power_long_shots"),
    ("fc_volleys", "attacking_volleys"),
    ("fc_penalties", "mentality_penalties"),
    ("fc_vision", "mentality_vision"),
    ("fc_crossing", "attacking_crossing"),
    ("fc_fk_accuracy", "skill_fk_accuracy"),
    ("fc_short_passing", "attacking_short_passing"),
    ("fc_long_passing", "skill_long_passing"),
    ("fc_curve", "skill_curve"),
    ("fc_dribbling", "skill_dribbling"),
    ("fc_agility", "movement_agility"),
    ("fc_balance", "movement_balance"),
    ("fc_reactions", "movement_reactions"),
    ("fc_ball_control", "skill_ball_control"),
    ("fc_composure", "mentality_composure"),
    ("fc_interceptions", "mentality_interceptions"),
    ("fc_heading", "attacking_heading_accuracy"),
    ("fc_marking", "defending_marking_awareness"),
    ("fc_standing_tackle", "defending_standing_tackle"),
    ("fc_sliding_tackle", "defending_sliding_tackle"),
    ("fc_jumping", "power_jumping"),
    ("fc_stamina", "power_stamina"),
    ("fc_strength", "power_strength"),
    ("fc_aggression", "mentality_aggression"),
    ("fc_gk_diving", "goalkeeping_diving"),
    ("fc_gk_handling", "goalkeeping_handling"),
    ("fc_gk_kicking", "goalkeeping_kicking"),
    ("fc_gk_positioning", "goalkeeping_positioning"),
    ("fc_gk_reflexes", "goalkeeping_reflexes"),
    ("fc_gk_speed", "goalkeeping_speed"),
)

ATTR_FIELD_NAMES = [field for field, _csv in ATTR_COLUMNS]
CSV_ATTR_NAMES = [csv_name for _field, csv_name in ATTR_COLUMNS]
ATTR_CSV_TO_FIELD = {csv_name: field for field, csv_name in ATTR_COLUMNS}

# Present for every outfield player and every GK in FC26. ``fc_gk_speed`` is
# only populated for goalkeepers.
CORE_ATTR_FIELDS = [field for field, _csv in ATTR_COLUMNS if field != "fc_gk_speed"]
GK_ONLY_FIELDS = ["fc_gk_speed"]

ATTRIBUTE_GROUPS = (
    (
        "PACE",
        (
            ("Sprint Speed", "fc_sprint_speed"),
            ("Acceleration", "fc_acceleration"),
        ),
    ),
    (
        "SHOOTING",
        (
            ("Positioning", "fc_positioning"),
            ("Finishing", "fc_finishing"),
            ("Shot Power", "fc_shot_power"),
            ("Long Shots", "fc_long_shots"),
            ("Volleys", "fc_volleys"),
            ("Penalties", "fc_penalties"),
        ),
    ),
    (
        "PASSING",
        (
            ("Vision", "fc_vision"),
            ("Crossing", "fc_crossing"),
            ("Free Kick Accuracy", "fc_fk_accuracy"),
            ("Short Passing", "fc_short_passing"),
            ("Long Passing", "fc_long_passing"),
            ("Curve", "fc_curve"),
        ),
    ),
    (
        "DRIBBLING",
        (
            ("Dribbling", "fc_dribbling"),
            ("Agility", "fc_agility"),
            ("Balance", "fc_balance"),
            ("Reactions", "fc_reactions"),
            ("Ball Control", "fc_ball_control"),
            ("Composure", "fc_composure"),
        ),
    ),
    (
        "DEFENDING",
        (
            ("Interceptions", "fc_interceptions"),
            ("Heading Accuracy", "fc_heading"),
            ("Defensive Awareness", "fc_marking"),
            ("Standing Tackle", "fc_standing_tackle"),
            ("Sliding Tackle", "fc_sliding_tackle"),
        ),
    ),
    (
        "PHYSICAL",
        (
            ("Jumping", "fc_jumping"),
            ("Stamina", "fc_stamina"),
            ("Strength", "fc_strength"),
            ("Aggression", "fc_aggression"),
        ),
    ),
)

GOALKEEPING_GROUP = (
    "GOALKEEPING",
    (
        ("Diving", "fc_gk_diving"),
        ("Handling", "fc_gk_handling"),
        ("Kicking", "fc_gk_kicking"),
        ("Positioning", "fc_gk_positioning"),
        ("Reflexes", "fc_gk_reflexes"),
        ("Speed", "fc_gk_speed"),
    ),
)


def parse_attr_value(value):
    """Return an int or None. Empty CSV cells stay None; never invent a number."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def apply_fc26_attributes(player, row) -> list[str]:
    """Copy FC26 detail attributes onto an existing player. Does not create rows."""
    changed = []
    for field, csv_name in ATTR_COLUMNS:
        parsed = parse_attr_value(row.get(csv_name))
        if getattr(player, field) != parsed:
            setattr(player, field, parsed)
            changed.append(field)
    work_rate = (row.get("work_rate") or "").strip()
    if getattr(player, "fc_work_rate", "") != work_rate:
        player.fc_work_rate = work_rate
        changed.append("fc_work_rate")
    return changed


def attribute_items(player, rows):
    return [
        {"label": label, "value": getattr(player, field, None)}
        for label, field in rows
    ]


def show_goalkeeping(player) -> bool:
    if (player.position or "").upper() == "GK":
        return True
    return getattr(player, "fc_gk_speed", None) is not None


def attribute_groups_for_player(player) -> list[dict]:
    groups = [
        {"title": title, "items": attribute_items(player, rows)}
        for title, rows in ATTRIBUTE_GROUPS
    ]
    if show_goalkeeping(player):
        title, rows = GOALKEEPING_GROUP
        groups.append({"title": title, "items": attribute_items(player, rows)})
    return groups


def attribute_completeness(player) -> str:
    """Return 'complete', 'partial', or 'empty' for reporting."""
    core_values = [getattr(player, field, None) for field in CORE_ATTR_FIELDS]
    filled = sum(value is not None for value in core_values)
    if (player.position or "").upper() == "GK":
        gk_speed = getattr(player, "fc_gk_speed", None)
        if filled == len(CORE_ATTR_FIELDS) and gk_speed is not None:
            return "complete"
        if filled or gk_speed is not None:
            return "partial"
        return "empty"
    if filled == len(CORE_ATTR_FIELDS):
        return "complete"
    if filled:
        return "partial"
    return "empty"
