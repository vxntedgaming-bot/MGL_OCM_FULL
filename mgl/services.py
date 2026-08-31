from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from auctions.models import PlayerAuction
from managers.models import ManagerApplication
from players.models import Player
from teams.models import Team

from .models import (
    ApprovalStatus,
    ManagerCareerStat,
    NewsPost,
    PlayerListing,
    PlayerOwnershipHistory,
    RewardTransaction,
)


def player_tier(overall):
    if hasattr(overall, "overall"):
        overall = getattr(overall, "overall", 0)
    overall = overall or 0
    if overall >= 75:
        return "GOLD"
    if overall >= 65:
        return "SILVER"
    return "BRONZE"


def manager_for_user(user):
    if not user or not user.is_authenticated:
        return None

    try:
        return ManagerApplication.objects.get(user=user)
    except ManagerApplication.DoesNotExist:
        return None


def _open_reward(manager, category, reference):
    if not reference:
        return None
    return RewardTransaction.objects.filter(
        manager=manager,
        category=category,
        reference=reference,
        reversed_at__isnull=True,
    ).first()


@transaction.atomic
def credit_manager(
    manager,
    amount,
    reason,
    category="OTHER",
    fixture=None,
    reference="",
    created_by=None,
    reverses=None,
):
    """
    Add tokens to a manager and permanently record the reward.
    If reference is set, the same open manager/category/reference pays only once.
    """

    amount = Decimal(str(amount))
    reference = (reference or "").strip()

    manager = (
        ManagerApplication.objects
        .select_for_update()
        .get(pk=manager.pk)
    )

    existing = _open_reward(manager, category, reference)
    if existing:
        return existing

    before = Decimal(manager.tokens)
    manager.tokens = before + amount
    manager.save(update_fields=["tokens"])

    return RewardTransaction.objects.create(
        manager=manager,
        amount=amount,
        reason=reason,
        category=category,
        fixture=fixture,
        reference=reference,
        balance_before=before,
        balance_after=manager.tokens,
        created_by=created_by if getattr(created_by, "is_authenticated", False) else None,
        reverses=reverses,
    )


@transaction.atomic
def debit_manager(
    manager,
    amount,
    reason,
    category="OTHER",
    fixture=None,
    reference="",
    created_by=None,
    reverses=None,
    allow_negative=False,
):
    """
    Remove tokens safely and permanently record the transaction.
    If reference is set, the same open manager/category/reference debits only once.
    """

    amount = Decimal(str(amount))
    reference = (reference or "").strip()

    manager = (
        ManagerApplication.objects
        .select_for_update()
        .get(pk=manager.pk)
    )

    existing = _open_reward(manager, category, reference)
    if existing:
        return existing

    if not allow_negative and manager.tokens < amount:
        raise ValueError("Manager does not have enough tokens.")

    before = Decimal(manager.tokens)
    manager.tokens = before - amount
    manager.save(update_fields=["tokens"])

    return RewardTransaction.objects.create(
        manager=manager,
        amount=-amount,
        reason=reason,
        category=category,
        fixture=fixture,
        reference=reference,
        balance_before=before,
        balance_after=manager.tokens,
        created_by=created_by if getattr(created_by, "is_authenticated", False) else None,
        reverses=reverses,
    )


def get_or_create_career(manager):
    career, _ = ManagerCareerStat.objects.get_or_create(
        manager=manager
    )
    return career


def normalise_totw_position(position):
    """
    MGL 4-2-3-1 position groups.

    LW/LM -> LM
    RW/RM -> RM
    CM/CDM -> CM
    """

    position = (position or "").upper().strip()

    mapping = {
        "GK": "GK",

        "LB": "LB",
        "LWB": "LB",

        "CB": "CB",

        "RB": "RB",
        "RWB": "RB",

        "CDM": "CM",
        "CM": "CM",

        "CAM": "CAM",

        "LM": "LM",
        "LW": "LM",

        "RM": "RM",
        "RW": "RM",

        "CF": "ST",
        "ST": "ST",
    }

    return mapping.get(position, position)


def create_news(category, title, body, publish=True, team=None, secondary_team=None, details=None):
    """
    Creates a news event for the website and Discord bot queue.

    Pass the actual Team objects involved so Live Activity can render
    club badges from club data rather than guessing names in the copy.
    Optional details stores a snapshot (for example a completed deal)
    so later squad moves do not rewrite history.
    """

    post = NewsPost.objects.create(
        category=category,
        title=title,
        body=body,
        published=publish,
        discord_sent=False,
        primary_team=team,
        secondary_team=secondary_team,
        details=details or {},
    )
    try:
        from mgl.discord_queue import queue_from_news

        queue_from_news(post)
    except Exception:
        pass
    return post


