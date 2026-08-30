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
    approve_listing,
    buy_listed_player,
    create_listed_purchase_offer,
    list_player_for_sale,
    place_auction_bid,
    respond_to_transfer_offer,
    settle_auction,
)
from mgl.models import MarketTransaction, PlayerListing
from players.models import Player
from teams.models import Team


class MarketEconomyTests(TestCase):
    def setUp(self):
        self.league = League.objects.create(name="MGL", short_name="MGL", season="1")
        self.owner = User.objects.create_user(
            username="owner",
            password="test-pass-123",
            role=User.OWNER,
        )
        self.user_a = User.objects.create_user(username="manager_a", password="test-pass-123")
        self.user_b = User.objects.create_user(username="manager_b", password="test-pass-123")
        self.mgr_a = ManagerApplication.objects.create(
            user=self.user_a,
            display_name="Manager A",
            gamertag="A1",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("50.00"),
        )
        self.mgr_b = ManagerApplication.objects.create(
            user=self.user_b,
            display_name="Manager B",
            gamertag="B1",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("50.00"),
        )
        self.team_a = Team.objects.create(
            name="Alpha FC",
            short_name="AFC",
            league=self.league,
            manager=self.user_a,
            tokens=Decimal("50.00"),
        )
        self.team_b = Team.objects.create(
            name="Beta FC",
            short_name="BFC",
            league=self.league,
            manager=self.user_b,
            tokens=Decimal("50.00"),
        )
        self.player = Player.objects.create(
            name="Player X",
            position="ST",
            overall=70,
            mgl_team=self.team_a,
            is_free_agent=False,
        )
        self.fa = Player.objects.create(
            name="Free Agent Y",
            position="CM",
            overall=68,
            is_free_agent=True,
        )
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_cannot_sell_player_from_another_club(self):
        with self.assertRaises(ValueError):
            list_player_for_sale(self.player, self.mgr_b, 12)

    def test_sale_moves_player_and_tokens(self):
        listing = list_player_for_sale(self.player, self.mgr_a, 12)
        listing.status = PlayerListing.LIVE
        listing.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            buy_listed_player(listing, self.mgr_b)
        offer = create_listed_purchase_offer(listing, self.mgr_b, "12")
        respond_to_transfer_offer(offer, self.user_a, True)
        approve_listing(offer, self.owner)
        self.player.refresh_from_db()
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.team_a.refresh_from_db()
        self.team_b.refresh_from_db()
        self.assertEqual(self.player.mgl_team_id, self.team_b.id)
        self.assertEqual(self.mgr_a.tokens, Decimal("62.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("38.00"))
        self.assertEqual(self.team_a.tokens, Decimal("50.00"))
        self.assertEqual(self.team_b.tokens, Decimal("50.00"))
        self.assertTrue(
            MarketTransaction.objects.filter(
                player=self.player,
                transaction_type=MarketTransaction.SALE,
                status=MarketTransaction.COMPLETED,
            ).exists()
        )

    def test_cannot_spend_more_tokens_than_the_club_owns(self):
        listing = list_player_for_sale(self.player, self.mgr_a, 80)
        listing.status = PlayerListing.LIVE
        listing.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            create_listed_purchase_offer(listing, self.mgr_b, "80")

    def test_outbid_refunds_previous_club(self):
        auction = PlayerAuction.objects.create(
            player=self.fa,
            starting_bid=1,
            minimum_increment=1,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(hours=1),
            status=PlayerAuction.LIVE,
        )
        place_auction_bid(auction, self.mgr_a, 10)
        place_auction_bid(auction, self.mgr_b, 12)
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.team_a.refresh_from_db()
        self.team_b.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("50.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("38.00"))
        self.assertEqual(self.team_a.tokens, Decimal("50.00"))
        self.assertEqual(self.team_b.tokens, Decimal("50.00"))

    def test_settling_auction_assigns_player(self):
        auction = PlayerAuction.objects.create(
            player=self.fa,
            starting_bid=1,
            minimum_increment=1,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(hours=1),
            status=PlayerAuction.LIVE,
        )
        place_auction_bid(auction, self.mgr_b, 8)
        settle_auction(auction)
        self.fa.refresh_from_db()
        auction.refresh_from_db()
        self.assertEqual(self.fa.mgl_team_id, self.team_b.id)
        self.assertFalse(self.fa.is_free_agent)
        self.assertEqual(auction.status, PlayerAuction.ENDED)

    def test_club_tokens_remain_when_manager_leaves(self):
        self.team_a.tokens = Decimal("41.00")
        self.team_a.save(update_fields=["tokens"])
        self.client.login(username="owner", password="test-pass-123")
        response = self.client.post(
            reverse("remove_club_manager", args=[self.team_a.id])
        )
        self.assertEqual(response.status_code, 302)
        self.team_a.refresh_from_db()
        self.assertIsNone(self.team_a.manager_id)
        self.assertEqual(self.team_a.tokens, Decimal("41.00"))
        self.assertEqual(self.team_a.players.count(), 1)

    def test_raising_own_bid_only_holds_the_new_amount(self):
        auction = PlayerAuction.objects.create(
            player=self.fa,
            starting_bid=1,
            minimum_increment=1,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(hours=1),
            status=PlayerAuction.LIVE,
        )
        place_auction_bid(auction, self.mgr_a, 10)
        place_auction_bid(auction, self.mgr_a, 15)
        self.mgr_a.refresh_from_db()
        self.team_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("35.00"))
        self.assertEqual(self.team_a.tokens, Decimal("50.00"))
        self.assertEqual(auction.bids.filter(manager=self.mgr_a).count(), 1)

    def test_cannot_bid_without_a_club(self):
        self.team_a.manager = None
        self.team_a.save(update_fields=["manager"])
        auction = PlayerAuction.objects.create(
            player=self.fa,
            starting_bid=1,
            minimum_increment=1,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(hours=1),
            status=PlayerAuction.LIVE,
        )
        with self.assertRaises(ValueError):
            place_auction_bid(auction, self.mgr_a, 5)

    def test_owner_can_approve_manager_from_control(self):
        applicant_user = User.objects.create_user(
            username="applicant",
            password="test-pass-123",
            is_active=False,
        )
        application = ManagerApplication.objects.create(
            user=applicant_user,
            display_name="Applicant",
            gamertag="APP1",
            status=ManagerApplication.PENDING,
            tokens=Decimal("0.00"),
        )
        self.client.login(username="owner", password="test-pass-123")
        response = self.client.post(
            reverse("control_approve_manager", args=[application.id])
        )
        self.assertEqual(response.status_code, 302)
        application.refresh_from_db()
        applicant_user.refresh_from_db()
        self.assertEqual(application.status, ManagerApplication.APPROVED)
        self.assertEqual(application.tokens, Decimal("20.00"))
        self.assertTrue(applicant_user.is_active)

    def test_manager_cannot_open_control_centre(self):
        self.client.login(username="manager_a", password="test-pass-123")
        response = self.client.get(reverse("control_centre"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("manager_hub"))

    def test_public_pages_render(self):
        for url in ["/", "/leagues/", "/stats/", "/jobs/", "/market/", "/login/", "/register/"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_logged_out_team_still_redirects(self):
        response = self.client.get("/mgl/team/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])
