"""MGL player market states.

UNASSIGNED  — unused FC26 pool; never released to auction; no club.
AUCTION     — live or pending auction.
FREE AGENT  — no-bid auction (or a club release); available for FA signing.
CLUB PLAYER — belongs to an MGL club.

Do not treat the unused FC26 pool as Free Agents.
"""

from django.db.models import Q

from auctions.models import PlayerAuction
from mgl.models import PlayerListing
from players.models import Player


UNASSIGNED = "UNASSIGNED"
FREE_AGENT = "FREE AGENT"
AUCTION = "AUCTION"
CLUB_PLAYER = "CLUB PLAYER"

LIVE_AUCTION_STATUSES = (PlayerAuction.PENDING, PlayerAuction.LIVE)
LIVE_LISTING_STATUSES = (PlayerListing.PENDING, PlayerListing.LIVE)


def live_auction_player_ids():
    return PlayerAuction.objects.filter(status__in=LIVE_AUCTION_STATUSES).values_list(
        "player_id", flat=True
    )


def unavailable_player_q():
    live_listings = PlayerListing.objects.filter(status__in=LIVE_LISTING_STATUSES).values_list(
        "player_id", flat=True
    )
    return Q(id__in=live_auction_player_ids()) | Q(id__in=live_listings)


def unassigned_players():
    """Unused FC26 pool: no club, not a free agent, not in a live auction."""
    return Player.objects.filter(
        mgl_team__isnull=True,
        is_free_agent=False,
    ).exclude(id__in=live_auction_player_ids())


def free_agents():
    """Players who entered Free Agent state after a no-bid auction or club release."""
    return Player.objects.filter(
        mgl_team__isnull=True,
        is_free_agent=True,
    ).exclude(id__in=live_auction_player_ids())


def club_players():
    return Player.objects.filter(mgl_team__isnull=False)


def reserved_club_auction_player_ids(team):
    if team is None:
        return PlayerAuction.objects.none().values_list("player_id", flat=True)
    return PlayerAuction.objects.filter(
        origin_team=team,
        listing_kind=PlayerAuction.CLUB,
        status__in=LIVE_AUCTION_STATUSES,
    ).values_list("player_id", flat=True)


def roster_occupancy(team):
    """Players on the club plus those held by a live club auction from this club."""
    if team is None:
        return 0
    return (
        Player.objects.filter(Q(mgl_team=team) | Q(id__in=reserved_club_auction_player_ids(team)))
        .distinct()
        .count()
    )


def live_auctions():
    return PlayerAuction.objects.filter(status__in=LIVE_AUCTION_STATUSES)


def market_counts():
    return {
        "unassigned": unassigned_players().count(),
        "free_agents": free_agents().count(),
        "auctions": live_auctions().count(),
        "club_players": club_players().count(),
        "players": Player.objects.count(),
    }


def player_is_in_live_auction(player):
    pk = getattr(player, "pk", None)
    if not pk:
        return False
    return PlayerAuction.objects.filter(
        player_id=pk,
        status__in=LIVE_AUCTION_STATUSES,
    ).exists()


def market_status(player):
    if getattr(player, "mgl_team_id", None):
        return CLUB_PLAYER
    if player_is_in_live_auction(player):
        return AUCTION
    if getattr(player, "is_free_agent", False):
        return FREE_AGENT
    return UNASSIGNED


def market_status_label(player):
    status = market_status(player)
    team = getattr(player, "mgl_team", None)
    if status == CLUB_PLAYER and team is not None:
        return team.short_name
    return status


def is_unassigned(player):
    return (
        getattr(player, "mgl_team_id", None) is None
        and not getattr(player, "is_free_agent", False)
        and not player_is_in_live_auction(player)
    )
