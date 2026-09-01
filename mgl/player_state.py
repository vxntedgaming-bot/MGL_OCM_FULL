"""UFL player market states.

UNSIGNED / UNASSIGNED — FC26 player with no UFL club. Recruitment pool.
                        Not a UFL Free Agent. Ignore legacy is_free_agent.
AUCTION               — live or pending auction.
FREE_AGENT            — entered FA through an explicit UFL process
                        (club release, no-bid admin/unsigned auction, etc.).
ASSIGNED              — belongs to a UFL club.
TRANSFER_LISTED       — owned and listed on the transfer market.
IN_NEGOTIATION        — owned and a live offer is being negotiated.

Genuine UFL Free Agent status is `Player.released_at` (set only by UFL
processes). Do not treat the unused FC26 pool or the legacy
`is_free_agent` flag as the product status (DEC-042).
"""

from django.db.models import Q
from django.utils import timezone

from auctions.models import PlayerAuction
from mgl.models import PlayerListing
from players.models import Player


UNASSIGNED = "UNASSIGNED"
UNSIGNED = "UNSIGNED"
FREE_AGENT = "FREE AGENT"
UFL_FREE_AGENT = "UFL FREE AGENT"
AUCTION = "AUCTION"
CLUB_PLAYER = "CLUB PLAYER"
CLUB_OWNED = "CLUB-OWNED"
ASSIGNED = "ASSIGNED"
TRANSFER_LISTED = "TRANSFER LISTED"
TEMPORARILY_LISTED = "TEMPORARILY LISTED"
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


def unsigned_q():
    """UNSIGNED: no UFL club and never entered a genuine UFL FA process."""
    return Q(mgl_team__isnull=True, released_at__isnull=True)


def ufl_free_agent_q():
    """Genuine UFL Free Agent: entered FA through an explicit UFL process."""
    return Q(mgl_team__isnull=True, released_at__isnull=False)


def is_ufl_free_agent(player):
    return (
        getattr(player, "mgl_team_id", None) is None
        and getattr(player, "released_at", None) is not None
    )


def enter_ufl_free_agency(player, when=None):
    """Mark a player as a genuine UFL Free Agent. Does not mass-edit the pool."""
    player.mgl_team = None
    player.is_free_agent = True
    player.released_at = when or timezone.now()
    player.save(update_fields=["mgl_team", "is_free_agent", "released_at"])
    return player


def clear_ufl_free_agency(player):
    player.is_free_agent = False
    player.released_at = None
    return player


def unassigned_players():
    """UNSIGNED FC26 pool: no club, not a genuine UFL FA, not in a live auction."""
    return Player.objects.filter(unsigned_q()).exclude(id__in=live_auction_player_ids())


def free_agents():
    """Genuine UFL Free Agents only. Does not list the unused FC26 pool."""
    return Player.objects.filter(ufl_free_agent_q()).exclude(id__in=live_auction_player_ids())


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


def ufl_player_status(player):
    """Locked UFL product status. Legacy `is_free_agent` never wins."""
    if player_is_in_live_auction(player):
        return TEMPORARILY_LISTED
    if getattr(player, "mgl_team_id", None):
        return CLUB_OWNED
    if is_ufl_free_agent(player):
        return UFL_FREE_AGENT
    return UNSIGNED


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
    if is_ufl_free_agent(player):
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
        and not is_ufl_free_agent(player)
        and not player_is_in_live_auction(player)
    )
