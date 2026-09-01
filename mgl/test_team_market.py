from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from auctions.models import PlayerAuction
from leagues.models import League
from managers.models import ManagerApplication
from mgl.market import (
    AUCTION_DURATIONS_MINUTES,
    MARKET_SLOT_MESSAGE,
    MAX_ACTIVE_CLUB_LISTINGS,
    _lock_listing,
    cancel_live_auction,
    close_expired_auctions,
    create_free_agent_auction,
    create_manager_auction,
    detach_live_club_auction_players,
    list_player_for_sale,
    parse_auction_starting_bid,
    place_auction_bid,
    settle_auction,
)
from mgl.player_state import AUCTION, is_unassigned, market_status, roster_occupancy
from mgl.models import ManagerNotification, PlayerListing
from mgl.services import release_player
from players.models import Player
from teams.models import Team


def _user(username, role=User.MANAGER):
    return User.objects.create_user(username=username, password="test-pass-123", role=role)


def _manager(user, tokens="40.00"):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=ManagerApplication.APPROVED,
        tokens=Decimal(tokens),
    )


class TeamMarketListingTests(TestCase):
    def setUp(self):
        self.league = League.objects.create(name="Market League", short_name="MKT", season="1")
        self.user_a = _user("seller")
        self.user_b = _user("buyer")
        self.mgr_a = _manager(self.user_a)
        self.mgr_b = _manager(self.user_b)
        self.team_a = Team.objects.create(name="Alpha", short_name="ALP", league=self.league, manager=self.user_a)
        self.team_b = Team.objects.create(name="Beta", short_name="BET", league=self.league, manager=self.user_b)
        self.owned = Player.objects.create(name="Club Striker", position="ST", overall=74, mgl_team=self.team_a, is_free_agent=False)
        self.other = Player.objects.create(name="Rival Mid", position="CM", overall=71, mgl_team=self.team_b, is_free_agent=False)
        self.client = Client(HTTP_HOST="127.0.0.1")
        from mgl.models import LeagueSettings
        LeagueSettings.objects.update(allow_manager_auctions=True)

    def test_team_management_uses_cards_not_old_list(self):
        self.client.login(username="seller", password="test-pass-123")
        page = self.client.get(reverse("team_management"))
        self.assertContains(page, "CLUB STRIKER")
        self.assertContains(page, "mgl-team.css")
        self.assertContains(page, ">TRANSFER<")
        self.assertContains(page, ">RELEASE<")
        self.assertContains(page, ">AUCTION<")
        self.assertContains(page, "mgl-squad-table")
        self.assertNotContains(page, "TRANSFER LIST")
        self.assertNotContains(page, "mgl-squad-check-link")
        html = page.content.decode()
        transfer_at = html.find(">TRANSFER<")
        release_at = html.find(">RELEASE<")
        auction_at = html.find(">AUCTION<")
        self.assertTrue(0 < transfer_at < release_at < auction_at)
        self.assertNotContains(page, "mgl-pitch-chip")
        self.assertNotContains(page, "aria-label=\"Squad pitch\"")
        self.assertNotContains(page, "SELL A PLAYER")
        self.assertNotContains(page, "LIST FOR SALE")
        self.assertNotContains(page, "TOKEN ASKING PRICE")
        self.assertNotContains(page, "class=\"table-row\"")
        self.assertNotContains(page, "core/img/mgl-starting-xi.png")
        self.assertContains(page, 'class="mgl-squad-pos"')
        self.assertContains(page, 'class="mgl-squad-age"')
        theme = Path(__file__).resolve().parents[1].joinpath("core/static/core/css/mgl-theme.css").read_text(encoding="utf-8")
        team_css = Path(__file__).resolve().parents[1].joinpath("core/static/core/css/mgl-team.css").read_text(encoding="utf-8")
        self.assertIn("display: table-row", team_css)
        self.assertIn("table-layout: fixed", team_css)
        self.assertNotRegex(theme, r"(?m)^\.mgl-squad-row \{")
        self.assertNotRegex(theme, r"(?m)^\.mgl-squad-table-head,")

    def test_manager_can_list_own_player_and_not_another_club(self):
        listing = list_player_for_sale(self.owned, self.mgr_a, "5.00")
        self.assertEqual(listing.asking_price, Decimal("5.00"))
        self.assertEqual(listing.player_id, self.owned.id)
        self.assertEqual(Player.objects.filter(pk=self.owned.id).count(), 1)
        with self.assertRaises(ValueError):
            list_player_for_sale(self.other, self.mgr_a, "5.00")
        with self.assertRaises(ValueError):
            list_player_for_sale(self.owned, self.mgr_a, "6.00")

    def test_invalid_price_rejected(self):
        with self.assertRaises(ValueError):
            list_player_for_sale(self.owned, self.mgr_a, "0")
        with self.assertRaises(ValueError):
            list_player_for_sale(self.owned, self.mgr_a, "-2")
        with self.assertRaises(ValueError):
            list_player_for_sale(self.owned, self.mgr_a, "")
        self.assertEqual(PlayerListing.objects.count(), 0)

    def test_combined_five_listing_cap_covers_transfers_and_auctions(self):
        extras = [
            Player.objects.create(
                name=f"Slot {i}",
                position="CB",
                overall=65,
                mgl_team=self.team_a,
                is_free_agent=False,
            )
            for i in range(4)
        ]
        for extra in extras[:2]:
            list_player_for_sale(extra, self.mgr_a, "3")
        PlayerListing.objects.filter(seller=self.mgr_a).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        list_player_for_sale(extras[2], self.mgr_a, "3")
        create_manager_auction(extras[3], self.mgr_a, 30, starting_bid=0)
        create_manager_auction(self.owned, self.mgr_a, 60, starting_bid=2)
        seventh = Player.objects.create(name="Seventh", position="ST", overall=66, mgl_team=self.team_a, is_free_agent=False)
        with self.assertRaises(ValueError):
            list_player_for_sale(seventh, self.mgr_a, "4")
        with self.assertRaises(ValueError):
            create_manager_auction(seventh, self.mgr_a, 30, starting_bid=1)
        self.assertEqual(MAX_ACTIVE_CLUB_LISTINGS, 5)

    def test_cannot_list_transfer_and_auction_together(self):
        list_player_for_sale(self.owned, self.mgr_a, "8")
        with self.assertRaises(ValueError):
            create_manager_auction(self.owned, self.mgr_a, 30, starting_bid=1)

    def test_manager_auction_rules(self):
        with self.assertRaises(ValueError):
            create_manager_auction(self.other, self.mgr_a, 30, starting_bid=1)
        self.assertEqual(parse_auction_starting_bid("0"), 0)
        auction = create_manager_auction(self.owned, self.mgr_a, 30, starting_bid=0)
        self.assertEqual(auction.starting_bid, 0)
        self.owned.refresh_from_db()
        self.assertIsNone(self.owned.mgl_team_id)
        self.assertFalse(self.owned.is_free_agent)
        self.assertEqual(auction.origin_team_id, self.team_a.id)
        with self.assertRaises(ValueError):
            parse_auction_starting_bid("11")
        with self.assertRaises(ValueError):
            create_manager_auction(
                Player.objects.create(name="Too High", position="ST", overall=64, mgl_team=self.team_a, is_free_agent=False),
                self.mgr_a,
                30,
                starting_bid=11,
            )
        with self.assertRaises(ValueError):
            create_manager_auction(
                Player.objects.create(name="Bad Timer", position="ST", overall=64, mgl_team=self.team_a, is_free_agent=False),
                self.mgr_a,
                45,
                starting_bid=1,
            )

    def test_all_allowed_auction_timers(self):
        for minutes in AUCTION_DURATIONS_MINUTES:
            player = Player.objects.create(
                name=f"Timer {minutes}",
                position="LW",
                overall=67,
                mgl_team=self.team_a,
                is_free_agent=False,
            )
            auction = create_manager_auction(player, self.mgr_a, minutes, starting_bid=1)
            self.assertEqual(auction.duration_minutes, minutes)
            cancel_live_auction(auction)
            from auctions.models import PlayerAuction
            from datetime import timedelta
            from django.utils import timezone

            PlayerAuction.objects.filter(listed_by_manager=self.mgr_a).update(
                created_at=timezone.now() - timedelta(hours=25)
            )

    def test_release_rules(self):
        release_player(self.owned, self.team_a)
        self.owned.refresh_from_db()
        self.assertTrue(self.owned.is_free_agent)
        self.assertIsNone(self.owned.mgl_team_id)
        with self.assertRaises(ValueError):
            release_player(self.other, self.team_a)
        listed = Player.objects.create(name="Listed Release", position="RB", overall=63, mgl_team=self.team_a, is_free_agent=False)
        list_player_for_sale(listed, self.mgr_a, "4")
        with self.assertRaises(ValueError):
            release_player(listed, self.team_a)
        auctioned = Player.objects.create(name="Auction Release", position="LB", overall=62, mgl_team=self.team_a, is_free_agent=False)
        create_manager_auction(auctioned, self.mgr_a, 30, starting_bid=1)
        with self.assertRaises(ValueError):
            release_player(auctioned, self.team_a)

    def test_transfer_form_and_market_display(self):
        self.client.login(username="seller", password="test-pass-123")
        form = self.client.get(reverse("team_management"), {"list": "transfer", "player": self.owned.id})
        self.assertContains(form, "LIST PLAYER FOR TRANSFER")
        self.assertContains(form, "STARTING PRICE")
        steal = self.client.get(reverse("team_management"), {"list": "transfer", "player": self.other.id})
        self.assertEqual(steal.status_code, 302)
        self.client.post(reverse("sell_player", args=[self.owned.id]), {"asking_price": "5.00"})
        listing = PlayerListing.objects.get(player=self.owned)
        listing.status = PlayerListing.LIVE
        listing.save(update_fields=["status"])
        squad = self.client.get(reverse("team_management"))
        self.assertContains(squad, "TRANSFER LISTED")
        market = self.client.get(reverse("transfer_market"))
        self.assertContains(market, "Club Striker")
        self.assertContains(market, "5.00")
        self.assertContains(market, "VIEW PLAYER")
        self.assertNotContains(market, ">OFFER</button>")
        self.assertContains(market, "Starting price")
        self.assertContains(market, "ASKING PRICE")
        self.assertContains(market, "FILTER:")
        self.assertContains(market, "data-pos-filter")
        self.assertContains(market, "core/css/mgl-market.css")
        self.assertContains(market, "Alpha")
        self.assertContains(market, "MANAGER")
        self.assertContains(market, self.mgr_a.display_name)
        css = (Path(__file__).resolve().parents[1] / "core/static/core/css/mgl-market.css").read_text(encoding="utf-8")
        self.assertIn(".mgl-market-row[hidden]", css)
        self.assertIn("display: none !important", css)

    def test_http_rejects_other_club_listing_and_seventh_slot(self):
        self.client.login(username="seller", password="test-pass-123")
        blocked = self.client.post(reverse("sell_player", args=[self.other.id]), {"asking_price": "4"})
        self.assertEqual(blocked.status_code, 302)
        self.assertEqual(PlayerListing.objects.filter(player=self.other).count(), 0)
        extras = [
            Player.objects.create(name=f"Cap {i}", position="CM", overall=60, mgl_team=self.team_a, is_free_agent=False)
            for i in range(5)
        ]
        for index, extra in enumerate(extras):
            if index and index % 3 == 0:
                PlayerListing.objects.filter(seller=self.mgr_a).update(
                    created_at=timezone.now() - timedelta(hours=25)
                )
            list_player_for_sale(extra, self.mgr_a, "2")
        seventh = self.client.post(reverse("sell_player", args=[self.owned.id]), {"asking_price": "3"})
        self.assertEqual(seventh.status_code, 302)
        self.assertFalse(PlayerListing.objects.filter(player=self.owned).exists())
        auction = self.client.post(
            reverse("list_player_for_auction", args=[self.owned.id]),
            {"duration": "30", "starting_bid": "1"},
        )
        self.assertEqual(auction.status_code, 302)
        self.assertFalse(PlayerAuction.objects.filter(player=self.owned).exists())

    def test_listing_lock_query_does_not_join_nullable_relations(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        listing = list_player_for_sale(self.owned, self.mgr_a, "3.00")
        with CaptureQueriesContext(connection) as captured:
            locked = _lock_listing(listing)
        self.assertEqual(locked.pk, listing.pk)
        sql = " ".join(query["sql"] for query in captured.captured_queries).lower()
        self.assertNotIn(" join ", sql)
        self.assertIn("from \"mgl_playerlisting\"", sql)

    def test_approved_sale_appears_on_market_and_other_channels_stay(self):
        owner = _user("sale-owner", role=User.OWNER)
        fa = Player.objects.create(
            name="Loose Agent",
            position="CM",
            overall=70,
            is_free_agent=True,
        )
        auction_player = Player.objects.create(
            name="Bid Target",
            position="ST",
            overall=72,
            is_free_agent=False,
        )
        auction = PlayerAuction.objects.create(
            player=auction_player,
            starting_bid=1,
            minimum_increment=1,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(hours=1),
            status=PlayerAuction.LIVE,
            listing_kind=PlayerAuction.FREE_AGENT,
        )
        self.client.login(username="seller", password="test-pass-123")
        self.client.post(reverse("sell_player", args=[self.owned.id]), {"asking_price": "6.50"})
        listing = PlayerListing.objects.get(player=self.owned)
        self.assertEqual(listing.status, PlayerListing.LIVE)
        self.assertFalse(
            ManagerNotification.objects.filter(
                recipient=owner,
                source_key=f"admin-listing-{listing.pk}",
            ).exists()
        )
        pending = self.client.get(reverse("transfer_market"))
        self.assertContains(pending, "Club Striker")
        self.assertContains(pending, "6.50")
        self.assertNotContains(pending, "LIVE PLAYER AUCTIONS")
        self.assertNotContains(pending, "Bid Target")
        self.assertNotContains(pending, "LOOSE AGENT")
        auctions_page = self.client.get(reverse("live_auctions"))
        self.assertContains(auctions_page, "BID TARGET")
        fa_page = self.client.get(reverse("free_agents"))
        self.assertContains(fa_page, "LOOSE AGENT")

        live = self.client.get(reverse("transfer_market"))
        self.assertContains(live, "Club Striker")
        self.assertContains(live, "6.50")
        self.assertContains(live, "Alpha")
        self.assertNotContains(live, "LIVE PLAYER AUCTIONS")
        self.assertNotContains(live, "Bid Target")
        self.assertNotContains(live, "LOOSE AGENT")
        self.assertEqual(PlayerAuction.objects.get(pk=auction.pk).status, PlayerAuction.LIVE)
        self.assertContains(self.client.get(reverse("live_auctions")), "BID TARGET")
        self.assertContains(self.client.get(reverse("free_agents")), "LOOSE AGENT")

        self.client.logout()
        self.client.login(username="buyer", password="test-pass-123")
        buyer = self.client.get(reverse("transfer_market"))
        self.assertContains(buyer, "Club Striker")
        self.assertNotContains(buyer, reverse("buy_player", args=[listing.id]))
        self.assertContains(buyer, reverse("purchase_listing", args=[listing.id]))
        self.assertNotContains(buyer, ">OFFER</button>")
        self.assertContains(buyer, "VIEW PLAYER")
        self.assertContains(buyer, ">BUY</a>")
        buyer_html = buyer.content.decode()
        self.assertLess(buyer_html.index("VIEW PLAYER"), buyer_html.index(">BUY</a>"))

        self.client.logout()
        self.client.login(username="seller", password="test-pass-123")
        self.client.post(reverse("cancel_player_listing", args=[listing.id]))
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.CANCELLED)
        gone = self.client.get(reverse("transfer_market"))
        self.assertContains(gone, "NO PLAYERS LISTED")
        self.assertNotContains(gone, reverse("purchase_listing", args=[listing.id]))
        self.assertNotContains(gone, "Bid Target")
        self.assertNotContains(gone, "LOOSE AGENT")
        self.assertContains(self.client.get(reverse("live_auctions")), "BID TARGET")
        self.assertContains(self.client.get(reverse("free_agents")), "LOOSE AGENT")


