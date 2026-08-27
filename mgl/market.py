from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from auctions.models import AuctionBid, PlayerAuction, TokenTransaction
from players.models import Player
from teams.models import Team

from .models import MarketTransaction, NewsPost, PlayerListing, PlayerOwnershipHistory
from .services import assign_player, create_news, manager_for_user


def club_for_user(user):
    if not user or not user.is_authenticated:
        return None
    return getattr(user, "managed_team", None)


def token_balance_for_user(user):
    team = club_for_user(user)
    if team is not None:
        return team.tokens
    manager = manager_for_user(user)
    if manager:
        return manager.tokens
    return Decimal("0.00")


def lock_team(team):
    return Team.objects.select_for_update().get(pk=team.pk)


def debit_team_tokens(team, amount):
    team = lock_team(team)
    amount = Decimal(str(amount))
    if team.tokens < amount:
        raise ValueError("This club does not have enough tokens.")
    team.tokens = Decimal(team.tokens) - amount
    team.save(update_fields=["tokens"])
    return team


def credit_team_tokens(team, amount):
    team = lock_team(team)
    amount = Decimal(str(amount))
    team.tokens = Decimal(team.tokens) + amount
    team.save(update_fields=["tokens"])
    return team


def record_market_transaction(**kwargs):
    kwargs.setdefault("status", MarketTransaction.COMPLETED)
    if kwargs["status"] == MarketTransaction.COMPLETED:
        kwargs.setdefault("completed_at", timezone.now())
    return MarketTransaction.objects.create(**kwargs)


def record_token_transaction(manager, amount, transaction_type, description, auction=None):
    if not manager:
        return None
    return TokenTransaction.objects.create(
        manager=manager,
        amount=int(amount),
        transaction_type=transaction_type,
        description=description,
        auction=auction,
    )


@transaction.atomic
def transfer_player(player, from_team, to_team, source="TRANSFER", reference=""):
    player = Player.objects.select_for_update().get(pk=player.pk)

    if from_team and player.mgl_team_id != from_team.id:
        raise ValueError("This player does not belong to the selling club.")

    roster_limit = getattr(to_team, "roster_limit", 30) or 30
    current_size = Player.objects.filter(mgl_team=to_team).count()
    if current_size >= roster_limit:
        raise ValueError(
            f"{to_team.name} has reached its {roster_limit}-player roster limit."
        )

    player.mgl_team = to_team
    player.is_free_agent = False
    player.save(update_fields=["mgl_team", "is_free_agent"])

    PlayerOwnershipHistory.objects.create(
        player=player,
        team=to_team,
        manager=to_team.manager,
        source=source,
        reference=str(reference or ""),
    )
    return player