@transaction.atomic
def request_player_release(player, team, manager, reason=""):
    """Manager asks to release a player. Ownership does not change until approved."""
    from mgl.models import ApprovalRequest, ApprovalStatus, PlayerReleaseRequest

    player = Player.objects.select_for_update().get(pk=player.pk)
    if player.mgl_team_id != team.id:
        raise ValueError("This player does not belong to this team.")
    if PlayerListing.objects.filter(
        player=player,
        status__in=[PlayerListing.PENDING, PlayerListing.LIVE, PlayerListing.OFFER],
    ).exists():
        raise ValueError("This player cannot be released while listed for transfer.")
    if PlayerAuction.objects.filter(
        player=player,
        status__in=[PlayerAuction.PENDING, PlayerAuction.LIVE],
    ).exists():
        raise ValueError("This player cannot be released while in an auction.")
    if PlayerReleaseRequest.objects.filter(
        player=player, status=ApprovalStatus.PENDING
    ).exists():
        raise ValueError("A release request for this player is already pending.")

    request_row = PlayerReleaseRequest.objects.create(
        player=player,
        team=team,
        manager=manager,
        reason=reason or "",
        status=ApprovalStatus.PENDING,
    )
    ApprovalRequest.objects.create(
        kind="PLAYER_RELEASE",
        object_id=request_row.pk,
        submitted_by=getattr(manager, "user", None),
        status=ApprovalStatus.PENDING,
        payload={"player_id": player.pk, "team_id": team.pk},
    )
    from django.urls import reverse

    from accounts.models import User
    from mgl.notifications import notify_user

    for user in User.objects.filter(role__in=[User.OWNER, User.ADMIN], is_active=True):
        notify_user(
            user,
            source_key=f"admin-release-{request_row.pk}",
            notification_type="RELEASE",
            title="PLAYER RELEASE REQUEST",
            message=(
                f"{team.name} requested to release {player.name}. "
                "The player stays in the squad until you approve."
            ),
            actor=manager.display_name,
            action_url=reverse("control_pending"),
            action_label="REVIEW",
            team=team,
            player=player,
            is_action=True,
        )
    return request_row


@transaction.atomic
def approve_player_release(release_request, reviewer):
    from mgl.models import ApprovalStatus, PlayerReleaseRequest

    release_request = PlayerReleaseRequest.objects.select_for_update().get(
        pk=release_request.pk
    )
    if release_request.status != ApprovalStatus.PENDING:
        raise ValueError("That release request is no longer pending.")
    player = release_player(
        release_request.player,
        release_request.team,
        source="MANAGER_RELEASE",
        reviewer=reviewer,
    )
    release_request.status = ApprovalStatus.APPROVED
    release_request.reviewed_at = timezone.now()
    release_request.reviewed_by = reviewer
    release_request.save(update_fields=["status", "reviewed_at", "reviewed_by"])
    from mgl.audit import log_ocm_action

    log_ocm_action(
        reviewer,
        action="player.release.approve",
        object_type="PlayerReleaseRequest",
        object_id=release_request.pk,
        object_label=player.name,
        new_value="FREE_AGENT",
        summary=f"{player.name} release approved.",
    )
    return player


@transaction.atomic
def reject_player_release(release_request, reviewer, reason=""):
    from mgl.models import ApprovalStatus, PlayerReleaseRequest

    release_request = PlayerReleaseRequest.objects.select_for_update().get(
        pk=release_request.pk
    )
    if release_request.status != ApprovalStatus.PENDING:
        raise ValueError("That release request is no longer pending.")
    release_request.status = ApprovalStatus.REJECTED
    release_request.reviewed_at = timezone.now()
    release_request.reviewed_by = reviewer
    if reason:
        release_request.reason = reason
    release_request.save(update_fields=["status", "reviewed_at", "reviewed_by", "reason"])
    from mgl.audit import log_ocm_action

    log_ocm_action(
        reviewer,
        action="player.release.reject",
        object_type="PlayerReleaseRequest",
        object_id=release_request.pk,
        object_label=release_request.player.name,
        new_value="REJECTED",
        summary=f"{release_request.player.name} release rejected.",
    )
    return release_request


