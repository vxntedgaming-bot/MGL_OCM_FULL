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


def auction_duration_choice_tuples():
    from mgl.ufl_settings import auction_duration_choices

    return auction_duration_choices()


AUCTION_DURATION_CHOICES = (
    (30, "30 minutes"),
    (60, "60 minutes"),
    (90, "90 minutes"),
    (120, "120 minutes"),
)
AUCTION_DURATIONS_MINUTES = (30, 60, 90, 120)
MAX_AUCTION_MINUTES = 120
MAX_ACTIVE_CLUB_LISTINGS = 5
MIN_AUCTION_STARTING_BID = 0
MAX_AUCTION_STARTING_BID = 10
MARKET_SLOT_MESSAGE = "Your club already has 5 active market listings."
LISTING_FREQUENCY_MESSAGE = "You can list at most 3 players every 24 hours."


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
    from mgl.services import debit_manager

    amount = Decimal(str(amount))
    try:
        debit_manager(
            manager,
            amount,
            reason,
            category="MARKET",
        )
    except ValueError as exc:
        if "enough tokens" in str(exc).lower():
            raise ValueError("You do not have enough tokens.") from exc
        raise
    manager = lock_manager(manager)
    record_token_transaction(
        manager,
        -int(amount),
        TokenTransaction.DEBIT,
        reason,
        auction=auction,
    )
    return manager


def credit_manager_tokens(manager, amount, reason, auction=None):
    from mgl.services import credit_manager

    amount = Decimal(str(amount))
    credit_manager(
        manager,
        amount,
        reason,
        category="MARKET",
    )
    manager = lock_manager(manager)
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


def completed_auction_transfer(auction):
    if auction is None:
        return None
    return (
        MarketTransaction.objects.filter(
            auction=auction,
            transaction_type=MarketTransaction.AUCTION,
            status=MarketTransaction.COMPLETED,
        )
        .order_by("id")
        .first()
    )


def record_completed_auction_transfer(
    *,
    auction,
    player,
    seller,
    buyer,
    from_team,
    to_team,
    amount,
    approved_by=None,
):
    """Create one AUCTION history row per auction. Safe to call again."""
    existing = completed_auction_transfer(auction)
    if existing:
        return existing
    if to_team is None or player is None:
        return None
    return record_market_transaction(
        player=player,
        seller=seller,
        buyer=buyer,
        from_team=from_team,
        to_team=to_team,
        amount=amount,
        transaction_type=MarketTransaction.AUCTION,
        status=MarketTransaction.COMPLETED,
        approved_by=approved_by,
        auction=auction,
    )


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
    from mgl.ufl_settings import auction_duration_choices

    try:
        minutes = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose a valid auction length.") from exc
    allowed = tuple(choice[0] for choice in auction_duration_choices()) or AUCTION_DURATIONS_MINUTES
    if minutes not in allowed or minutes > MAX_AUCTION_MINUTES:
        raise ValueError("Auction length must be 30, 60, 90 or 120 minutes.")
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
    from mgl.player_state import roster_occupancy
    from mgl.ufl_settings import effective_roster_limit

    roster_limit = effective_roster_limit(team)
    current_size = roster_occupancy(team)
    if current_size + extra > roster_limit:
        raise ValueError(
            f"{team.name} has reached its {roster_limit}-player roster limit."
        )


def assert_club_listing_capacity(team):
    from mgl.ufl_settings import max_active_listings

    limit = max_active_listings()
    if active_market_listing_count(team) >= limit:
        raise ValueError(f"Your club already has {limit} active market listings.")


def assert_listing_frequency(manager):
    from mgl.ufl_settings import listings_per_24h

    limit = listings_per_24h()
    if not manager or limit <= 0:
        return
    since = timezone.now() - timedelta(hours=24)
    created = PlayerListing.objects.filter(seller=manager, created_at__gte=since).count()
    if created >= limit:
        raise ValueError(f"You can list at most {limit} players every 24 hours.")


def assert_auction_listing_frequency(manager):
    from mgl.ufl_settings import auction_listings_per_24h

    limit = auction_listings_per_24h()
    if not manager or limit <= 0:
        return
    since = timezone.now() - timedelta(hours=24)
    created = PlayerAuction.objects.filter(
        listed_by_manager=manager,
        listing_kind=PlayerAuction.CLUB,
        created_at__gte=since,
    ).count()
    if created >= limit:
        raise ValueError(f"You can submit at most {limit} players to auction every 24 hours.")


def transfer_window_is_open():
    """MGL currently keeps the window open. Shared hook for buy/list checks."""
    return True


def assert_transfer_window():
    if not transfer_window_is_open():
        raise ValueError("The transfer window is closed.")


