"""UFL player market states.

UNASSIGNED       — unused FC26 pool; never released to auction; no club.
AUCTION          — live or pending auction.
FREE_AGENT       — no-bid auction (or an approved club release).
ASSIGNED         — belongs to a UFL club.
TRANSFER_LISTED  — owned and listed on the transfer market.
IN_NEGOTIATION   — owned and a live offer is being negotiated.

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
ASSIGNED = "ASSIGNED"
TRANSFER_LISTED = "TRANSFER LISTED"
IN_NEGOTIATION = "IN NEGOTIATION"

LIVE_AUCTION_STATUSES = (PlayerAuction.PENDING, PlayerAuction.LIVE)
LIVE_LISTING_STATUSES = (PlayerListing.PENDING, PlayerListing.LIVE)
NEGOTIATION_STATUSES = (PlayerListing.OFFER, PlayerListing.PENDING)


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
    pk = getattr(player, "pk", None)
    if player_is_in_live_auction(player):
        return AUCTION
    if pk and PlayerListing.objects.filter(
        player_id=pk, status__in=NEGOTIATION_STATUSES
    ).exists():
        return IN_NEGOTIATION
    if pk and PlayerListing.objects.filter(
        player_id=pk, status__in=LIVE_LISTING_STATUSES
    ).exists():
        return TRANSFER_LISTED
    if getattr(player, "mgl_team_id", None):
        return ASSIGNED
    if getattr(player, "is_free_agent", False):
        return FREE_AGENT
    return UNASSIGNED


def market_status_label(player):
    status = market_status(player)
    team = getattr(player, "mgl_team", None)
    if status in {CLUB_PLAYER, ASSIGNED} and team is not None:
        return team.short_name
    return status


def is_unassigned(player):
    return (
        getattr(player, "mgl_team_id", None) is None
        and not getattr(player, "is_free_agent", False)
        and not player_is_in_live_auction(player)
    )