@transaction.atomic
def release_player(player, team, source="MANAGER_RELEASE", reviewer=None):
    """
    Official release. Managers must go through request_player_release.
    Admin/Owner and the approval engine call this after review.
    """

    player = Player.objects.select_for_update().get(pk=player.pk)

    if player.mgl_team_id != team.id:
        raise ValueError("This player does not belong to this team.")

    if PlayerListing.objects.filter(
        player=player,
        status__in=[PlayerListing.PENDING, PlayerListing.LIVE],
    ).exists():
        raise ValueError("This player cannot be released while listed for transfer.")
    if PlayerAuction.objects.filter(
        player=player,
        status__in=[PlayerAuction.PENDING, PlayerAuction.LIVE],
    ).exists():
        raise ValueError("This player cannot be released while in an auction.")

    PlayerOwnershipHistory.objects.create(
        player=player,
        team=team,
        manager=team.manager,
        source=source,
        reference="",
    )

    player.mgl_team = None
    player.is_free_agent = True
    player.save(update_fields=["mgl_team", "is_free_agent"])

    create_news(
        NewsPost.FREE_AGENT,
        f"{player.name} released",
        f"{player.name} has been released by {team.name} and is now a Free Agent.",
        team=team,
    )
    if team.manager_id:
        from mgl.notifications import notify_user
        from mgl.press import create_release_press

        notify_user(
            team.manager,
            source_key=f"player-released-{player.pk}-{team.id}",
            notification_type="CLUB",
            title="PLAYER RELEASED",
            message=f"{player.name} has left {team.name} and is now a Free Agent.",
            actor=team.name,
            team=team,
            player=player,
        )
        create_release_press(team.manager, team, player)
    return player


@transaction.atomic
def assign_player(player, team, source="ADMIN", reference=""):
    """
    Central player assignment function.

    Enforces the UFL squad limit and prevents duplicate ownership.
    """

    player = Player.objects.select_for_update().get(pk=player.pk)
    team = Team.objects.select_for_update().get(pk=team.pk)

    from mgl.player_state import roster_occupancy
    from mgl.ufl_settings import effective_roster_limit

    roster_limit = effective_roster_limit(team)
    current_size = roster_occupancy(team)

    if current_size >= roster_limit:
        raise ValueError(
            f"{team.name} has reached its {roster_limit}-player roster limit."
        )

    if player.mgl_team_id and player.mgl_team_id != team.id:
        raise ValueError(
            f"{player.name} already belongs to another UFL club."
        )

    player.mgl_team = team
    player.is_free_agent = False
    player.save(update_fields=["mgl_team", "is_free_agent"])

    PlayerOwnershipHistory.objects.create(
        player=player,
        team=team,
        manager=team.manager,
        source=source,
        reference=str(reference or ""),
    )

    return player


@transaction.atomic
def sign_free_agent(player, manager):
    """Sign a Free Agent for 0 TKN onto the manager's club."""
    from mgl.market import assert_roster_space, club_for_user, record_market_transaction
    from mgl.models import MarketTransaction
    from mgl.player_state import player_is_in_live_auction

    if manager is None or getattr(manager, "status", None) != ManagerApplication.APPROVED:
        raise ValueError("You must be an approved manager to sign a Free Agent.")
    team = club_for_user(manager.user)
    if not team:
        raise ValueError("You must manage a club to sign a Free Agent.")
    player = Player.objects.select_for_update().get(pk=player.pk)
    if player_is_in_live_auction(player):
        raise ValueError("This player is in a live auction.")
    if player.mgl_team_id:
        raise ValueError("This player already belongs to a club.")
    if not player.is_free_agent:
        raise ValueError("Only Free Agents can be signed for free. Unassigned players are not Free Agents.")
    assert_roster_space(team)
    signed = assign_player(
        player,
        team,
        source="FREE_AGENT",
        reference=f"fa-sign:{manager.id}",
    )
    if not MarketTransaction.objects.filter(
        player=signed,
        buyer=manager,
        to_team=team,
        transaction_type=MarketTransaction.SALE,
        notes="Free agent signing",
    ).exists():
        record_market_transaction(
            player=signed,
            seller=None,
            buyer=manager,
            from_team=None,
            to_team=team,
            amount=Decimal("0.00"),
            transaction_type=MarketTransaction.SALE,
            status=MarketTransaction.COMPLETED,
            notes="Free agent signing",
        )
    create_news(
        NewsPost.SIGNING,
        f"{signed.name} signed",
        f"{signed.name} has joined {team.name} on a free signing.",
        team=team,
    )
    from mgl.press import maybe_create_signing_press

    maybe_create_signing_press(manager.user, team)
    return signed
