from datetime import timedelta
from decimal import Decimal

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
    create_free_agent_auction,
    create_manager_auction,
    list_player_for_sale,
    parse_auction_starting_bid,
    settle_auction,
)
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

    def test_team_management_uses_cards_not_old_list(self):
        self.client.login(username="seller", password="test-pass-123")
        page = self.client.get(reverse("team_management"))
        self.assertContains(page, "CLUB STRIKER")
        self.assertContains(page, "mgl/cards/")
        self.assertContains(page, "LIST FOR TRANSFER")
        self.assertContains(page, "LIST FOR AUCTION")
        self.assertContains(page, "RELEASE")
        self.assertContains(page, "core/img/mgl-starting-xi.png")
        self.assertContains(page, "mgl-starting-xi.css")
        self.assertNotContains(page, "mgl-pitch-chip")
        self.assertNotContains(page, "aria-label=\"Squad pitch\"")
        self.assertNotContains(page, "SELL A PLAYER")
        self.assertNotContains(page, "LIST FOR SALE")
        self.assertNotContains(page, "TOKEN ASKING PRICE")
        self.assertNotContains(page, "class=\"table-row\"")

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

    def test_combined_six_listing_cap_covers_transfers_and_auctions(self):
        extras = [
            Player.objects.create(
                name=f"Slot {i}",
                position="CB",
                overall=65,
                mgl_team=self.team_a,
                is_free_agent=False,
            )
            for i in range(5)
        ]
        for extra in extras[:4]:
            list_player_for_sale(extra, self.mgr_a, "3")
        create_manager_auction(extras[4], self.mgr_a, 30, starting_bid=0)
        create_manager_auction(self.owned, self.mgr_a, 60, starting_bid=2)
        seventh = Player.objects.create(name="Seventh", position="ST", overall=66, mgl_team=self.team_a, is_free_agent=False)
        with self.assertRaisesMessage(ValueError, MARKET_SLOT_MESSAGE):
            list_player_for_sale(seventh, self.mgr_a, "4")
        with self.assertRaisesMessage(ValueError, MARKET_SLOT_MESSAGE):
            create_manager_auction(seventh, self.mgr_a, 30, starting_bid=1)
        self.assertEqual(MAX_ACTIVE_CLUB_LISTINGS, 6)

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
        self.assertEqual(self.owned.mgl_team_id, self.team_a.id)
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
            auction.status = PlayerAuction.CANCELLED
            auction.save(update_fields=["status"])

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
        self.assertContains(market, "Starting price")

    def test_http_rejects_other_club_listing_and_seventh_slot(self):
        self.client.login(username="seller", password="test-pass-123")
        blocked = self.client.post(reverse("sell_player", args=[self.other.id]), {"asking_price": "4"})
        self.assertEqual(blocked.status_code, 302)
        self.assertEqual(PlayerListing.objects.filter(player=self.other).count(), 0)
        extras = [
            Player.objects.create(name=f"Cap {i}", position="CM", overall=60, mgl_team=self.team_a, is_free_agent=False)
            for i in range(6)
        ]
        for extra in extras:
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
        self.assertEqual(listing.status, PlayerListing.PENDING)
        pending = self.client.get(reverse("transfer_market"))
        self.assertContains(pending, "NO PLAYERS LISTED")
        self.assertContains(pending, "Bid Target")
        self.assertContains(pending, "LOOSE AGENT")

        self.client.logout()
        self.client.login(username="sale-owner", password="test-pass-123")
        notice = ManagerNotification.objects.get(
            recipient=owner,
            source_key=f"admin-listing-{listing.pk}",
        )
        self.client.post(reverse("control_approve_listing", args=[listing.id]))
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.LIVE)
        notice.refresh_from_db()
        self.assertEqual(notice.response_status, ManagerNotification.ACCEPTED)

        live = self.client.get(reverse("transfer_market"))
        self.assertContains(live, "Club Striker")
        self.assertContains(live, "6.50")
        self.assertContains(live, "Alpha")
        self.assertContains(live, "Bid Target")
        self.assertContains(live, "LOOSE AGENT")
        self.assertEqual(PlayerAuction.objects.get(pk=auction.pk).status, PlayerAuction.LIVE)

        self.client.logout()
        self.client.login(username="buyer", password="test-pass-123")
        buyer = self.client.get(reverse("transfer_market"))
        self.assertContains(buyer, "Club Striker")
        self.assertContains(buyer, reverse("buy_player", args=[listing.id]))

        self.client.logout()
        self.client.login(username="seller", password="test-pass-123")
        self.client.post(reverse("cancel_player_listing", args=[listing.id]))
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.CANCELLED)
        gone = self.client.get(reverse("transfer_market"))
        self.assertContains(gone, "NO PLAYERS LISTED")
        self.assertNotContains(gone, reverse("buy_player", args=[listing.id]))
        self.assertContains(gone, "Bid Target")
        self.assertContains(gone, "LOOSE AGENT")