def _assert_player_unlocked(player, exclude_listing_id=None):
    if PlayerAuction.objects.filter(
        player=player,
        status__in=[PlayerAuction.PENDING, PlayerAuction.LIVE],
    ).exists():
        raise ValueError("This player already has an active auction.")
    listings = PlayerListing.objects.filter(
        player=player,
        status__in=[
            PlayerListing.PENDING,
            PlayerListing.LIVE,
            PlayerListing.OFFER,
        ],
    )
    swaps = PlayerListing.objects.filter(
        offered_player=player,
        status__in=[
            PlayerListing.PENDING,
            PlayerListing.LIVE,
            PlayerListing.OFFER,
        ],
    )
    multi_swaps = PlayerListing.objects.filter(
        offered_players=player,
        status__in=[
            PlayerListing.PENDING,
            PlayerListing.LIVE,
            PlayerListing.OFFER,
        ],
    )
    if exclude_listing_id:
        listings = listings.exclude(pk=exclude_listing_id)
        swaps = swaps.exclude(pk=exclude_listing_id)
        multi_swaps = multi_swaps.exclude(pk=exclude_listing_id)
    if listings.exists():
        raise ValueError("This player is listed on the transfer market.")
    if swaps.exists() or multi_swaps.exists():
        raise ValueError("This player is already part of another transfer offer.")


def _assert_no_live_auction(player):
    _assert_player_unlocked(player)


def locked_squad_player_ids(team):
    if team is None:
        return set()
    listed = PlayerListing.objects.filter(
        status__in=[PlayerListing.PENDING, PlayerListing.LIVE, PlayerListing.OFFER],
        player__mgl_team=team,
    ).values_list("player_id", flat=True)
    offered = PlayerListing.objects.filter(
        status__in=[PlayerListing.PENDING, PlayerListing.LIVE, PlayerListing.OFFER],
        offered_player__mgl_team=team,
    ).values_list("offered_player_id", flat=True)
    offered_many = PlayerListing.objects.filter(
        status__in=[PlayerListing.PENDING, PlayerListing.LIVE, PlayerListing.OFFER],
        offered_players__mgl_team=team,
    ).values_list("offered_players", flat=True)
    auctions = PlayerAuction.objects.filter(
        player__mgl_team=team,
        status__in=[PlayerAuction.PENDING, PlayerAuction.LIVE],
    ).values_list("player_id", flat=True)
    return {player_id for player_id in (*listed, *offered, *offered_many, *auctions) if player_id}


def parse_offer_amount(value, *, allow_zero=False):
    if value is None or str(value).strip() == "":
        if allow_zero:
            return Decimal("0.00")
        raise ValueError("Enter a token offer.")
    try:
        price = Decimal(str(value).strip())
    except Exception as exc:
        raise ValueError("Enter a valid token amount.") from exc
    if price < 0:
        raise ValueError("Token offer cannot be negative.")
    if price == 0 and not allow_zero:
        raise ValueError("Token offer must be greater than zero.")
    return price


def _player_deal_line(player):
    if player is None:
        return ""
    return f"{player.name} — {player.position} — {player.overall} OVR"


def listing_swap_players(listing):
    if listing is None:
        return []
    players = list(listing.offered_players.all().order_by("name", "id"))
    if players:
        return players
    if listing.offered_player_id:
        return [listing.offered_player]
    return []


def transfer_offer_details(listing, buyer_club=None, extra=None):
    buyer = listing.reserved_buyer
    if buyer_club is None and buyer is not None:
        buyer_club = club_for_user(buyer.user)
    offered = listing_swap_players(listing)
    amount = listing.asking_price
    details = {
        "player": listing.player.name,
        "requesting_club": buyer_club.name if buyer_club else (buyer.display_name if buyer else ""),
        "current_club": listing.team.name,
        "transfer_type": "Player swap" if offered else "Transfer request",
        "amount": str(amount),
        "buyer_receives": _player_deal_line(listing.player),
        "buyer_manager": buyer.display_name if buyer else "",
    }
    if offered:
        seller_bits = [_player_deal_line(player) for player in offered]
        if amount and amount > 0:
            seller_bits.append(f"{amount} TKN")
        details["offered_player"] = ", ".join(_player_deal_line(player) for player in offered)
        details["seller_receives"] = " + ".join(seller_bits)
    elif amount is not None:
        details["seller_receives"] = f"{amount} TKN"
    if extra:
        details.update(extra)
    return details


def assert_swap_player_for_buyer(offered_player, buyer_club, *, exclude_listing_id=None):
    if offered_player is None:
        return None
    player = _lock_player(offered_player)
    if player.mgl_team_id != buyer_club.id:
        raise ValueError("You can only offer a player from your own squad.")
    if player.is_free_agent:
        raise ValueError("You cannot offer a free agent as a swap player.")
    _assert_player_unlocked(player, exclude_listing_id=exclude_listing_id)
    return player


def assert_swap_players_for_buyer(offered_players, buyer_club, *, target_id=None, exclude_listing_id=None):
    validated = []
    seen = set()
    for raw in offered_players or []:
        if raw is None:
            continue
        player = assert_swap_player_for_buyer(
            raw,
            buyer_club,
            exclude_listing_id=exclude_listing_id,
        )
        if player.id in seen:
            continue
        if target_id and player.id == target_id:
            raise ValueError("The swap player must be different from the player being bought.")
        seen.add(player.id)
        validated.append(player)
    return validated


