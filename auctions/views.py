from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from managers.models import ManagerApplication

from .models import AuctionBid, PlayerAuction


@login_required
def live_auctions(request):
    auctions = PlayerAuction.objects.filter(
        status=PlayerAuction.LIVE,
        starts_at__lte=timezone.now(),
        ends_at__gt=timezone.now(),
    ).select_related("player")

    return render(
        request,
        "auctions/live_auctions.html",
        {"auctions": auctions},
    )


@login_required
@transaction.atomic
def place_bid(request, auction_id):
    auction = get_object_or_404(
        PlayerAuction.objects.select_for_update(),
        id=auction_id,
        status=PlayerAuction.LIVE,
    )

    if request.method != "POST":
        return redirect("live_auctions")

    if auction.starts_at and auction.starts_at > timezone.now():
        messages.error(request, "This auction has not started yet.")
        return redirect("live_auctions")

    if auction.ends_at and auction.ends_at <= timezone.now():
        messages.error(request, "This auction has ended.")
        return redirect("live_auctions")

    try:
        manager = request.user.manager_application
    except ManagerApplication.DoesNotExist:
        messages.error(request, "You are not registered as a manager.")
        return redirect("live_auctions")

    if manager.status != ManagerApplication.APPROVED:
        messages.error(request, "Your manager account is not approved.")
        return redirect("live_auctions")

    try:
        amount = int(request.POST.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0

    highest_bid = auction.bids.select_for_update().first()

    minimum_bid = auction.starting_bid

    if highest_bid:
        minimum_bid = highest_bid.amount + auction.minimum_increment

    # If this manager already has the highest bid, their previous
    # bid is released before calculating their new available balance.
    previous_manager_bid = auction.bids.filter(
        manager=manager
    ).order_by("-amount", "-created_at").first()

    available_tokens = manager.tokens

    if previous_manager_bid:
        available_tokens += previous_manager_bid.amount

    if amount < minimum_bid:
        messages.error(
            request,
            f"Your bid must be at least {minimum_bid} tokens.",
        )
        return redirect("live_auctions")

    if amount > available_tokens:
        messages.error(
            request,
            f"You only have {available_tokens} available tokens.",
        )
        return redirect("live_auctions")

    # Remove this manager's previous bid on this auction.
    if previous_manager_bid:
        previous_manager_bid.delete()

    # Reserve the new bid amount.
    manager.tokens = available_tokens - amount
    manager.save(update_fields=["tokens"])

    AuctionBid.objects.create(
        auction=auction,
        manager=manager,
        amount=amount,
    )

    auction.winning_manager = manager
    auction.winning_bid = amount
    auction.save(
        update_fields=[
            "winning_manager",
            "winning_bid",
        ]
    )

    messages.success(
        request,
        f"Bid of {amount} tokens placed successfully.",
    )

    return redirect("live_auctions")