class ClubAuctionSquadLifecycleTests(TestCase):
    def setUp(self):
        self.league = League.objects.create(name="Auction League", short_name="AUC", season="1")
        self.owner = _user("auction-owner", role=User.OWNER)
        self.user_a = _user("seller")
        self.user_b = _user("buyer")
        self.mgr_a = _manager(self.user_a)
        self.mgr_b = _manager(self.user_b)
        self.team_a = Team.objects.create(name="Alpha", short_name="ALP", league=self.league, manager=self.user_a)
        self.team_b = Team.objects.create(name="Beta", short_name="BET", league=self.league, manager=self.user_b)
        self.owned = Player.objects.create(
            name="Club Striker",
            position="ST",
            overall=74,
            mgl_team=self.team_a,
            is_free_agent=False,
        )
        self.teammate = Player.objects.create(
            name="Home Keeper",
            position="GK",
            overall=70,
            mgl_team=self.team_a,
            is_free_agent=False,
        )
        self.client = Client(HTTP_HOST="127.0.0.1")
        from mgl.models import LeagueSettings
        LeagueSettings.objects.update(allow_manager_auctions=True)

    def _assert_single_player_row(self):
        self.assertEqual(Player.objects.filter(pk=self.owned.id).count(), 1)
        self.assertEqual(Player.objects.filter(name="Club Striker").count(), 1)

    def test_listed_player_leaves_seller_squad_and_team_management(self):
        occupancy_before = roster_occupancy(self.team_a)
        self.assertEqual(occupancy_before, 2)
        self.client.login(username="seller", password="test-pass-123")
        before = self.client.get(reverse("team_management"))
        self.assertContains(before, "CLUB STRIKER")
        self.assertContains(before, "HOME KEEPER")

        created = self.client.post(
            reverse("list_player_for_auction", args=[self.owned.id]),
            {"duration": "30", "starting_bid": "1"},
        )
        self.assertEqual(created.status_code, 302)
        self.owned.refresh_from_db()
        self.assertIsNone(self.owned.mgl_team_id)
        self.assertFalse(self.owned.is_free_agent)
        self.assertFalse(is_unassigned(self.owned))
        self.assertEqual(market_status(self.owned), AUCTION)
        self.assertEqual(roster_occupancy(self.team_a), occupancy_before)
        self.assertEqual(self.team_a.players.filter(pk=self.owned.id).count(), 0)
        self._assert_single_player_row()

        squad = self.client.get(reverse("team_management"))
        self.assertNotContains(squad, "CLUB STRIKER")
        self.assertContains(squad, "HOME KEEPER")
        self.assertContains(squad, "2/28")
        self.assertEqual(squad.context["available_spaces"], 26)
        steal = self.client.get(
            reverse("team_management"),
            {"list": "auction", "player": self.owned.id},
        )
        self.assertEqual(steal.status_code, 302)
        release = self.client.post(reverse("release_my_player", args=[self.owned.id]))
        self.assertEqual(release.status_code, 404)
        self.owned.refresh_from_db()
        self.assertFalse(self.owned.is_free_agent)
        self.assertIsNone(self.owned.mgl_team_id)

        auctions = self.client.get(reverse("live_auctions"))
        self.assertContains(auctions, "CLUB STRIKER")
        fa_page = self.client.get(reverse("free_agents"))
        self.assertNotContains(fa_page, "Club Striker")
        self.assertNotContains(fa_page, "CLUB STRIKER")

    def test_active_auction_player_stays_off_squad_after_refresh_and_backfill(self):
        auction = create_manager_auction(self.owned, self.mgr_a, 30, starting_bid=1)
        self.owned.mgl_team = self.team_a
        self.owned.save(update_fields=["mgl_team"])
        self.assertEqual(self.team_a.players.filter(pk=self.owned.id).count(), 1)
        detached = detach_live_club_auction_players()
        self.assertEqual(detached, 1)
        self.owned.refresh_from_db()
        self.assertIsNone(self.owned.mgl_team_id)
        self.assertEqual(auction.status, PlayerAuction.LIVE)
        self.client.login(username="seller", password="test-pass-123")
        page = self.client.get(reverse("team_management"))
        self.assertNotContains(page, "CLUB STRIKER")
        self.assertEqual(self.team_a.players.filter(pk=self.owned.id).count(), 0)

    def test_winning_bid_moves_player_to_buyer_only(self):
        auction = create_manager_auction(self.owned, self.mgr_a, 30, starting_bid=1)
        place_auction_bid(auction, self.mgr_b, 5)
        settle_auction(auction)
        self.owned.refresh_from_db()
        auction.refresh_from_db()
        self.assertEqual(auction.status, PlayerAuction.ENDED)
        self.assertEqual(self.owned.mgl_team_id, self.team_b.id)
        self.assertFalse(self.owned.is_free_agent)
        self.assertEqual(self.team_a.players.filter(pk=self.owned.id).count(), 0)
        self.assertEqual(self.team_b.players.filter(pk=self.owned.id).count(), 1)
        self.assertEqual(Player.objects.filter(mgl_team=self.team_b, name="Club Striker").count(), 1)
        self._assert_single_player_row()
        again, message = settle_auction(auction)
        self.assertIn("no longer live", message)
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.mgl_team_id, self.team_b.id)
        self.client.login(username="seller", password="test-pass-123")
        seller_page = self.client.get(reverse("team_management"))
        self.assertNotContains(seller_page, "CLUB STRIKER")
        self.client.logout()
        self.client.login(username="buyer", password="test-pass-123")
        buyer_page = self.client.get(reverse("team_management"))
        self.assertContains(buyer_page, "CLUB STRIKER")

    def test_expired_unsold_auction_returns_player_to_original_squad(self):
        auction = create_manager_auction(self.owned, self.mgr_a, 30, starting_bid=1)
        auction.ends_at = timezone.now() - timedelta(minutes=1)
        auction.save(update_fields=["ends_at"])
        closed = close_expired_auctions()
        self.assertEqual(closed, 1)
        self.owned.refresh_from_db()
        auction.refresh_from_db()
        self.assertEqual(auction.status, PlayerAuction.ENDED)
        self.assertIsNone(auction.winning_manager_id)
        self.assertEqual(self.owned.mgl_team_id, self.team_a.id)
        self.assertFalse(self.owned.is_free_agent)
        self.assertEqual(self.team_a.players.filter(pk=self.owned.id).count(), 1)
        self._assert_single_player_row()
        self.client.login(username="seller", password="test-pass-123")
        page = self.client.get(reverse("team_management"))
        self.assertContains(page, "CLUB STRIKER")
        self.assertContains(page, ">AUCTION<")
        auctions = self.client.get(reverse("live_auctions"))
        self.assertContains(auctions, "RECENTLY ENDED")
        self.assertContains(auctions, "CLUB STRIKER")
        self.assertNotContains(auctions, f'action="{reverse("place_bid", args=[auction.id])}"')

    def test_owner_cancel_returns_player_and_refunds_bid(self):
        auction = create_manager_auction(self.owned, self.mgr_a, 30, starting_bid=1)
        place_auction_bid(auction, self.mgr_b, 6)
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.mgr_b.tokens, Decimal("34.00"))
        self.client.login(username="auction-owner", password="test-pass-123")
        response = self.client.post(reverse("control_cancel_auction", args=[auction.id]))
        self.assertEqual(response.status_code, 302)
        self.owned.refresh_from_db()
        auction.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(auction.status, PlayerAuction.CANCELLED)
        self.assertEqual(self.owned.mgl_team_id, self.team_a.id)
        self.assertFalse(self.owned.is_free_agent)
        self.assertEqual(self.mgr_b.tokens, Decimal("40.00"))
        self.assertEqual(self.team_a.players.filter(pk=self.owned.id).count(), 1)
        self._assert_single_player_row()
        with self.assertRaises(ValueError):
            cancel_live_auction(auction)
        self.client.logout()
        self.client.login(username="seller", password="test-pass-123")
        page = self.client.get(reverse("team_management"))
        self.assertContains(page, "CLUB STRIKER")
        self.client.logout()
        self.client.login(username="buyer", password="test-pass-123")
        auctions = self.client.get(reverse("live_auctions"))
        self.assertNotContains(auctions, "Club Striker")

    def test_player_cannot_be_in_two_active_auctions(self):
        first = create_manager_auction(self.owned, self.mgr_a, 30, starting_bid=1)
        with self.assertRaises(ValueError):
            create_manager_auction(self.owned, self.mgr_a, 30, starting_bid=1)
        with self.assertRaises(ValueError):
            create_manager_auction(self.owned, self.mgr_b, 30, starting_bid=1)
        self.assertEqual(
            PlayerAuction.objects.filter(
                player=self.owned,
                status__in=[PlayerAuction.PENDING, PlayerAuction.LIVE],
            ).count(),
            1,
        )
        self.assertEqual(PlayerAuction.objects.filter(player=self.owned).count(), 1)
        self.assertEqual(first.status, PlayerAuction.LIVE)

    def test_cancel_and_restore_do_not_duplicate_squad_rows(self):
        auction = create_manager_auction(self.owned, self.mgr_a, 30, starting_bid=0)
        cancel_live_auction(auction)
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.mgl_team_id, self.team_a.id)
        self.assertEqual(self.team_a.players.filter(pk=self.owned.id).count(), 1)
        self._assert_single_player_row()
        second = create_manager_auction(self.owned, self.mgr_a, 30, starting_bid=0)
        second.ends_at = timezone.now() - timedelta(minutes=1)
        second.save(update_fields=["ends_at"])
        close_expired_auctions()
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.mgl_team_id, self.team_a.id)
        self.assertEqual(Player.objects.filter(mgl_team=self.team_a, pk=self.owned.id).count(), 1)
        close_expired_auctions()
        self.owned.refresh_from_db()
        self.assertEqual(self.team_a.players.filter(pk=self.owned.id).count(), 1)
        self._assert_single_player_row()