def assert_swap_roster_space(buyer_club, selling_team, swap_count):
    buyer_extra = 1 - swap_count
    seller_extra = swap_count - 1
    if buyer_extra > 0:
        assert_roster_space(buyer_club, extra=buyer_extra)
    if seller_extra > 0:
        assert_roster_space(selling_team, extra=seller_extra)


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
    assert_auction_listing_frequency(manager)
    bid = parse_auction_starting_bid(starting_bid)
    now = timezone.now()
    auction = PlayerAuction.objects.create(
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
    _detach_player_for_club_auction(player)
    create_news(
        NewsPost.AUCTION,
        f"{player.name} is live at auction",
        f"{team.name} listed {player.name} ({player.position}, {player.overall} OVR) for auction.",
        team=team,
    )
    return auction


def _detach_player_for_club_auction(player):
    player.mgl_team = None
    player.is_free_agent = False
    player.save(update_fields=["mgl_team", "is_free_agent"])
    return player


def detach_live_club_auction_players():
    """Detach any club-auction player still sitting on a squad."""
    player_ids = list(
        PlayerAuction.objects.filter(
            listing_kind=PlayerAuction.CLUB,
            status__in=[PlayerAuction.PENDING, PlayerAuction.LIVE],
        ).values_list("player_id", flat=True)
    )
    if not player_ids:
        return 0
    return Player.objects.filter(pk__in=player_ids, mgl_team__isnull=False).update(
        mgl_team=None,
        is_free_agent=False,
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
def transfer_player(player, from_team, to_team, source="TRANSFER", reference="", enforce_roster_limit=True):
    player = Player.objects.select_for_update().get(pk=player.pk)
    to_team = Team.objects.select_for_update().get(pk=to_team.pk)

    if from_team and player.mgl_team_id != from_team.id:
        raise ValueError("This player does not belong to the selling club.")

    from mgl.player_state import roster_occupancy

    if enforce_roster_limit:
        from mgl.ufl_settings import effective_roster_limit

        roster_limit = effective_roster_limit(to_team)
        current_size = roster_occupancy(to_team)
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


def _backfill_ended_auction_transfer(auction, reviewer=None):
    """If an ended auction has a winner but no history row, write that row once."""
    if auction.status != PlayerAuction.ENDED:
        return None
    if not auction.winning_manager_id or not auction.winning_bid:
        return None
    winner = auction.winning_manager
    club = club_for_user(winner.user) if winner else None
    if club is None:
        highest = (
            auction.bids.select_related("team")
            .order_by("-amount", "-created_at")
            .first()
        )
        club = highest.team if highest else None
    return record_completed_auction_transfer(
        auction=auction,
        player=auction.player,
        seller=auction.listed_by_manager,
        buyer=winner,
        from_team=auction.origin_team,
        to_team=club,
        amount=auction.winning_bid,
        approved_by=reviewer,
    )


@transaction.atomic
def settle_auction(auction, reviewer=None):
    auction = PlayerAuction.objects.select_for_update().get(pk=auction.pk)

    if auction.status != PlayerAuction.LIVE:
        if auction.status == PlayerAuction.ENDED:
            _backfill_ended_auction_transfer(auction, reviewer=reviewer)
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

    record_completed_auction_transfer(
        auction=auction,
        player=player,
        seller=auction.listed_by_manager,
        buyer=winner,
        from_team=origin,
        to_team=club,
        amount=highest.amount,
        approved_by=reviewer,
    )
    from mgl.notifications import notify_user

    notify_user(
        winner.user,
        source_key=f"auction-won-{auction.pk}",
        notification_type="TRANSFER",
        title="AUCTION WON",
        message=f"{player.name} has joined {club.name} after your winning bid of {highest.amount} TKN.",
        actor="UFL Auctions",
        team=club,
        player=player,
    )
    if auction.listed_by_manager_id and auction.listed_by_manager_id != winner.id:
        notify_user(
            auction.listed_by_manager.user,
            source_key=f"auction-sold-{auction.pk}",
            notification_type="TRANSFER",
            title="PLAYER SOLD AT AUCTION",
            message=f"{player.name} was sold to {club.name} for {highest.amount} TKN.",
            actor="UFL Auctions",
            team=origin,
            player=player,
        )
    create_news(
        NewsPost.AUCTION,
        f"{player.name} sold at auction",
        f"{player.name} has joined {club.name} after a winning auction bid.",
        team=club,
        secondary_team=origin,
    )
    return auction, f"{player.name} transferred to {club.name}."


@transaction.atomic
def cancel_live_auction(auction, reviewer=None):
    auction = PlayerAuction.objects.select_for_update().get(pk=auction.pk)
    if auction.status != PlayerAuction.LIVE:
        raise ValueError("This auction is not live.")
    highest = auction.bids.order_by("-amount", "-created_at").first()
    if highest:
        credit_manager_tokens(
            highest.manager,
            highest.amount,
            f"Auction cancelled refund on {auction.player.name}",
            auction=auction,
        )
        record_market_transaction(
            player=auction.player,
            seller=None,
            buyer=highest.manager,
            from_team=None,
            to_team=None,
            amount=highest.amount,
            transaction_type=MarketTransaction.BID_REFUND,
            status=MarketTransaction.COMPLETED,
            auction=auction,
            approved_by=reviewer,
            notes="Refunded after auction cancellation",
        )
    player = _restore_unsold_player(auction)
    auction.status = PlayerAuction.CANCELLED
    auction.save(update_fields=["status"])
    club_name = auction.origin_team.name if auction.origin_team_id else "the original club"
    return auction, f"{player.name} returned to {club_name}."


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
    assert_transfer_window()
    _assert_no_live_auction(player)
    assert_listing_frequency(manager)
    assert_club_listing_capacity(team)

    listing = PlayerListing.objects.create(
        player=player,
        team=team,
        seller=manager,
        asking_price=price,
        status=PlayerListing.LIVE,
    )
    create_news(
        NewsPost.TRANSFER,
        f"{player.name} listed for sale",
        f"{team.name} listed {player.name} for {price} tokens.",
        team=team,
    )
    return listing


def _notify_control_of_sale_listing(listing):
    from django.urls import reverse

    from accounts.models import User
    from mgl.models import ManagerNotification
    from mgl.notifications import notify_user

    buyer = listing.reserved_buyer
    details = transfer_offer_details(listing)
    for user in User.objects.filter(
        role__in=[User.OWNER, User.ADMIN],
        is_active=True,
    ):
        notify_user(
            user,
            source_key=f"admin-listing-{listing.pk}",
            notification_type="TRANSFER",
            title="TRANSFER REQUEST",
            message=(
                f"{listing.team.name} accepted a transfer request for "
                f"{listing.player.name} at {listing.asking_price} TKN."
            ),
            actor=listing.seller.display_name,
            action_url=reverse("control_transfers"),
            action_label="REVIEW",
            team=listing.team,
            player=listing.player,
            listing=listing,
            is_action=True,
            response_status=ManagerNotification.PENDING,
            details=details,
        )


def _close_admin_listing_notices(listing, status):
    from mgl.models import ManagerNotification

    now = timezone.now()
    ManagerNotification.objects.filter(
        source_key=f"admin-listing-{listing.pk}",
        response_status=ManagerNotification.PENDING,
    ).update(
        response_status=status,
        actioned_at=now,
        read_at=now,
    )


def _notify_listing_outcome(listing, *, buyer=None, rejected=False):
    from django.urls import reverse
    from mgl.notifications import notify_user

    if rejected:
        notify_user(
            listing.seller.user,
            source_key=f"listing-rejected-{listing.pk}",
            notification_type="TRANSFER",
            title="LISTING REJECTED",
            message=f"Your listing for {listing.player.name} was rejected.",
            actor="UFL Admin",
            action_url=reverse("team_management"),
            action_label="VIEW SQUAD",
            team=listing.team,
            player=listing.player,
        )
        if listing.reserved_buyer_id and listing.reserved_buyer.user_id:
            notify_user(
                listing.reserved_buyer.user,
                source_key=f"transfer-offer-admin-rejected-{listing.pk}",
                notification_type="TRANSFER",
                title="TRANSFER REJECTED",
                message=(
                    f"Your transfer request for {listing.player.name} "
                    "was rejected by the league office."
                ),
                actor="UFL Admin",
                action_url=reverse("transfer_market"),
                action_label="VIEW MARKET",
                team=listing.team,
                player=listing.player,
            )
        return

    notify_user(
        listing.seller.user,
        source_key=f"listing-approved-{listing.pk}",
        notification_type="TRANSFER",
        title="LISTING APPROVED",
        message=(
            f"{listing.player.name} is now live on the transfer market "
            f"for {listing.asking_price} TKN."
        ),
        actor="UFL Admin",
        action_url=reverse("transfer_market"),
        action_label="VIEW MARKET",
        team=listing.team,
        player=listing.player,
    )


def _player_deal_snapshot(player):
    return {
        "id": player.id,
        "name": player.name,
        "overall": int(player.overall or 0),
        "position": player.position or "",
    }


def completed_listing_deal_details(listing, selling_team, buyer_club, offered, price):
    """Snapshot of the completed deal at approval time.

    Stored on the activity/news record so later squad moves do not
    rewrite what users see in history.
    """
    return {
        "deal": True,
        "listing_id": listing.id,
        "amount": str(Decimal(price)),
        "selling_club": selling_team.name,
        "buying_club": buyer_club.name,
        "target": _player_deal_snapshot(listing.player),
        "swaps": [_player_deal_snapshot(player) for player in offered],
    }


def _complete_listing_sale(listing, buyer):
    buyer_club = club_for_user(buyer.user)
    if not buyer_club:
        raise ValueError("You must manage a club to buy a player.")
    if buyer_club.id == listing.team_id:
        raise ValueError("You already own this player.")
    if listing.seller_id == buyer.id:
        raise ValueError("You cannot buy your own listing.")
    assert_transfer_window()
    selling_team = listing.team
    offered = assert_swap_players_for_buyer(
        listing_swap_players(listing),
        buyer_club,
        target_id=listing.player_id,
        exclude_listing_id=listing.pk,
    )
    assert_swap_roster_space(buyer_club, selling_team, len(offered))

    price = Decimal(listing.asking_price)
    deal_details = completed_listing_deal_details(
        listing,
        selling_team,
        buyer_club,
        offered,
        price,
    )
    if price > 0:
        debit_manager_tokens(
            buyer,
            price,
            f"Bought {listing.player.name} from {selling_team.name}",
        )
        credit_manager_tokens(
            listing.seller,
            price,
            f"Sold {listing.player.name} to {buyer_club.name}",
        )

    transfer_player(
        listing.player,
        selling_team,
        buyer_club,
        source="TRANSFER",
        reference=f"listing:{listing.id}",
        enforce_roster_limit=not offered,
    )
    for index, swap in enumerate(offered):
        transfer_player(
            swap,
            buyer_club,
            selling_team,
            source="TRANSFER",
            reference=f"listing:{listing.id}:swap:{index}",
            enforce_roster_limit=False,
        )

    listing.status = PlayerListing.SOLD
    listing.sold_to = buyer
    listing.sold_at = timezone.now()
    listing.save(update_fields=["status", "sold_to", "sold_at"])

    record_market_transaction(
        player=listing.player,
        seller=listing.seller,
        buyer=buyer,
        from_team=selling_team,
        to_team=buyer_club,
        amount=price,
        transaction_type=MarketTransaction.SALE,
        status=MarketTransaction.COMPLETED,
        approved_by=listing.reviewed_by,
        listing=listing,
    )
    for swap in offered:
        record_market_transaction(
            player=swap,
            seller=buyer,
            buyer=listing.seller,
            from_team=buyer_club,
            to_team=selling_team,
            amount=Decimal("0.00"),
            transaction_type=MarketTransaction.SALE,
            status=MarketTransaction.COMPLETED,
            approved_by=listing.reviewed_by,
            listing=listing,
            notes="Player swap",
        )
    news_body = (
        f"{listing.player.name} has joined {buyer_club.name} from {selling_team.name}."
    )
    if offered:
        swap_names = ", ".join(player.name for player in offered)
        news_body = (
            f"{listing.player.name} has joined {buyer_club.name} from {selling_team.name} "
            f"in exchange for {swap_names}"
            f"{f' and {price} TKN' if price > 0 else ''}."
        )
    create_news(
        NewsPost.TRANSFER,
        f"{listing.player.name} transferred",
        news_body,
        team=buyer_club,
        secondary_team=selling_team,
        details=deal_details,
    )
    from mgl.press import maybe_create_signing_press

    maybe_create_signing_press(buyer.user, buyer_club)
    from django.urls import reverse
    from mgl.notifications import notify_user

    notify_user(
        listing.seller.user,
        source_key=f"transfer-sold-{listing.pk}",
        notification_type="TRANSFER",
        title="PLAYER SOLD",
        message=(
            f"{listing.player.name} has joined {buyer_club.name} "
            f"from {listing.team.name}."
        ),
        actor=buyer.display_name,
        action_url=reverse("transfer_market"),
        action_label="VIEW MARKET",
        team=listing.team,
        player=listing.player,
    )
    notify_user(
        buyer.user,
        source_key=f"transfer-bought-{listing.pk}",
        notification_type="TRANSFER",
        title="PLAYER SIGNED",
        message=(
            f"{listing.player.name} has joined {buyer_club.name} "
            f"from {listing.team.name}."
        ),
        actor="Transfer Market",
        action_url=reverse("team_management"),
        action_label="VIEW SQUAD",
        team=buyer_club,
        player=listing.player,
    )
    return listing


def _lock_listing(listing):
    """Lock the listing row only.

    PostgreSQL rejects SELECT FOR UPDATE when select_related() joins a
    nullable FK (reserved_buyer, sold_to, reviewed_by). Load those after
    the lock, the same way auction bids are locked.
    """
    return PlayerListing.objects.select_for_update().get(pk=listing.pk)


def _lock_player(player):
    """Lock only the player row.

    PostgreSQL rejects SELECT FOR UPDATE when select_related() joins the
    nullable mgl_team FK. Fetch related rows after the lock.
    """
    return Player.objects.select_for_update().get(pk=getattr(player, "pk", player))


@transaction.atomic
def approve_listing(listing, reviewer):
    listing = _lock_listing(listing)
    if listing.status != PlayerListing.PENDING:
        raise ValueError("This listing is not waiting for approval.")
    listing.reviewed_at = timezone.now()
    listing.reviewed_by = reviewer
    if listing.reserved_buyer_id:
        listing.save(update_fields=["reviewed_at", "reviewed_by"])
        result = _complete_listing_sale(listing, listing.reserved_buyer)
        from mgl.models import ManagerNotification

        _close_admin_listing_notices(listing, ManagerNotification.ACCEPTED)
        return result
    listing.status = PlayerListing.LIVE
    listing.save(update_fields=["status", "reviewed_at", "reviewed_by"])
    create_news(
        NewsPost.TRANSFER,
        f"{listing.player.name} listed for sale",
        f"{listing.team.name} listed {listing.player.name} for {listing.asking_price} tokens.",
        team=listing.team,
    )
    _notify_listing_outcome(listing)
    from mgl.models import ManagerNotification

    _close_admin_listing_notices(listing, ManagerNotification.ACCEPTED)
    return listing


@transaction.atomic
def reject_listing(listing, reviewer):
    listing = _lock_listing(listing)
    if listing.status != PlayerListing.PENDING:
        raise ValueError("This listing is not waiting for approval.")
    listing.status = PlayerListing.REJECTED
    listing.reviewed_at = timezone.now()
    listing.reviewed_by = reviewer
    listing.save(update_fields=["status", "reviewed_at", "reviewed_by"])
    _notify_listing_outcome(listing, rejected=True)
    from mgl.models import ManagerNotification

    _close_admin_listing_notices(listing, ManagerNotification.REJECTED)
    return listing


@transaction.atomic
def buy_listed_player(listing, buyer):
    listing = PlayerListing.objects.select_for_update().select_related(
        "player",
        "team",
        "seller",
    ).get(pk=listing.pk)

    raise ValueError(
        "Listed players must be bought through a transfer request. "
        "The selling manager and Owner/Admin must approve the deal."
    )


def seller_application_for_team(team):
    if team is None or not team.manager_id:
        return None
    return manager_for_user(team.manager)


def assert_can_create_transfer_offer(
    player,
    buyer,
    *,
    exclude_listing_id=None,
    require_tokens=True,
    check_roster=True,
):
    assert_transfer_window()
    buyer_club = club_for_user(buyer.user)
    if not buyer_club:
        raise ValueError("You must manage a club to buy a player.")
    selling_team = player.mgl_team
    if selling_team is None:
        raise ValueError("This player is not at a club.")
    if selling_team.id == buyer_club.id:
        raise ValueError("You cannot buy your own player.")
    if not selling_team.manager_id:
        raise ValueError("This club has no manager to receive a transfer request.")
    seller = seller_application_for_team(selling_team)
    if seller is None:
        raise ValueError("This club has no manager to receive a transfer request.")
    if seller.id == buyer.id:
        raise ValueError("You cannot buy your own player.")
    if require_tokens and buyer.tokens < Decimal("0.01"):
        raise ValueError("You do not have enough tokens.")
    if check_roster:
        assert_roster_space(buyer_club)
    _assert_player_unlocked(player, exclude_listing_id=exclude_listing_id)
    return buyer_club, selling_team, seller


@transaction.atomic
def create_transfer_offer(player, buyer, asking_price):
    player = _lock_player(player)
    buyer_club, selling_team, seller = assert_can_create_transfer_offer(player, buyer)
    price = parse_asking_price(asking_price)
    if buyer.tokens < price:
        raise ValueError("You do not have enough tokens.")
    listing = PlayerListing.objects.create(
        player=player,
        team=selling_team,
        seller=seller,
        asking_price=price,
        status=PlayerListing.OFFER,
        reserved_buyer=buyer,
    )
    _notify_seller_of_transfer_offer(listing, buyer_club)
    return listing


def _notify_seller_of_transfer_offer(listing, buyer_club):
    from django.urls import reverse
    from mgl.notifications import notify_user

    player = listing.player
    selling_team = listing.team
    offered = listing_swap_players(listing)
    if offered:
        swap_names = ", ".join(item.name for item in offered)
        message = (
            f"{buyer_club.name} has submitted a transfer request for {player.name}, "
            f"offering {swap_names}"
            f"{f' and {listing.asking_price} TKN' if listing.asking_price > 0 else ''}."
        )
    else:
        message = (
            f"{buyer_club.name} has submitted a transfer request for {player.name}."
        )
    notify_user(
        selling_team.manager,
        source_key=f"transfer-offer-{listing.pk}",
        notification_type="TRANSFER",
        title="Transfer Request",
        message=message,
        actor=buyer_club.name,
        action_url=reverse("transfer_requests"),
        action_label="REVIEW REQUEST",
        team=selling_team,
        player=player,
        listing=listing,
        is_action=True,
        response_status="PENDING",
        details=transfer_offer_details(listing, buyer_club),
    )
    return listing


@transaction.atomic
def create_listed_purchase_offer(
    listing,
    buyer,
    asking_price,
    offered_player=None,
    offered_players=None,
):
    listing = _lock_listing(listing)
    if listing.status != PlayerListing.LIVE:
        raise ValueError("This player is not available for purchase.")
    player = _lock_player(listing.player_id)
    buyer_club, selling_team, seller = assert_can_create_transfer_offer(
        player,
        buyer,
        exclude_listing_id=listing.pk,
        require_tokens=False,
        check_roster=False,
    )
    if listing.team_id != selling_team.id or listing.seller_id != seller.id:
        raise ValueError("This listing no longer matches the selling club.")
    raw_swaps = list(offered_players or [])
    if not raw_swaps and offered_player is not None:
        raw_swaps = [offered_player]
    offered = assert_swap_players_for_buyer(
        raw_swaps,
        buyer_club,
        target_id=player.id,
        exclude_listing_id=listing.pk,
    )
    price = parse_offer_amount(asking_price, allow_zero=bool(offered))
    if not offered and price <= 0:
        raise ValueError("Offer tokens or include a player from your squad.")
    if buyer.tokens < price:
        raise ValueError("You do not have enough tokens.")
    assert_swap_roster_space(buyer_club, selling_team, len(offered))
    listing.reserved_buyer = buyer
    listing.asking_price = price
    listing.offered_player = offered[0] if offered else None
    listing.status = PlayerListing.OFFER
    listing.save(
        update_fields=["reserved_buyer", "asking_price", "offered_player", "status"]
    )
    listing.offered_players.set(offered)
    _record_negotiation_event(
        listing,
        getattr(buyer, "user", None),
        "OFFER",
        listing.asking_price,
        getattr(listing, "message", ""),
        offered,
    )
    listing = PlayerListing.objects.select_related(
        "player",
        "team",
        "seller",
        "reserved_buyer",
        "offered_player",
    ).prefetch_related("offered_players").get(pk=listing.pk)
    _notify_seller_of_transfer_offer(listing, buyer_club)
    return listing


@transaction.atomic
def respond_to_transfer_offer(listing, seller_user, accept):
    listing = _lock_listing(listing)
    if listing.status != PlayerListing.OFFER:
        raise ValueError("This transfer request has already been handled.")
    if listing.team.manager_id != seller_user.id:
        raise ValueError("You can only respond to transfer requests for your own players.")
    player = listing.player
    if player.mgl_team_id != listing.team_id:
        raise ValueError("This player is no longer at your club.")
    from django.urls import reverse
    from mgl.notifications import mark_notification_response, notify_user

    now = timezone.now()
    if accept:
        swaps = listing_swap_players(listing)
        if swaps:
            if not listing.reserved_buyer_id:
                raise ValueError("This transfer request is missing a buying club.")
            buyer_club = club_for_user(listing.reserved_buyer.user)
            if not buyer_club:
                raise ValueError("The buying club is no longer valid.")
            assert_swap_players_for_buyer(
                swaps,
                buyer_club,
                target_id=player.id,
                exclude_listing_id=listing.pk,
            )
            assert_swap_roster_space(buyer_club, listing.team, len(swaps))
        assert_club_listing_capacity(listing.team)
        listing.status = PlayerListing.PENDING
        listing.save(update_fields=["status"])
        mark_notification_response(
            listing.team.manager,
            f"transfer-offer-{listing.pk}",
            "ACCEPTED",
        )
        if listing.reserved_buyer_id:
            notify_user(
                listing.reserved_buyer.user,
                source_key=f"transfer-offer-accepted-{listing.pk}",
                notification_type="TRANSFER",
                title="TRANSFER ACCEPTED",
                message=(
                    f"{listing.team.name} accepted your request for {player.name}. "
                    "The league office still has to approve the transfer."
                ),
                actor=listing.team.name,
                action_url=reverse("transfer_market"),
                action_label="VIEW MARKET",
                team=listing.team,
                player=player,
                listing=listing,
                details=transfer_offer_details(
                    listing,
                    extra={"status": "PENDING ADMIN"},
                ),
            )
        _notify_control_of_sale_listing(listing)
        _record_negotiation_event(
            listing,
            seller_user,
            "ACCEPT",
            listing.asking_price,
            "",
            listing_swap_players(listing),
        )
        return listing

    listing.status = PlayerListing.REJECTED
    listing.save(update_fields=["status"])
    mark_notification_response(
        listing.team.manager,
        f"transfer-offer-{listing.pk}",
        "REJECTED",
    )
    if listing.reserved_buyer_id:
        notify_user(
            listing.reserved_buyer.user,
            source_key=f"transfer-offer-rejected-{listing.pk}",
            notification_type="TRANSFER",
            title="TRANSFER REJECTED",
            message=(
                f"{listing.team.name} rejected the transfer request for {player.name}."
            ),
            actor=listing.team.name,
            action_url=reverse("transfer_market"),
            action_label="VIEW MARKET",
            team=listing.team,
            player=player,
            listing=listing,
        )
    _record_negotiation_event(
        listing,
        seller_user,
        "REJECT",
        listing.asking_price,
        "",
        listing_swap_players(listing),
    )
    return listing


def _swap_summary(players):
    names = [getattr(player, "name", "") for player in players if player]
    return ", ".join(name for name in names if name)


def _record_negotiation_event(listing, actor, action, amount=None, message="", swaps=None):
    from mgl.models import TransferNegotiationEvent

    TransferNegotiationEvent.objects.create(
        listing=listing,
        actor=actor,
        action=action,
        token_amount=amount if amount is not None else listing.asking_price,
        message=message or "",
        swap_summary=_swap_summary(swaps if swaps is not None else listing_swap_players(listing)),
    )


@transaction.atomic
def counter_transfer_offer(listing, actor_user, asking_price, offered_players=None, message=""):
    listing = _lock_listing(listing)
    if listing.status != PlayerListing.OFFER:
        raise ValueError("Only an open offer can be countered.")
    seller_id = listing.team.manager_id
    buyer_user = getattr(listing.reserved_buyer, "user", None)
    buyer_id = getattr(buyer_user, "id", None)
    if actor_user.id not in {seller_id, buyer_id}:
        raise ValueError("You can only counter a negotiation you are part of.")
    buyer_club = club_for_user(listing.reserved_buyer.user) if listing.reserved_buyer_id else None
    if buyer_club is None:
        raise ValueError("The buying club is no longer valid.")
    raw_swaps = list(offered_players or [])
    offered = assert_swap_players_for_buyer(
        raw_swaps,
        buyer_club,
        target_id=listing.player_id,
        exclude_listing_id=listing.pk,
    )
    price = parse_offer_amount(asking_price, allow_zero=bool(offered))
    if not offered and price <= 0:
        raise ValueError("Counter with tokens or include a player from the buying squad.")
    listing.asking_price = price
    listing.offered_player = offered[0] if offered else None
    listing.message = (message or "").strip()
    listing.status = PlayerListing.OFFER
    listing.save(update_fields=["asking_price", "offered_player", "message", "status"])
    listing.offered_players.set(offered)
    _record_negotiation_event(listing, actor_user, "COUNTER", price, listing.message, offered)
    from django.urls import reverse
    from mgl.notifications import notify_user

    counterpart = listing.reserved_buyer.user if actor_user.id == seller_id else listing.team.manager
    notify_user(
        counterpart,
        source_key=f"transfer-counter-{listing.pk}-{timezone.now().timestamp()}",
        notification_type="TRANSFER",
        title="TRANSFER COUNTER",
        message=f"A counter-offer is waiting on {listing.player.name}.",
        actor=getattr(actor_user, "username", ""),
        action_url=reverse("transfer_requests"),
        action_label="OPEN NEGOTIATION",
        team=listing.team,
        player=listing.player,
        listing=listing,
    )
    return listing


@transaction.atomic
def withdraw_transfer_offer(listing, buyer):
    listing = _lock_listing(listing)
    if listing.reserved_buyer_id != buyer.id:
        raise ValueError("You can only withdraw your own offer.")
    if listing.status != PlayerListing.OFFER:
        raise ValueError("Only an open offer can be withdrawn.")
    listing.status = PlayerListing.CANCELLED
    listing.save(update_fields=["status"])
    _record_negotiation_event(listing, getattr(buyer, "user", None), "WITHDRAW", listing.asking_price)
    return listing


@transaction.atomic
def request_listing_changes(listing, reviewer, note=""):
    listing = _lock_listing(listing)
    if listing.status != PlayerListing.PENDING:
        raise ValueError("Only an accepted deal can be sent back for changes.")
    listing.status = PlayerListing.OFFER
    listing.request_changes_note = (note or "").strip()
    listing.save(update_fields=["status", "request_changes_note"])
    _record_negotiation_event(
        listing,
        reviewer,
        "CHANGES",
        listing.asking_price,
        listing.request_changes_note,
    )
    from mgl.audit import log_ocm_action

    log_ocm_action(
        reviewer,
        action="transfer.request_changes",
        object_type="PlayerListing",
        object_id=listing.pk,
        object_label=listing.player.name,
        summary=f"League office requested changes on {listing.player.name}.",
    )
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


def transfer_offer_context_for(user, player):
    from mgl.permissions import approved_manager

    manager = approved_manager(user) if getattr(user, "is_authenticated", False) else None
    club = club_for_user(user) if manager else None
    can_request = False
    block_reason = ""
    open_offer = None
    if manager and club:
        open_offer = (
            PlayerListing.objects.filter(
                player=player,
                reserved_buyer=manager,
                status__in=[PlayerListing.OFFER, PlayerListing.PENDING],
            )
            .order_by("-id")
            .first()
        )
        try:
            assert_can_create_transfer_offer(player, manager)
            can_request = True
        except ValueError as exc:
            block_reason = str(exc)
    own_player = bool(club and player.mgl_team_id == club.id)
    return {
        "can_request_transfer": can_request and open_offer is None,
        "transfer_block_reason": "" if own_player else block_reason,
        "open_transfer_offer": open_offer,
        "viewer_manager": manager,
        "viewer_club": club,
        "is_own_player": own_player,
    }
