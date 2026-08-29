from decimal import Decimal
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from auctions.models import AuctionBid, PlayerAuction, TokenTransaction
from managers.models import ManagerApplication
from players.models import Player
from teams.models import Team

from .models import MarketTransaction, NewsPost, PlayerListing, PlayerOwnershipHistory
from .services import assign_player, create_news, manager_for_user


AUCTION_DURATION_CHOICES = (
    (30, "30 minutes"),
    (60, "60 minutes"),
    (90, "90 minutes"),
    (120, "120 minutes"),
    (180, "180 minutes"),
    (720, "12 hours"),
)
AUCTION_DURATIONS_MINUTES = tuple(minutes for minutes, _label in AUCTION_DURATION_CHOICES)
MAX_AUCTION_MINUTES = 720
MAX_ACTIVE_CLUB_LISTINGS = 6
MIN_AUCTION_STARTING_BID = 0
MAX_AUCTION_STARTING_BID = 10
MARKET_SLOT_MESSAGE = "Your club already has 6 active market listings."


def club_for_user(user):
    if not user or not user.is_authenticated:
        return None
    return getattr(user, "managed_team", None)


def token_balance_for_user(user):
    manager = manager_for_user(user)
    if manager:
        return manager.tokens
    return Decimal("0.00")


def lock_manager(manager):
    return ManagerApplication.objects.select_for_update().get(pk=manager.pk)


def debit_manager_tokens(manager, amount, reason, auction=None):
    amount = Decimal(str(amount))
    manager = lock_manager(manager)
    if manager.tokens < amount:
        raise ValueError("You do not have enough tokens.")
    manager.tokens = Decimal(manager.tokens) - amount
    manager.save(update_fields=["tokens"])
    record_token_transaction(
        manager,
        -int(amount),
        TokenTransaction.DEBIT,
        reason,
        auction=auction,
    )
    return manager


def credit_manager_tokens(manager, amount, reason, auction=None):
    amount = Decimal(str(amount))
    manager = lock_manager(manager)
    manager.tokens = Decimal(manager.tokens) + amount
    manager.save(update_fields=["tokens"])
    record_token_transaction(
        manager,
        int(amount),
        TokenTransaction.CREDIT,
        reason,
        auction=auction,
    )
    return manager


def lock_team(team):
    return Team.objects.select_for_update().get(pk=team.pk)


def debit_team_tokens(team, amount):
    """Deprecated club-treasury helper kept for unread legacy rows."""
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


def parse_auction_duration(value):
    try:
        minutes = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose a valid auction length.") from exc
    if minutes not in AUCTION_DURATIONS_MINUTES or minutes > MAX_AUCTION_MINUTES:
        raise ValueError("Auction length must be 30–180 minutes or 12 hours.")
    return minutes


def parse_auction_starting_bid(value):
    if value is None or str(value).strip() == "":
        raise ValueError("Enter a starting bid between 0 and 10 tokens.")
    try:
        amount = Decimal(str(value).strip())
    except Exception as exc:
        raise ValueError("Enter a starting bid between 0 and 10 tokens.") from exc
    if amount != amount.to_integral_value():
        raise ValueError("Starting bid must be a whole number from 0 to 10 tokens.")
    amount = int(amount)
    if amount < MIN_AUCTION_STARTING_BID or amount > MAX_AUCTION_STARTING_BID:
        raise ValueError("Starting bid must be between 0 and 10 tokens.")
    return amount


def parse_asking_price(value):
    if value is None or str(value).strip() == "":
        raise ValueError("Enter a starting transfer price.")
    try:
        price = Decimal(str(value).strip())
    except Exception as exc:
        raise ValueError("Enter a valid token asking price.") from exc
    if price <= 0:
        raise ValueError("Asking price must be greater than zero.")
    return price


def active_market_listing_count(team):
    if team is None:
        return 0
    transfers = PlayerListing.objects.filter(
        team=team,
        status__in=[PlayerListing.PENDING, PlayerListing.LIVE],
    ).count()
    auctions = PlayerAuction.objects.filter(
        origin_team=team,
        listing_kind=PlayerAuction.CLUB,
        status__in=[PlayerAuction.PENDING, PlayerAuction.LIVE],
    ).count()
    return transfers + auctions


def assert_roster_space(team, extra=1):
    if team is None:
        raise ValueError("You must manage a club.")
    roster_limit = getattr(team, "roster_limit", 30) or 30
    current_size = Player.objects.filter(mgl_team=team).count()
    if current_size + extra > roster_limit:
        raise ValueError(
            f"{team.name} has reached its {roster_limit}-player roster limit."
        )


def assert_club_listing_capacity(team):
    if active_market_listing_count(team) >= MAX_ACTIVE_CLUB_LISTINGS:
        raise ValueError(MARKET_SLOT_MESSAGE)


