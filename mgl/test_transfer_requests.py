from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from auctions.models import PlayerAuction
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.market import (
    approve_listing,
    cancel_live_auction,
    create_transfer_offer,
    place_auction_bid,
    record_completed_auction_transfer,
    settle_auction,
)
from mgl.models import ManagerNotification, MarketTransaction, PlayerListing
from mgl.services import sign_free_agent
from mgl.transfer_requests import completed_transfers_for
from players.models import Player
from teams.models import Team


def _user(username, role=User.MANAGER):
    return User.objects.create_user(
        username=username,
        password="test-pass-123",
        role=role,
    )


def _manager(user, tokens="20.00"):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=ManagerApplication.APPROVED,
        tokens=Decimal(tokens),
    )


class TransferRequestsPageTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.owner = _user("owner", role=User.OWNER)
        self.user_a = _user("buyer")
        self.user_b = _user("seller")
        self.user_c = _user("outsider")
        self.mgr_a = _manager(self.user_a, "20.00")
        self.mgr_b = _manager(self.user_b, "20.00")
        self.mgr_c = _manager(self.user_c, "20.00")
        self.team_a = Team.objects.create(
            name="Arsenal Test",
            short_name="ATX",
            league=self.league,
            manager=self.user_a,
        )
        self.team_b = Team.objects.create(
            name="Chelsea Test",
            short_name="CTX",
            league=self.league,
            manager=self.user_b,
        )
        self.team_c = Team.objects.create(
            name="Spurs Test",
            short_name="STX",
            league=self.league,
            manager=self.user_c,
        )
        self.player_b = Player.objects.create(
            name="Blue Midfielder",
            position="CM",
            overall=80,
            mgl_team=self.team_b,
            is_free_agent=False,
        )
        self.player_c = Player.objects.create(
            name="Lilywhite Winger",
            position="RW",
            overall=78,
            mgl_team=self.team_c,
            is_free_agent=False,
        )

    def test_anonymous_user_cannot_open_manager_page(self):
        response = self.client.get(reverse("transfer_requests"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_pending_offers_do_not_appear_on_completed_history(self):
        create_transfer_offer(self.player_b, self.mgr_a, "8.00")
        self.client.login(username="seller", password="test-pass-123")
        page = self.client.get(reverse("transfer_requests"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "TRANSFERS")
        self.assertContains(page, "COMPLETED TRANSFERS")
        self.assertContains(page, "No completed transfers yet.")
        self.assertNotContains(page, "INCOMING REQUESTS")
        self.assertNotContains(page, "OUTGOING REQUESTS")
        self.assertNotContains(page, "AWAITING OPPONENT")
        self.assertNotContains(page, "AWAITING ADMIN")
        history = page.content.decode().split("<main", 1)[-1].split("</main>", 1)[0]
        self.assertNotIn("Blue Midfielder", history)
        self.assertNotContains(page, ">APPROVE</button>")
        self.assertNotIn(">REJECT</button>", history)
        self.assertNotContains(page, 'href="?status=pending"')

    def test_outgoing_pending_offers_stay_off_completed_history(self):
        create_transfer_offer(self.player_b, self.mgr_a, "8.00")
        self.client.login(username="buyer", password="test-pass-123")
        page = self.client.get(reverse("transfer_requests"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "COMPLETED TRANSFERS")
        self.assertContains(page, "No completed transfers yet.")
        self.assertNotContains(page, "OUTGOING REQUESTS")
        self.assertNotContains(page, "INCOMING REQUESTS")
        history = page.content.decode().split("<main", 1)[-1].split("</main>", 1)[0]
        self.assertNotIn("Blue Midfielder", history)
        self.assertNotContains(page, ">APPROVE</button>")
        self.assertNotIn(">REJECT</button>", history)

    def test_pending_offers_for_other_clubs_are_not_shown_as_completed(self):
        create_transfer_offer(self.player_b, self.mgr_a, "8.00")
        create_transfer_offer(self.player_c, self.mgr_a, "5.00")
        self.client.login(username="outsider", password="test-pass-123")
        page = self.client.get(reverse("transfer_requests"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "No completed transfers yet.")
        history = page.content.decode().split("<main", 1)[-1].split("</main>", 1)[0]
        self.assertNotIn("Lilywhite Winger", history)
        self.assertNotIn("Blue Midfielder", history)
        self.assertNotContains(page, "INCOMING REQUESTS")
        self.assertNotContains(page, "OUTGOING REQUESTS")

    def test_manager_cannot_respond_to_another_clubs_request(self):
        listing = create_transfer_offer(self.player_b, self.mgr_a, "8.00")
        self.client.login(username="outsider", password="test-pass-123")
        stolen = self.client.post(
            reverse("respond_transfer_request", args=[listing.id]),
            {"action": "approve"},
        )
        self.assertEqual(stolen.status_code, 403)
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.OFFER)
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_b.mgl_team_id, self.team_b.id)

    def test_manager_can_approve_incoming_request_into_admin_queue(self):
        listing = create_transfer_offer(self.player_b, self.mgr_a, "8.00")
        self.client.login(username="seller", password="test-pass-123")
        accepted = self.client.post(
            reverse("respond_transfer_request", args=[listing.id]),
            {"action": "approve"},
        )
        self.assertEqual(accepted.status_code, 302)
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.PENDING)
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_b.mgl_team_id, self.team_b.id)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("20.00"))
        self.assertTrue(
            ManagerNotification.objects.filter(
                recipient=self.owner,
                source_key=f"admin-listing-{listing.pk}",
            ).exists()
        )
        self.assertFalse(
            MarketTransaction.objects.filter(
                listing=listing,
                status=MarketTransaction.COMPLETED,
            ).exists()
        )

        approved = approve_listing(listing, self.owner)
        self.assertEqual(approved.status, PlayerListing.SOLD)
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_b.mgl_team_id, self.team_a.id)
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("12.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("28.00"))

    def test_manager_can_reject_incoming_request(self):
        listing = create_transfer_offer(self.player_b, self.mgr_a, "6.00")
        self.client.login(username="seller", password="test-pass-123")
        rejected = self.client.post(
            reverse("respond_transfer_request", args=[listing.id]),
            {"action": "reject"},
        )
        self.assertEqual(rejected.status_code, 302)
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.REJECTED)
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_b.mgl_team_id, self.team_b.id)
        self.assertFalse(
            ManagerNotification.objects.filter(
                recipient=self.owner,
                source_key=f"admin-listing-{listing.pk}",
            ).exists()
        )
        with self.assertRaises(ValueError):
            approve_listing(listing, self.owner)
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_b.mgl_team_id, self.team_b.id)

    def test_public_transfer_list_only_shows_completed_deals(self):
        pending = create_transfer_offer(self.player_b, self.mgr_a, "8.00")
        finished = Player.objects.create(
            name="Completed Striker",
            position="ST",
            overall=82,
            mgl_team=self.team_a,
            is_free_agent=False,
        )
        MarketTransaction.objects.create(
            player=finished,
            seller=self.mgr_b,
            buyer=self.mgr_a,
            from_team=self.team_b,
            to_team=self.team_a,
            amount=Decimal("9.00"),
            transaction_type=MarketTransaction.SALE,
            status=MarketTransaction.COMPLETED,
        )
        MarketTransaction.objects.create(
            player=self.player_c,
            seller=self.mgr_c,
            buyer=self.mgr_a,
            from_team=self.team_c,
            to_team=self.team_a,
            amount=Decimal("4.00"),
            transaction_type=MarketTransaction.SALE,
            status=MarketTransaction.PENDING,
        )
        for url_name in ("transfer_history", "public_transfers"):
            page = self.client.get(reverse(url_name))
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "MGL TRANSFERS")
            self.assertContains(page, "Completed Striker")
            self.assertContains(page, "VIEW")
            self.assertNotContains(page, "Blue Midfielder")
            self.assertNotContains(page, "Lilywhite Winger")
            self.assertNotContains(page, "INCOMING REQUESTS")
            self.assertNotContains(page, "OUTGOING REQUESTS")
            self.assertNotContains(page, ">APPROVE</button>")
            self.assertNotContains(page, ">REJECT</button>")
            self.assertNotContains(page, f"listing-{pending.pk}")

    def test_transfers_page_uses_real_completed_deals(self):
        finished = Player.objects.create(
            name="Completed Striker",
            position="ST",
            overall=82,
            mgl_team=self.team_a,
            is_free_agent=False,
        )
        MarketTransaction.objects.create(
            player=finished,
            seller=self.mgr_b,
            buyer=self.mgr_a,
            from_team=self.team_b,
            to_team=self.team_a,
            amount=Decimal("9.00"),
            transaction_type=MarketTransaction.SALE,
            status=MarketTransaction.COMPLETED,
        )
        self.client.login(username="seller", password="test-pass-123")
        page = self.client.get(reverse("transfer_requests"))
        self.assertContains(page, "MGL | TRANSFERS")
        self.assertContains(page, "COMPLETED TRANSFERS")
        self.assertContains(page, "Completed Striker")
        self.assertContains(page, "9 TOKENS")
        self.assertContains(page, "Chelsea Test")
        self.assertContains(page, "Arsenal Test")
        self.assertNotContains(page, "INCOMING REQUESTS")
        self.assertNotContains(page, "OUTGOING REQUESTS")
        self.assertNotContains(page, "HERE WE GO")
        self.assertNotContains(page, "FLORIAN WIRTZ")

    def test_nav_and_hub_link_show_pending_count(self):
        create_transfer_offer(self.player_b, self.mgr_a, "8.00")
        self.client.login(username="seller", password="test-pass-123")
        hub = self.client.get(reverse("manager_hub"))
        self.assertContains(hub, reverse("transfer_requests"))
        self.assertContains(hub, "TRANSFER REQUESTS")
        self.assertContains(hub, 'class="mgl-dash-badge">1</span>')
        self.assertContains(hub, 'class="mgl-nav-badge is-count">1</span>')

        self.client.logout()
        public = self.client.get("/")
        self.assertNotContains(public, reverse("transfer_requests"))
        self.assertNotContains(public, "INCOMING REQUESTS")


class AuctionTransferHistoryTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.owner = _user("owner", role=User.OWNER)
        self.user_a = _user("buyer")
        self.user_b = _user("seller")
        self.mgr_a = _manager(self.user_a, "50.00")
        self.mgr_b = _manager(self.user_b, "50.00")
        self.team_a = Team.objects.create(
            name="Origin FC",
            short_name="OFC",
            league=self.league,
            manager=self.user_a,
        )
        self.team_b = Team.objects.create(
            name="Winning FC",
            short_name="WFC",
            league=self.league,
            manager=self.user_b,
        )
        self.fa = Player.objects.create(
            name="Pool Striker",
            position="ST",
            overall=88,
            is_free_agent=True,
        )
        self.club_player = Player.objects.create(
            name="Club Defender",
            position="CB",
            overall=84,
            mgl_team=self.team_a,
            is_free_agent=False,
        )

    def _live_auction(self, player, **kwargs):
        now = timezone.now()
        values = {
            "player": player,
            "starting_bid": 1,
            "minimum_increment": 1,
            "starts_at": now - timedelta(minutes=1),
            "ends_at": now + timedelta(hours=1),
            "status": PlayerAuction.LIVE,
            "listing_kind": PlayerAuction.FREE_AGENT,
        }
        values.update(kwargs)
        return PlayerAuction.objects.create(**values)

    def _history_page(self):
        self.client.login(username="buyer", password="test-pass-123")
        return self.client.get(reverse("transfer_requests"))

    def test_live_auction_with_bids_is_not_completed_history(self):
        auction = self._live_auction(self.fa)
        place_auction_bid(auction, self.mgr_a, 6)
        place_auction_bid(auction, self.mgr_b, 8)
        self.assertTrue(
            MarketTransaction.objects.filter(
                player=self.fa,
                transaction_type=MarketTransaction.BID_REFUND,
                status=MarketTransaction.COMPLETED,
            ).exists()
        )
        page = self._history_page()
        self.assertNotContains(page, "Pool Striker")
        self.assertEqual(
            [row.player_id for row in completed_transfers_for(None, all_clubs=True)],
            [],
        )

    def test_settled_free_agent_auction_appears_once_with_fa_from_badge(self):
        auction = self._live_auction(self.fa)
        place_auction_bid(auction, self.mgr_b, 7)
        settle_auction(auction)
        page = self._history_page()
        self.assertContains(page, "Pool Striker")
        self.assertContains(page, "FREE AGENT")
        self.assertContains(page, "Winning FC")
        self.assertContains(page, "7 TOKENS")
        self.assertContains(page, "mgl-fa-mark")
        self.assertEqual(page.content.decode().count("Pool Striker"), 1)
        self.assertEqual(
            MarketTransaction.objects.filter(
                auction=auction,
                transaction_type=MarketTransaction.AUCTION,
                status=MarketTransaction.COMPLETED,
            ).count(),
            1,
        )
        settle_auction(auction)
        record_completed_auction_transfer(
            auction=auction,
            player=self.fa,
            seller=None,
            buyer=self.mgr_b,
            from_team=None,
            to_team=self.team_b,
            amount=7,
        )
        page = self._history_page()
        self.assertEqual(page.content.decode().count("Pool Striker"), 1)
        self.assertEqual(
            MarketTransaction.objects.filter(
                auction=auction,
                transaction_type=MarketTransaction.AUCTION,
                status=MarketTransaction.COMPLETED,
            ).count(),
            1,
        )

    def test_club_player_auction_keeps_origin_club_on_history(self):
        auction = self._live_auction(
            self.club_player,
            listing_kind=PlayerAuction.CLUB,
            origin_team=self.team_a,
            listed_by_manager=self.mgr_a,
        )
        place_auction_bid(auction, self.mgr_b, 9)
        settle_auction(auction)
        page = self._history_page()
        self.assertContains(page, "Club Defender")
        self.assertContains(page, "Origin FC")
        self.assertContains(page, "Winning FC")
        self.assertContains(page, "9 TOKENS")
        self.assertNotContains(page, "FREE AGENT")
        row = completed_transfers_for(None, all_clubs=True)[0]
        self.assertEqual(row.from_team_id, self.team_a.id)
        self.assertEqual(row.to_team_id, self.team_b.id)
        self.assertFalse(row.from_is_free_agent)

    def test_cancelled_auction_does_not_create_completed_transfer(self):
        auction = self._live_auction(self.fa)
        place_auction_bid(auction, self.mgr_a, 4)
        cancel_live_auction(auction)
        page = self._history_page()
        self.assertNotContains(page, "Pool Striker")
        self.assertFalse(
            MarketTransaction.objects.filter(
                auction=auction,
                transaction_type=MarketTransaction.AUCTION,
                status=MarketTransaction.COMPLETED,
            ).exists()
        )

    def test_auction_with_no_bids_does_not_create_completed_transfer(self):
        auction = self._live_auction(self.fa)
        settle_auction(auction)
        page = self._history_page()
        self.assertNotContains(page, "Pool Striker")
        self.assertFalse(
            MarketTransaction.objects.filter(
                player=self.fa,
                transaction_type=MarketTransaction.AUCTION,
            ).exists()
        )

    def test_expired_live_auction_settles_when_history_page_opens(self):
        auction = self._live_auction(self.fa)
        place_auction_bid(auction, self.mgr_b, 5)
        auction.ends_at = timezone.now() - timedelta(minutes=2)
        auction.save(update_fields=["ends_at"])
        page = self._history_page()
        auction.refresh_from_db()
        self.assertEqual(auction.status, PlayerAuction.ENDED)
        self.assertContains(page, "Pool Striker")
        self.assertContains(page, "FREE AGENT")
        self.assertContains(page, "Winning FC")

    def test_free_agent_signing_appears_as_completed_from_free_agent(self):
        signed = Player.objects.create(
            name="Walk On Winger",
            position="LW",
            overall=70,
            is_free_agent=True,
        )
        sign_free_agent(signed, self.mgr_a)
        page = self._history_page()
        self.assertContains(page, "Walk On Winger")
        self.assertContains(page, "FREE AGENT")
        self.assertContains(page, "Origin FC")
        self.assertContains(page, "0 TOKENS")
        self.assertEqual(
            MarketTransaction.objects.filter(
                player=signed,
                notes="Free agent signing",
                status=MarketTransaction.COMPLETED,
            ).count(),
            1,
        )
        row = next(
            item
            for item in completed_transfers_for(None, all_clubs=True)
            if item.player_id == signed.id
        )
        self.assertTrue(row.from_is_free_agent)
        self.assertEqual(row.to_team_id, self.team_a.id)
