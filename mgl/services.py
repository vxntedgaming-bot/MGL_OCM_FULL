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
def credit_manager(manager, amount, reason, category="OTHER", fixture=None):
    """
    Add tokens to a manager and permanently record the reward.
    """

    amount = Decimal(str(amount))

    manager = (
        ManagerApplication.objects
        .select_for_update()
        .get(pk=manager.pk)
    )

    manager.tokens = Decimal(manager.tokens) + amount
    manager.save(update_fields=["tokens"])

    return RewardTransaction.objects.create(
        manager=manager,
        amount=amount,
        reason=reason,
        category=category,
        fixture=fixture,
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


def create_news(category, title, body, publish=True):
    """
    Creates a news event for the website and Discord bot queue.
    """

    return NewsPost.objects.create(
        category=category,
        title=title,
        body=body,
        published=publish,
        discord_sent=False,
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
        f"{team.name} have released {player.name}. "
        f"The player is now available as a free agent.",
    )

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

    roster_limit = getattr(team, "roster_limit", 30) or 30
    current_size = Player.objects.filter(mgl_team=team).count()

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
    from mgl.market import assert_roster_space, club_for_user
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
    return assign_player(
        player,
        team,
        source="FREE_AGENT",
        reference=f"fa-sign:{manager.id}",
    )