def _assert_no_live_auction(player):
    if PlayerAuction.objects.filter(
        player=player,
        status__in=[PlayerAuction.PENDING, PlayerAuction.LIVE],
    ).exists():
        raise ValueError("This player already has an active auction.")
    if PlayerListing.objects.filter(
        player=player,
        status__in=[PlayerListing.PENDING, PlayerListing.LIVE],
    ).exists():
        raise ValueError("This player is listed on the transfer market.")


@transaction.atomic
def create_free_agent_auction(player, user, duration_minutes, starting_bid=1):
    """Admin-only: release an UNASSIGNED player into the existing auction system."""
    from mgl.player_state import is_unassigned

    if getattr(user, "role", None) not in (User.OWNER, User.ADMIN):
        raise PermissionDenied(
            "Only an owner or admin can release an unassigned player to auction."
        )
    minutes = parse_auction_duration(duration_minutes)
    player = Player.objects.select_for_update().get(pk=player.pk)
    if player.mgl_team_id or player.is_free_agent or not is_unassigned(player):
        raise ValueError("Only unassigned players can be released to auction by an admin.")
    _assert_no_live_auction(player)
    bid = parse_auction_starting_bid(starting_bid)
    now = timezone.now()
    auction = PlayerAuction.objects.create(
        player=player,
        created_by=user,
        starting_bid=bid,
        minimum_increment=1,
        starts_at=now,
        ends_at=now + timedelta(minutes=minutes),
        status=PlayerAuction.LIVE,
        listing_kind=PlayerAuction.FREE_AGENT,
        listed_by_manager=None,
        origin_team=None,
        duration_minutes=minutes,
    )
    create_news(
        NewsPost.AUCTION,
        f"{player.name} is now available in an Admin auction",
        f"{player.name} is now available in an Admin auction.",
    )
    return auction


@transaction.atomic
def create_manager_auction(player, manager, duration_minutes, starting_bid=1):
    minutes = parse_auction_duration(duration_minutes)
    team = club_for_user(manager.user)
    if not team:
        raise ValueError("You must manage a club to auction a player.")
    player = Player.objects.select_for_update().get(pk=player.pk)
    if player.mgl_team_id != team.id or player.is_free_agent:
        raise ValueError("You can only auction a player who currently belongs to your club.")
    _assert_no_live_auction(player)
    assert_club_listing_capacity(team)
    bid = parse_auction_starting_bid(starting_bid)
    now = timezone.now()
    return PlayerAuction.objects.create(
        player=player,
        created_by=manager.user,
        starting_bid=bid,
        minimum_increment=1,
        starts_at=now,
        ends_at=now + timedelta(minutes=minutes),
        status=PlayerAuction.LIVE,
        listing_kind=PlayerAuction.CLUB,
        listed_by_manager=manager,
        origin_team=team,
        duration_minutes=minutes,
    )


def _restore_unsold_player(auction):
    player = Player.objects.select_for_update().get(pk=auction.player_id)
    if auction.listing_kind == PlayerAuction.CLUB and auction.origin_team_id:
        player.mgl_team_id = auction.origin_team_id
        player.is_free_agent = False
        player.save(update_fields=["mgl_team", "is_free_agent"])
        return player
    player.mgl_team = None
    player.is_free_agent = True
    player.save(update_fields=["mgl_team", "is_free_agent"])
    create_news(
        NewsPost.FREE_AGENT,
        f"{player.name} is a Free Agent",
        f"{player.name} is now available as a Free Agent after an auction received no bids.",
    )
    return player


