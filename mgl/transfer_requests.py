"""Helpers for the manager Transfers page.

Uses the existing PlayerListing offer workflow and MarketTransaction history.
Does not invent statuses, ownership, or approval rules.
"""

from decimal import Decimal

from django.db.models import Q, Sum

from managers.models import ManagerApplication
from mgl.market import club_for_user, listing_swap_players, transfer_offer_details
from mgl.models import MarketTransaction, PlayerListing
from teams.models import Team


LISTING_STATUS_LABELS = {
    PlayerListing.OFFER: "Pending",
    PlayerListing.PENDING: "Accepted",
    PlayerListing.REJECTED: "Rejected",
    PlayerListing.SOLD: "Completed",
    PlayerListing.CANCELLED: "Cancelled",
    PlayerListing.LIVE: "Live",
}


def _listing_queryset():
    return PlayerListing.objects.select_related(
        "player",
        "team",
        "seller",
        "reserved_buyer",
        "reserved_buyer__user",
        "offered_player",
    ).prefetch_related("offered_players")


def incoming_transfer_requests(club):
    """Offers aimed at this club's players. LIVE listings have no buyer yet."""
    if club is None:
        return PlayerListing.objects.none()
    return (
        _listing_queryset()
        .filter(team=club, reserved_buyer__isnull=False)
        .exclude(status=PlayerListing.LIVE)
        .order_by("-created_at", "-id")
    )


def outgoing_transfer_requests(manager):
    if manager is None:
        return PlayerListing.objects.none()
    return (
        _listing_queryset()
        .filter(reserved_buyer=manager)
        .order_by("-created_at", "-id")
    )


def incoming_offer_count(club):
    if club is None:
        return 0
    return PlayerListing.objects.filter(
        team=club,
        status=PlayerListing.OFFER,
        reserved_buyer__isnull=False,
    ).count()


def incoming_offer_count_for_user(user):
    return incoming_offer_count(club_for_user(user))


def listing_status_label(listing):
    return LISTING_STATUS_LABELS.get(listing.status, listing.get_status_display())


FILTER_STATUS_MAP = {
    "pending": {PlayerListing.OFFER},
    "awaiting-opponent": {PlayerListing.OFFER},
    "awaiting-admin": {PlayerListing.PENDING},
    "completed": {PlayerListing.SOLD},
    "rejected": {PlayerListing.REJECTED},
}


def decorate_transfer_request(listing, buyer_club=None):
    if buyer_club is None and listing.reserved_buyer_id:
        buyer_club = club_for_user(listing.reserved_buyer.user)
    details = transfer_offer_details(listing, buyer_club)
    listing.deal = details
    listing.buyer_club = buyer_club
    listing.status_label = listing_status_label(listing)
    listing.swap_players = listing_swap_players(listing)
    listing.can_seller_respond = listing.status == PlayerListing.OFFER
    listing.transfer_type = details.get("transfer_type") or "Transfer request"
    listing.filter_key = {
        PlayerListing.OFFER: "pending",
        PlayerListing.PENDING: "awaiting-admin",
        PlayerListing.SOLD: "completed",
        PlayerListing.REJECTED: "rejected",
        PlayerListing.CANCELLED: "rejected",
    }.get(listing.status, "pending")
    return listing


def filter_requests(rows, status):
    wanted = FILTER_STATUS_MAP.get(status)
    if not wanted:
        return list(rows)
    return [row for row in rows if row.status in wanted]


def format_tokens(amount):
    if amount is None:
        return "0"
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    if value == value.to_integral():
        return str(int(value))
    return f"{value:.2f}"


PLAYER_MOVEMENT_TYPES = (
    MarketTransaction.SALE,
    MarketTransaction.AUCTION,
    MarketTransaction.ADMIN_ASSIGN,
)


def completed_transfer_queryset():
    """Completed player movements only — never bid reserves, refunds, or live auctions."""
    from auctions.models import PlayerAuction

    return (
        MarketTransaction.objects.filter(
            status=MarketTransaction.COMPLETED,
            transaction_type__in=PLAYER_MOVEMENT_TYPES,
            player__isnull=False,
            to_team__isnull=False,
        )
        .exclude(
            auction__isnull=False,
            auction__status__in=[PlayerAuction.LIVE, PlayerAuction.PENDING],
        )
        .select_related(
            "player",
            "from_team",
            "to_team",
            "seller",
            "buyer",
            "auction",
        )
        .order_by("-completed_at", "-created_at", "-id")
    )


def decorate_completed_transfer(row):
    row.fee_label = format_tokens(row.amount)
    row.from_is_free_agent = (
        row.from_team_id is None
        and row.to_team_id is not None
        and row.transaction_type in PLAYER_MOVEMENT_TYPES
    )
    return row


def completed_transfers_for(club, *, all_clubs=False, limit=None):
    rows = completed_transfer_queryset()
    if club is not None and not all_clubs:
        rows = rows.filter(Q(from_team=club) | Q(to_team=club))
    if limit:
        rows = rows[:limit]
    return [decorate_completed_transfer(row) for row in rows]


def richest_assigned_managers(limit=8):
    teams = {
        team.manager_id: team
        for team in Team.objects.filter(manager__isnull=False).select_related("league")
    }
    ranked = []
    managers = (
        ManagerApplication.objects.filter(status=ManagerApplication.APPROVED)
        .select_related("user")
        .order_by("-tokens", "display_name")
    )
    for manager in managers:
        club = teams.get(manager.user_id)
        if club is None:
            continue
        name = (manager.display_name or manager.user.username or "?").strip()
        parts = name.split()
        initials = (
            f"{parts[0][:1]}{parts[1][:1]}".upper()
            if len(parts) >= 2
            else name[:2].upper()
        )
        ranked.append(
            {
                "manager": manager,
                "club": club,
                "tokens": manager.tokens,
                "tokens_label": format_tokens(manager.tokens),
                "initials": initials,
            }
        )
        if limit and len(ranked) >= limit:
            break
    return ranked


def transfer_centre_stats():
    completed = MarketTransaction.objects.filter(status=MarketTransaction.COMPLETED)
    spent = completed.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    active_managers = Team.objects.filter(manager__isnull=False).count()
    return {
        "total_transfers": completed.count(),
        "tokens_spent": format_tokens(spent),
        "managers_active": active_managers,
    }
