from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from auctions.models import PlayerAuction
from mgl.market import (
    close_expired_auctions,
    detach_live_club_auction_players,
    place_auction_bid,
    token_balance_for_user,
)
from mgl.permissions import approved_manager
from mgl.services import manager_for_user


@login_required
def live_auctions(request):
    close_expired_auctions()
    detach_live_club_auction_players()
    auctions = (
        PlayerAuction.objects.filter(status=PlayerAuction.LIVE)
        .select_related("player", "player__mgl_team", "winning_manager", "listed_by_manager", "origin_team")
        .order_by("ends_at")
    )
    ended = (
        PlayerAuction.objects.filter(status=PlayerAuction.ENDED)
        .select_related("player", "winning_manager", "origin_team")
        .order_by("-ends_at", "-id")[:12]
    )
    return render(
        request,
        "auctions/live_auctions.html",
        {
            "auctions": auctions,
            "ended_auctions": ended,
            "manager": manager_for_user(request.user),
            "token_balance": token_balance_for_user(request.user),
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