@transaction.atomic
def transfer_player(player, from_team, to_team, source="TRANSFER", reference=""):
    player = Player.objects.select_for_update().get(pk=player.pk)
    to_team = Team.objects.select_for_update().get(pk=to_team.pk)

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
    assert_roster_space(team)

    try:
        amount = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a whole number of tokens.") from exc

    if amount <= 0:
        raise ValueError("Bid amount must be greater than zero.")

    player = Player.objects.select_for_update().get(pk=auction.player_id)
    if player.mgl_team_id == team.id:
        raise ValueError("You cannot bid on a player already at your club.")
    if auction.listed_by_manager_id == manager.id:
        raise ValueError("You cannot bid on your own auction.")

    # PostgreSQL rejects SELECT FOR UPDATE with select_related() on nullable FKs
    # (AuctionBid.team, PlayerAuction.winning_manager). Lock the bid rows only.
    highest_bid = (
        auction.bids.select_for_update()
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

    manager = lock_manager(manager)
    reserved = Decimal(previous_own.amount) if previous_own else Decimal("0")
    available = Decimal(manager.tokens) + reserved
    if Decimal(amount) > available:
        raise ValueError(f"You only have {available} available tokens.")

    if highest_bid and highest_bid.manager_id != manager.id:
        credit_manager_tokens(
            highest_bid.manager,
            highest_bid.amount,
            f"Outbid refund on {auction.player.name}",
            auction=auction,
        )
        record_market_transaction(
            player=auction.player,
            seller=None,
            buyer=highest_bid.manager,
            from_team=None,
            to_team=None,
            amount=highest_bid.amount,
            transaction_type=MarketTransaction.BID_REFUND,
            status=MarketTransaction.COMPLETED,
            auction=auction,
            notes="Refunded after being outbid",
        )
        auction.bids.filter(manager=highest_bid.manager).delete()

    if previous_own:
        credit_manager_tokens(
            manager,
            previous_own.amount,
            f"Replace bid on {auction.player.name}",
            auction=auction,
        )
        previous_own.delete()

    debit_manager_tokens(
        manager,
        amount,
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
    auction = PlayerAuction.objects.select_for_update().get(pk=auction.pk)

    if auction.status != PlayerAuction.LIVE:
        return auction, "Auction is no longer live."

    highest = (
        auction.bids.select_related("manager", "team")
        .order_by("-amount", "-created_at")
        .first()
    )

    if not highest:
        _restore_unsold_player(auction)
        auction.status = PlayerAuction.ENDED
        auction.save(update_fields=["status"])
        if auction.listing_kind == PlayerAuction.CLUB and auction.origin_team_id:
            return auction, "Auction ended with no bids."
        return auction, "Auction ended with no bids — Player is now a Free Agent."

    winner = highest.manager
    club = highest.team or club_for_user(winner.user)
    if not club:
        credit_manager_tokens(
            winner,
            highest.amount,
            f"Auction cancelled refund on {auction.player.name}",
            auction=auction,
        )
        _restore_unsold_player(auction)
        auction.status = PlayerAuction.CANCELLED
        auction.save(update_fields=["status"])
        return auction, "Winner no longer has a club. Bid refunded and auction cancelled."

    player = Player.objects.select_for_update().get(pk=auction.player_id)
    origin = auction.origin_team
    try:
        if origin and player.mgl_team_id == origin.id:
            transfer_player(
                player,
                origin,
                club,
                source="AUCTION",
                reference=f"auction:{auction.id}",
            )
        else:
            assign_player(
                player,
                club,
                source="AUCTION",
                reference=f"auction:{auction.id}",
            )
    except ValueError as exc:
        credit_manager_tokens(
            winner,
            highest.amount,
            f"Auction cancelled refund on {auction.player.name}",
            auction=auction,
        )
        _restore_unsold_player(auction)
        auction.status = PlayerAuction.CANCELLED
        auction.save(update_fields=["status"])
        return auction, str(exc)

    if auction.listed_by_manager_id:
        credit_manager_tokens(
            auction.listed_by_manager,
            highest.amount,
            f"Auction sale of {player.name}",
            auction=auction,
        )

    auction.status = PlayerAuction.ENDED
    auction.winning_manager = winner
    auction.winning_bid = highest.amount
    auction.save(update_fields=["status", "winning_manager", "winning_bid"])

    record_market_transaction(
        player=player,
        seller=auction.listed_by_manager,
        buyer=winner,
        from_team=origin,
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
        f"{player.name} has joined {club.name} after a winning auction bid.",
        team=club,
        secondary_team=origin,
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

    price = parse_asking_price(asking_price)
    _assert_no_live_auction(player)
    assert_club_listing_capacity(team)

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
        team=listing.team,
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
    assert_roster_space(buyer_club)

    debit_manager_tokens(
        buyer,
        listing.asking_price,
        f"Bought {listing.player.name} from {listing.team.name}",
    )
    credit_manager_tokens(
        listing.seller,
        listing.asking_price,
        f"Sold {listing.player.name} to {buyer_club.name}",
    )

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
        approved_by=listing.reviewed_by,
        listing=listing,
    )
    create_news(
        NewsPost.TRANSFER,
        f"{listing.player.name} transferred",
        f"{listing.player.name} has joined {buyer_club.name} from {listing.team.name}.",
        team=buyer_club,
        secondary_team=listing.team,
    )
    from mgl.press import maybe_create_signing_press

    maybe_create_signing_press(buyer.user, buyer_club)
    return listing


@transaction.atomic
def cancel_listing(listing, manager):
    listing = PlayerListing.objects.select_for_update().get(pk=listing.pk)
    if listing.seller_id != manager.id:
        raise ValueError("You can only withdraw your own listing.")
    if listing.status not in [PlayerListing.PENDING, PlayerListing.LIVE]:
        raise ValueError("This listing cannot be withdrawn.")
    listing.status = PlayerListing.CANCELLED
    listing.save(update_fields=["status"])
    return listing
