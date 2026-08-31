from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from auctions.models import AuctionBid, PlayerAuction
from mgl.market import (
    close_expired_auctions,
    detach_live_club_auction_players,
    place_auction_bid,
    token_balance_for_user,
)
from mgl.permissions import approved_manager
from mgl.services import manager_for_user
from players.search import matching_player_ids

POSITION_GROUPS = {
    "GK": ("GK",),
    "DEF": ("CB", "LB", "RB", "LWB", "RWB"),
    "MID": ("CDM", "CM", "CAM", "LM", "RM"),
    "ATT": ("LW", "RW", "ST", "CF"),
}


def _querystring(request):
    query = request.GET.copy()
    query.pop("page", None)
    query.pop("auction", None)
    return query.urlencode()


def _minimum_bid(auction):
    highest = next(iter(auction.bids.all()), None)
    if highest:
        return highest.amount + auction.minimum_increment
    return auction.starting_bid


def _attach_bid_meta(auctions):
    for auction in auctions:
        computed = _minimum_bid(auction)
        auction.current_bid = auction.winning_bid or auction.starting_bid
        auction.min_bid = computed
        auction.input_min = max(int(computed or 0), 1)
        auction.bid_total = getattr(auction, "bid_count", None)
        if auction.bid_total is None:
            auction.bid_total = len(auction.bids.all())
    return auctions


@login_required
def live_auctions(request):
    close_expired_auctions()
    detach_live_club_auction_players()
    live_qs = (
        PlayerAuction.objects.filter(status=PlayerAuction.LIVE)
        .select_related(
            "player",
            "player__mgl_team",
            "winning_manager",
            "listed_by_manager",
            "origin_team",
        )
        .annotate(bid_count=Count("bids"))
        .prefetch_related(
            Prefetch(
                "bids",
                queryset=AuctionBid.objects.order_by("-amount", "-created_at"),
            )
        )
        .order_by("ends_at")
    )
    live_count = live_qs.count()
    live_bid_count = AuctionBid.objects.filter(auction__status=PlayerAuction.LIVE).count()

    search = request.GET.get("search", "").strip()
    position = request.GET.get("position", "").strip()
    auctions = live_qs
    if search:
        auctions = auctions.filter(player_id__in=matching_player_ids(search))
    if position in POSITION_GROUPS:
        auctions = auctions.filter(player__position__in=POSITION_GROUPS[position])
    elif position:
        auctions = auctions.filter(player__position=position)

    per_page_raw = request.GET.get("per_page", "").strip()
    page_size = 10
    if per_page_raw.isdigit() and int(per_page_raw) in {10, 20, 40}:
        page_size = int(per_page_raw)
    page = Paginator(auctions, page_size).get_page(request.GET.get("page"))
    _attach_bid_meta(page.object_list)

    ended = (
        PlayerAuction.objects.filter(status=PlayerAuction.ENDED)
        .select_related("player", "winning_manager", "origin_team")
        .order_by("-ends_at", "-id")[:12]
    )

    manager = manager_for_user(request.user)
    my_won = 0
    if manager:
        my_won = PlayerAuction.objects.filter(
            status=PlayerAuction.ENDED,
            winning_manager=manager,
        ).count()

    open_auction = None
    open_raw = request.GET.get("auction", "").strip()
    if open_raw.isdigit():
        open_auction = next((item for item in page.object_list if item.id == int(open_raw)), None)
        if open_auction is None:
            match = live_qs.filter(pk=int(open_raw)).first()
            if match:
                _attach_bid_meta([match])
                open_auction = match

    return render(
        request,
        "auctions/live_auctions.html",
        {
            "auctions": page,
            "page_obj": page,
            "ended_auctions": ended,
            "manager": manager,
            "token_balance": token_balance_for_user(request.user),
            "search": search,
            "selected_position": position,
            "per_page": page_size,
            "querystring": _querystring(request),
            "result_count": page.paginator.count,
            "live_count": live_count,
            "live_bid_count": live_bid_count,
            "my_won": my_won,
            "open_auction": open_auction,
        },
    )


@login_required
@require_POST
def place_bid(request, auction_id):
    manager = approved_manager(request.user)
    if not manager:
        messages.error(request, "You must be an approved manager to bid.")
        return redirect("live_auctions")
    close_expired_auctions()
    auction = get_object_or_404(PlayerAuction, pk=auction_id)
    try:
        place_auction_bid(auction, manager, request.POST.get("amount"))
        messages.success(request, "Bid placed successfully.")
    except ValueError as exc:
        messages.error(request, str(exc))
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("live_auctions")
