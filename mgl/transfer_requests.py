"""Helpers for the manager Transfer Requests page.

Uses the existing PlayerListing offer workflow. Does not invent statuses,
ownership, or approval rules.
"""

from mgl.market import club_for_user, listing_swap_players, transfer_offer_details
from mgl.models import PlayerListing


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
    return listing