@transaction.atomic
def place_auction_bid(auction, manager, amount):
    auction = PlayerAuction.objects.select_for_update().get(pk=auction.pk)
    now = timezone.now()

    if auction.status != PlayerAuction.LIVE:
        raise ValueError("This auction is not live.")
    if auction.starts_at and auction.starts_at > now:
        raise ValueError("This auction has not started yet.")
    if auction.ends_at and auction.ends_at <= now:
        raise ValueError("This auction has ended.")

    team = club_for_user(manager.user)
    if not team:
        raise ValueError("You must manage a club before placing a bid.")

    try:
        amount = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a whole number of tokens.") from exc

    highest_bid = (
        auction.bids.select_for_update()
        .select_related("manager", "team")
        .order_by("-amount", "-created_at")
        .first()
    )
    minimum_bid = auction.starting_bid
    if highest_bid:
        minimum_bid = highest_bid.amount + auction.minimum_increment

    if amount < minimum_bid:
        raise ValueError(f"Your bid must be at least {minimum_bid} tokens.")

    previous_own = (
        auction.bids.select_for_update()
        .filter(manager=manager)
        .order_by("-amount", "-created_at")
        .first()
    )

    team = lock_team(team)
    reserved = Decimal(previous_own.amount) if previous_own and previous_own.team_id == team.id else Decimal("0")
    available = Decimal(team.tokens) + reserved
    if Decimal(amount) > available:
        raise ValueError(f"{team.name} only has {available} available tokens.")

    if highest_bid and highest_bid.manager_id != manager.id:
        refund_team = highest_bid.team or club_for_user(highest_bid.manager.user)
        if refund_team:
            credit_team_tokens(refund_team, highest_bid.amount)
            record_token_transaction(
                highest_bid.manager,
                highest_bid.amount,
                TokenTransaction.REFUND,
                f"Outbid refund on {auction.player.name}",
                auction=auction,
            )
            record_market_transaction(
                player=auction.player,
                seller=None,
                buyer=highest_bid.manager,
                from_team=None,
                to_team=refund_team,
                amount=highest_bid.amount,
                transaction_type=MarketTransaction.BID_REFUND,
                status=MarketTransaction.COMPLETED,
                auction=auction,
                notes="Refunded after being outbid",
            )
        auction.bids.filter(manager=highest_bid.manager).delete()

    if previous_own:
        if previous_own.team_id == team.id:
            credit_team_tokens(team, previous_own.amount)
        previous_own.delete()

    debit_team_tokens(team, amount)
    record_token_transaction(
        manager,
        -amount,
        TokenTransaction.DEBIT,
        f"Bid reserve on {auction.player.name}",
        auction=auction,
    )

    AuctionBid.objects.create(
        auction=auction,
        manager=manager,
        team=team,
        amount=amount,
    )

    auction.winning_manager = manager
    auction.winning_bid = amount
    auction.save(update_fields=["winning_manager", "winning_bid"])
    return auction


@transaction.atomic
def settle_auction(auction, reviewer=None):
    auction = PlayerAuction.objects.select_for_update().select_related(
        "player",
        "winning_manager",
        "winning_manager__user",
    ).get(pk=auction.pk)

    if auction.status != PlayerAuction.LIVE:
        return auction, "Auction is no longer live."

    highest = (
        auction.bids.select_related("manager", "team")
        .order_by("-amount", "-created_at")
        .first()
    )

    if not highest:
        auction.status = PlayerAuction.ENDED
        auction.save(update_fields=["status"])
        return auction, "Auction ended with no bids."

    winner = highest.manager
    club = highest.team or club_for_user(winner.user)
    if not club:
        if highest.team:
            credit_team_tokens(highest.team, highest.amount)
        auction.status = PlayerAuction.CANCELLED
        auction.save(update_fields=["status"])
        return auction, "Winner no longer has a club. Bid refunded and auction cancelled."

    player = Player.objects.select_for_update().get(pk=auction.player_id)
    assign_player(
        player,
        club,
        source="AUCTION",
        reference=f"auction:{auction.id}",
    )

    auction.status = PlayerAuction.ENDED
    auction.winning_manager = winner
    auction.winning_bid = highest.amount
    auction.save(update_fields=["status", "winning_manager", "winning_bid"])

    record_market_transaction(
        player=player,
        seller=None,
        buyer=winner,
        from_team=None,
        to_team=club,
        amount=highest.amount,
        transaction_type=MarketTransaction.AUCTION,
        status=MarketTransaction.COMPLETED,
        approved_by=reviewer,
        auction=auction,
    )
    create_news(
        NewsPost.AUCTION,
        f"{player.name} sold at auction",
        f"{club.name} signed {player.name} for {highest.amount} tokens.",
    )
    return auction, f"{player.name} transferred to {club.name}."


def close_expired_auctions(reviewer=None):
    now = timezone.now()
    expired = PlayerAuction.objects.filter(
        status=PlayerAuction.LIVE,
        ends_at__lte=now,
    )
    closed = 0
    for auction in expired:
        settle_auction(auction, reviewer=reviewer)
        closed += 1
    return closed


