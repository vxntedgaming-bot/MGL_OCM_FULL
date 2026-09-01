"""Recruitment Drive: 1 token opens a 3-player UNSIGNED pack. Manager picks one.

Server-side only. Players stay in the unsigned pool until a valid choice is
committed. Crafted player IDs that were not generated for this opening fail.
"""

from __future__ import annotations

import random
from decimal import Decimal

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from mgl.player_state import unassigned_players
from mgl.services import assign_player, debit_manager, manager_for_user
from mgl.ufl_settings import effective_roster_limit
from players.models import Player
from teams.models import Team

RECRUITMENT_COST = Decimal("1")
RECRUITMENT_COUNT = 3
RECRUITMENT_MAX_OVR = 74
PACK_COST_CATEGORY = "RECRUITMENT"

PACKS = (
    ("GK", "3x GK PACK", ("GK",)),
    ("CB", "3x CB PACK", ("CB",)),
    ("FB", "3x RB/LB PACK", ("RB", "LB")),
    ("DM", "3x CDM/CM PACK", ("CDM", "CM")),
    ("WM", "3x RM/LM PACK", ("RM", "LM")),
    ("CAM", "3x CAM PACK", ("CAM",)),
    ("WING", "3x LW/RW PACK", ("LW", "RW")),
    ("ST", "3x ST PACK", ("ST", "CF")),
)

PACK_MAP = {code: {"label": label, "positions": positions} for code, label, positions in PACKS}


def pack_choices():
    return [{"code": code, "label": label, "positions": positions} for code, label, positions in PACKS]


def pending_opening_for(manager):
    from mgl.models import RecruitmentOpening

    if manager is None:
        return None
    return (
        RecruitmentOpening.objects.filter(
            manager=manager,
            status=RecruitmentOpening.PENDING,
        )
        .order_by("-created_at", "-id")
        .first()
    )


def eligible_pool(positions, exclude_ids=None):
    exclude_ids = set(exclude_ids or ())
    return (
        unassigned_players()
        .filter(position__in=positions, overall__lte=RECRUITMENT_MAX_OVR)
        .exclude(id__in=exclude_ids)
        .order_by("id")
    )


def _pick_three(positions, rng):
    pool = list(eligible_pool(positions).values_list("id", flat=True))
    if len(pool) < RECRUITMENT_COUNT:
        raise ValueError(
            "Not enough unsigned players in this position group (OVR 74 or below)."
        )
    return rng.sample(pool, RECRUITMENT_COUNT)


@transaction.atomic
def open_recruitment_pack(user, pack_code, *, rng=None):
    from mgl.market import club_for_user
    from mgl.models import RecruitmentOpening
    from mgl.notifications import notify_user
    from mgl.player_state import roster_occupancy

    pack = PACK_MAP.get((pack_code or "").strip().upper())
    if not pack:
        raise ValueError("Choose a valid Recruitment Drive pack.")

    manager = manager_for_user(user)
    if manager is None or manager.status != manager.APPROVED:
        raise ValueError("You must be an approved manager to open a recruitment pack.")
    team = club_for_user(user)
    if team is None:
        raise ValueError("You need a club before you can recruit.")

    team = Team.objects.select_for_update().get(pk=team.pk)
    pending = pending_opening_for(manager)
    if pending:
        raise ValueError("Choose a player from your open pack before buying another.")

    limit = effective_roster_limit(team)
    if roster_occupancy(team) >= limit:
        raise ValueError(f"{team.name} is at the {limit}-player squad limit.")

    rng = rng or random.SystemRandom()
    player_ids = _pick_three(pack["positions"], rng)

    opening = RecruitmentOpening.objects.create(
        manager=manager,
        team=team,
        pack_code=pack_code.upper(),
        player_ids=player_ids,
        status=RecruitmentOpening.PENDING,
    )
    debit_manager(
        manager,
        RECRUITMENT_COST,
        f"Recruitment Drive {pack['label']}",
        category=PACK_COST_CATEGORY,
        reference=f"recruitment:open:{opening.pk}",
    )
    notify_user(
        user,
        source_key=f"recruitment:{opening.pk}",
        notification_type="RECRUITMENT",
        title="Your recruitment pack is ready.",
        message=f"Choose one player from the {pack['label']}.",
        action_url=reverse("recruitment_drive"),
        action_label="CHOOSE",
        team=team,
        is_action=True,
    )
    return opening


@transaction.atomic
def choose_recruitment_player(user, opening_id, player_id):
    from mgl.market import club_for_user
    from mgl.models import RecruitmentOpening
    from mgl.player_state import roster_occupancy
    from mgl.services import create_news

    manager = manager_for_user(user)
    if manager is None:
        raise ValueError("You must be an approved manager to recruit.")
    opening = (
        RecruitmentOpening.objects.select_for_update()
        .select_related("team", "manager")
        .filter(pk=opening_id, manager=manager)
        .first()
    )
    if opening is None:
        raise ValueError("That recruitment pack does not belong to you.")
    if opening.status != RecruitmentOpening.PENDING:
        raise ValueError("This pack has already been resolved.")

    try:
        player_id = int(player_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose one of the three generated players.") from exc
    if player_id not in [int(pk) for pk in opening.player_ids]:
        raise ValueError("That player was not in this recruitment pack.")

    team = club_for_user(user)
    if team is None or team.id != opening.team_id:
        raise ValueError("You can only recruit into your current club.")

    team = Team.objects.select_for_update().get(pk=team.pk)
    limit = effective_roster_limit(team)
    if roster_occupancy(team) >= limit:
        raise ValueError(f"{team.name} is at the {limit}-player squad limit.")

    player = Player.objects.select_for_update().filter(pk=player_id).first()
    if player is None:
        raise ValueError("That player is no longer available.")
    if player.mgl_team_id or player.is_free_agent:
        raise ValueError("That player is no longer unsigned.")

    assign_player(player, team, source="RECRUITMENT", reference=str(opening.pk))
    opening.chosen_player = player
    opening.status = RecruitmentOpening.COMPLETED
    opening.resolved_at = timezone.now()
    opening.save(update_fields=["chosen_player", "status", "resolved_at"])

    pack = PACK_MAP.get(opening.pack_code, {})
    create_news(
        category="SIGNING",
        title=f"{player.name} joins {team.name}",
        body=(
            f"{player.name} was signed from the unsigned pool through a "
            f"{pack.get('label', 'Recruitment Drive pack')}."
        ),
        publish=True,
        team=team,
    )
    return opening


def players_for_opening(opening):
    if opening is None:
        return []
    ids = [int(pk) for pk in opening.player_ids]
    found = {
        player.id: player
        for player in Player.objects.filter(pk__in=ids).select_related("mgl_team")
    }
    return [found[pk] for pk in ids if pk in found]
