"""Recruitment Drive: configurable packs, reserved unsigned results, choose one.

Players stay UNSIGNED until a valid choice is committed. Unselected results
remain UNSIGNED. They do not become Free Agents.
"""

from __future__ import annotations

import random
from decimal import Decimal

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from mgl.player_state import is_ufl_free_agent, unassigned_players
from mgl.services import assign_player, debit_manager, manager_for_user
from mgl.tokens import validate_token_amount
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


def reserved_player_ids():
    from mgl.models import RecruitmentOpening, ScoutAssignment

    ids = set()
    for row in RecruitmentOpening.objects.filter(status=RecruitmentOpening.PENDING).values_list(
        "player_ids", flat=True
    ):
        ids.update(int(pk) for pk in (row or []) if str(pk).isdigit() or isinstance(pk, int))
    for row in ScoutAssignment.objects.filter(
        status__in=(ScoutAssignment.PENDING, ScoutAssignment.READY, ScoutAssignment.OPENED)
    ).values_list("player_ids", "player_id"):
        for pk in row[0] or []:
            if str(pk).isdigit() or isinstance(pk, int):
                ids.add(int(pk))
        if row[1]:
            ids.add(int(row[1]))
    return ids


def ensure_default_packs():
    from mgl.models import RecruitmentPack

    if RecruitmentPack.objects.exists():
        return list(RecruitmentPack.objects.order_by("sort_order", "name", "id"))
    created = []
    for index, (code, name, positions) in enumerate(PACKS):
        created.append(
            RecruitmentPack.objects.create(
                code=code,
                name=name,
                pack_type="POSITION",
                active=True,
                token_cost=RECRUITMENT_COST,
                result_count=RECRUITMENT_COUNT,
                select_count=1,
                max_ovr=RECRUITMENT_MAX_OVR,
                positions=list(positions),
                sort_order=index,
            )
        )
    return created


def pack_by_code(pack_code):
    from mgl.models import RecruitmentPack

    ensure_default_packs()
    code = (pack_code or "").strip().upper()
    pack = RecruitmentPack.objects.filter(code__iexact=code).first()
    if pack is None:
        raise ValueError("Choose a valid Recruitment Drive pack.")
    return pack


def pack_choices(manager=None, *, include_inactive=False):
    from mgl.models import RecruitmentOpening

    rows = []
    for pack in ensure_default_packs():
        if not pack.active and not include_inactive:
            continue
        used = 0
        remaining_opens = None
        if manager is not None:
            used = RecruitmentOpening.objects.filter(
                manager=manager,
                pack=pack,
                status__in=(RecruitmentOpening.PENDING, RecruitmentOpening.COMPLETED),
            ).count()
            if pack.opening_limit is not None:
                remaining_opens = max(0, pack.opening_limit - used)
        result_count = int(pack.result_count or RECRUITMENT_COUNT)
        remaining = eligible_pool(pack).count()
        can_open = pack.active and remaining >= result_count
        if remaining_opens is not None and remaining_opens <= 0:
            can_open = False
        rows.append(
            {
                "id": pack.id,
                "code": pack.code,
                "label": pack.name,
                "positions": pack.positions or [],
                "rating_min": pack.min_ovr,
                "rating_max": pack.max_ovr if pack.max_ovr is not None else RECRUITMENT_MAX_OVR,
                "remaining": remaining,
                "cost": pack.token_cost,
                "result_count": result_count,
                "select_count": pack.select_count,
                "opening_limit": pack.opening_limit,
                "openings_used": used,
                "openings_left": remaining_opens,
                "active": pack.active,
                "can_open": can_open,
                "pack": pack,
            }
        )
    return rows


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


def _pack_positions(pack):
    positions = list(pack.positions or [])
    return positions


def eligible_pool(pack, exclude_ids=None):
    exclude_ids = set(exclude_ids or ()) | reserved_player_ids()
    qs = unassigned_players().exclude(id__in=exclude_ids)
    positions = _pack_positions(pack)
    if positions:
        qs = qs.filter(position__in=positions)
    if pack.min_ovr is not None:
        qs = qs.filter(overall__gte=pack.min_ovr)
    if pack.max_ovr is not None:
        qs = qs.filter(overall__lte=pack.max_ovr)
    return qs.order_by("id")


def _pick_players(pack, rng, count):
    exclude = set()
    for _attempt in range(8):
        pool = list(eligible_pool(pack, exclude_ids=exclude).values_list("id", flat=True))
        if len(pool) < count:
            raise ValueError("Not enough unsigned players match this recruitment pack.")
        picked = rng.sample(pool, count)
        claimed = []
        conflict = False
        reserved = reserved_player_ids()
        for player_id in sorted(picked):
            player = Player.objects.select_for_update().get(pk=player_id)
            if (
                player.mgl_team_id
                or is_ufl_free_agent(player)
                or player.id in reserved
            ):
                exclude.add(player.id)
                conflict = True
                break
            claimed.append(player.id)
        if not conflict and len(claimed) == count:
            return claimed
        exclude.update(picked)
    raise ValueError("Not enough unsigned players match this recruitment pack.")


def openings_used(manager, pack):
    from mgl.models import RecruitmentOpening

    return RecruitmentOpening.objects.filter(
        manager=manager,
        pack=pack,
        status__in=(RecruitmentOpening.PENDING, RecruitmentOpening.COMPLETED),
    ).count()