@transaction.atomic
def list_player_for_sale(player, manager, asking_price):
    team = club_for_user(manager.user)
    if not team:
        raise ValueError("You must manage a club to sell a player.")

    player = Player.objects.select_for_update().get(pk=player.pk)
    if player.mgl_team_id != team.id:
        raise ValueError("You can only sell a player who belongs to your club.")

    try:
        price = Decimal(str(asking_price))
    except Exception as exc:
        raise ValueError("Enter a valid token asking price.") from exc

    if price <= 0:
        raise ValueError("Asking price must be greater than zero.")

    if PlayerListing.objects.filter(
        player=player,
        status__in=[PlayerListing.PENDING, PlayerListing.LIVE],
    ).exists():
        raise ValueError("This player is already listed.")

    if PlayerAuction.objects.filter(
        player=player,
        status__in=[PlayerAuction.PENDING, PlayerAuction.LIVE],
    ).exists():
        raise ValueError("This player is currently in an auction.")

    return PlayerListing.objects.create(
        player=player,
        team=team,
        seller=manager,
        asking_price=price,
        status=PlayerListing.PENDING,
    )


@transaction.atomic
def approve_listing(listing, reviewer):
    listing = PlayerListing.objects.select_for_update().select_related("player").get(pk=listing.pk)
    if listing.status != PlayerListing.PENDING:
        raise ValueError("This listing is not waiting for approval.")
    listing.status = PlayerListing.LIVE
    listing.reviewed_at = timezone.now()
    listing.reviewed_by = reviewer
    listing.save(update_fields=["status", "reviewed_at", "reviewed_by"])
    create_news(
        NewsPost.TRANSFER,
        f"{listing.player.name} listed for sale",
        f"{listing.team.name} listed {listing.player.name} for {listing.asking_price} tokens.",
    )
    return listing


@transaction.atomic
def reject_listing(listing, reviewer):
    listing = PlayerListing.objects.select_for_update().get(pk=listing.pk)
    if listing.status != PlayerListing.PENDING:
        raise ValueError("This listing is not waiting for approval.")
    listing.status = PlayerListing.REJECTED
    listing.reviewed_at = timezone.now()
    listing.reviewed_by = reviewer
    listing.save(update_fields=["status", "reviewed_at", "reviewed_by"])
    return listing


@transaction.atomic
def buy_listed_player(listing, buyer):
    listing = PlayerListing.objects.select_for_update().select_related(
        "player",
        "team",
        "seller",
    ).get(pk=listing.pk)

    if listing.status != PlayerListing.LIVE:
        raise ValueError("This player is not available for purchase.")

    buyer_club = club_for_user(buyer.user)
    if not buyer_club:
        raise ValueError("You must manage a club to buy a player.")
    if buyer_club.id == listing.team_id:
        raise ValueError("You already own this player.")
    if listing.seller_id == buyer.id:
        raise ValueError("You cannot buy your own listing.")

    debit_team_tokens(buyer_club, listing.asking_price)
    credit_team_tokens(listing.team, listing.asking_price)

    transfer_player(
        listing.player,
        listing.team,
        buyer_club,
        source="TRANSFER",
        reference=f"listing:{listing.id}",
    )

    listing.status = PlayerListing.SOLD
    listing.sold_to = buyer
    listing.sold_at = timezone.now()
    listing.save(update_fields=["status", "sold_to", "sold_at"])

    record_market_transaction(
        player=listing.player,
        seller=listing.seller,
        buyer=buyer,
        from_team=listing.team,
        to_team=buyer_club,
        amount=listing.asking_price,
        transaction_type=MarketTransaction.SALE,
        status=MarketTransaction.COMPLETED,
        listing=listing,
    )
    record_token_transaction(
        buyer,
        -int(listing.asking_price),
        TokenTransaction.DEBIT,
        f"Bought {listing.player.name} from {listing.team.name}",
    )
    record_token_transaction(
        listing.seller,
        int(listing.asking_price),
        TokenTransaction.CREDIT,
        f"Sold {listing.player.name} to {buyer_club.name}",
    )
    create_news(
        NewsPost.TRANSFER,
        f"{listing.player.name} transferred",
        f"{listing.player.name} moved from {listing.team.name} to {buyer_club.name} "
        f"for {listing.asking_price} tokens.",
    )
    return listing
