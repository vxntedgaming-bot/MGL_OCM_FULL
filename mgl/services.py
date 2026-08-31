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


@transaction.atomic
@transaction.atomic
def credit_manager(manager, amount, reason, category="OTHER", fixture=None, reference=""):
    """
    Add tokens to a manager and permanently record the reward.
    If reference is set, the same manager/category/reference pays only once.
    """

    amount = Decimal(str(amount))
    reference = (reference or "").strip()

    manager = (
        ManagerApplication.objects
        .select_for_update()
        .get(pk=manager.pk)
    )

    if reference:
        existing = RewardTransaction.objects.filter(
            manager=manager,
            category=category,
            reference=reference,
        ).first()
        if existing:
            return existing

    manager.tokens = Decimal(manager.tokens) + amount
    manager.save(update_fields=["tokens"])

    return RewardTransaction.objects.create(
        manager=manager,
        amount=amount,
        reason=reason,
        category=category,
        fixture=fixture,
        reference=reference,
    )


@transaction.atomic
def debit_manager(manager, amount, reason, category="OTHER", fixture=None):
    """
    Remove tokens safely and permanently record the transaction.
    """

    amount = Decimal(str(amount))

    manager = (
        ManagerApplication.objects
        .select_for_update()
        .get(pk=manager.pk)
    )

    if manager.tokens < amount:
        raise ValueError("Manager does not have enough tokens.")

    manager.tokens = Decimal(manager.tokens) - amount
    manager.save(update_fields=["tokens"])

    return RewardTransaction.objects.create(
        manager=manager,
        amount=-amount,
        reason=reason,
        category=category,
        fixture=fixture,
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

    return NewsPost.objects.create(
        category=category,
        title=title,
        body=body,
        published=publish,
        discord_sent=False,
        primary_team=team,
        secondary_team=secondary_team,
        details=details or {},
    )


@transaction.atomic
def release_player(player, team, source="MANAGER_RELEASE"):
    """
    Manager releases are immediate and do not require admin approval.
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

    Enforces the MGL 30-player roster limit and prevents duplicate
    ownership.
    """

    player = Player.objects.select_for_update().get(pk=player.pk)
    team = Team.objects.select_for_update().get(pk=team.pk)

    from mgl.player_state import roster_occupancy

    roster_limit = getattr(team, "roster_limit", 30) or 30
    current_size = roster_occupancy(team)

    if current_size >= roster_limit:
        raise ValueError(
            f"{team.name} has reached its {roster_limit}-player roster limit."
        )

    if player.mgl_team_id and player.mgl_team_id != team.id:
        raise ValueError(
            f"{player.name} already belongs to another MGL club."
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