@transaction.atomic
def open_recruitment_pack(user, pack_code, *, rng=None):
    from mgl.market import club_for_user
    from mgl.models import RecruitmentOpening
    from mgl.notifications import notify_user
    from mgl.player_state import roster_occupancy
    from managers.models import ManagerApplication

    pack = pack_by_code(pack_code)
    if not pack.active:
        raise ValueError("That recruitment pack is not available.")
    cost = validate_token_amount(pack.token_cost)
    result_count = int(pack.result_count or RECRUITMENT_COUNT)

    manager = manager_for_user(user)
    if manager is None or manager.status != manager.APPROVED:
        raise ValueError("You must be an approved manager to open a recruitment pack.")
    manager = ManagerApplication.objects.select_for_update().get(pk=manager.pk)
    team = club_for_user(user)
    if team is None:
        raise ValueError("You need a club before you can recruit.")

    team = Team.objects.select_for_update().get(pk=team.pk)
    pending = pending_opening_for(manager)
    if pending:
        raise ValueError("Choose a player from your open pack before buying another.")
    if pack.opening_limit is not None and openings_used(manager, pack) >= pack.opening_limit:
        raise ValueError("You have reached the opening limit for this pack.")
    if manager.tokens < cost:
        raise ValueError("Manager does not have enough tokens.")

    limit = effective_roster_limit(team)
    if roster_occupancy(team) >= limit:
        raise ValueError(f"{team.name} is at the {limit}-player squad limit.")

    rng = rng or random.SystemRandom()
    player_ids = _pick_players(pack, rng, result_count)

    opening = RecruitmentOpening.objects.create(
        manager=manager,
        team=team,
        pack=pack,
        pack_code=pack.code,
        player_ids=player_ids,
        status=RecruitmentOpening.PENDING,
    )
    debit_manager(
        manager,
        cost,
        f"Recruitment Drive {pack.name}",
        category=PACK_COST_CATEGORY,
        reference=f"recruitment:open:{opening.pk}",
    )
    notify_user(
        user,
        source_key=f"recruitment:{opening.pk}",
        notification_type="RECRUITMENT",
        title="Your recruitment pack is ready.",
        message=f"Choose one player from the {pack.name}.",
        action_url=reverse("recruitment_drive"),
        action_label="CHOOSE",
        team=team,
        is_action=True,
    )
    from mgl.services import create_news

    create_news(
        category="SIGNING",
        title=f"{team.name} opened a recruitment pack",
        body=f"{team.name} opened {pack.name} for {cost} TKN.",
        publish=True,
        team=team,
        discord_idempotency_key=f"recruit.open:{opening.pk}",
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
        .select_related("team", "manager", "pack")
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
        raise ValueError("Choose one of the generated players.") from exc
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
    if player.mgl_team_id or is_ufl_free_agent(player):
        raise ValueError("That player is no longer unsigned.")

    assign_player(player, team, source="RECRUITMENT", reference=str(opening.pk))
    opening.chosen_player = player
    opening.status = RecruitmentOpening.COMPLETED
    opening.resolved_at = timezone.now()
    opening.save(update_fields=["chosen_player", "status", "resolved_at"])

    pack_label = opening.pack.name if opening.pack_id else PACK_MAP.get(opening.pack_code, {}).get("label", "Recruitment Drive pack")
    create_news(
        category="SIGNING",
        title=f"{player.name} joins {team.name}",
        body=(
            f"{player.name} was signed from the unsigned pool through a "
            f"{pack_label}."
        ),
        publish=True,
        team=team,
        discord_idempotency_key=f"recruit.result:{opening.pk}",
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


def save_recruitment_pack(*, actor, pack=None, **fields):
    from mgl.models import RecruitmentPack
    from mgl.permissions import is_owner_or_admin

    if not is_owner_or_admin(actor):
        raise ValueError("Only the Owner or Admin can configure recruitment packs.")
    cost = validate_token_amount(fields.get("token_cost", RECRUITMENT_COST))
    result_count = int(fields.get("result_count") or RECRUITMENT_COUNT)
    select_count = int(fields.get("select_count") or 1)
    if result_count < 1:
        raise ValueError("A pack must return at least one player.")
    if select_count < 1 or select_count > result_count:
        raise ValueError("The manager must select at least one player from the results.")
    code = (fields.get("code") or "").strip().upper()
    name = (fields.get("name") or "").strip()
    if not code or not name:
        raise ValueError("Pack code and name are required.")
    positions = fields.get("positions") or []
    if isinstance(positions, str):
        positions = [part.strip().upper() for part in positions.replace(",", " ").split() if part.strip()]
    opening_limit = fields.get("opening_limit")
    if opening_limit in ("", None):
        opening_limit = None
    else:
        opening_limit = int(opening_limit)
        if opening_limit < 1:
            raise ValueError("Opening limit must be at least 1, or blank for unlimited.")
    payload = {
        "code": code,
        "name": name,
        "pack_type": (fields.get("pack_type") or "POSITION").strip() or "POSITION",
        "active": bool(fields.get("active", True)),
        "token_cost": cost,
        "result_count": result_count,
        "select_count": select_count,
        "min_ovr": int(fields["min_ovr"]) if fields.get("min_ovr") not in (None, "") else None,
        "max_ovr": int(fields["max_ovr"]) if fields.get("max_ovr") not in (None, "") else None,
        "positions": positions,
        "opening_limit": opening_limit,
        "sort_order": int(fields.get("sort_order") or 0),
    }
    if pack is None:
        if RecruitmentPack.objects.filter(code__iexact=code).exists():
            raise ValueError("A pack with that code already exists.")
        return RecruitmentPack.objects.create(**payload)
    for key, value in payload.items():
        setattr(pack, key, value)
    pack.save()
    return pack
