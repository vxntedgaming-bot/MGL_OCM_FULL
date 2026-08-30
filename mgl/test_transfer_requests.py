from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.market import approve_listing, create_transfer_offer
from mgl.models import ManagerNotification, MarketTransaction, PlayerListing
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

    def test_manager_sees_incoming_requests(self):
        create_transfer_offer(self.player_b, self.mgr_a, "8.00")
        self.client.login(username="seller", password="test-pass-123")
        page = self.client.get(reverse("transfer_requests"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "TRANSFERS")
        self.assertContains(page, "INCOMING REQUESTS")
        self.assertContains(page, "Blue Midfielder")
        self.assertContains(page, "Arsenal Test")
        self.assertContains(page, "APPROVE")
        self.assertContains(page, "REJECT")
        self.assertContains(page, "PENDING")

    def test_manager_sees_outgoing_requests_without_approve_buttons(self):
        create_transfer_offer(self.player_b, self.mgr_a, "8.00")
        self.client.login(username="buyer", password="test-pass-123")
        page = self.client.get(reverse("transfer_requests"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "OUTGOING REQUESTS")
        self.assertContains(page, "Blue Midfielder")
        self.assertContains(page, "Chelsea Test")
        self.assertNotContains(page, ">APPROVE</button>")
        self.assertNotContains(page, ">REJECT</button>")

    def test_manager_cannot_see_another_managers_requests(self):
        create_transfer_offer(self.player_b, self.mgr_a, "8.00")
        create_transfer_offer(self.player_c, self.mgr_a, "5.00")
        self.client.login(username="outsider", password="test-pass-123")
        page = self.client.get(reverse("transfer_requests"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Lilywhite Winger")
        self.assertNotContains(page, "Blue Midfielder")
        incoming_html = page.content.decode().split('id="incoming-requests"', 1)[1].split(
            'id="outgoing-requests"', 1
        )[0]
        self.assertNotIn("Blue Midfielder", incoming_html)
        self.assertNotIn("Chelsea Test", incoming_html)

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
        self.assertContains(page, "HERE WE GO")
        self.assertContains(page, "Completed Striker")
        self.assertContains(page, "9 TOKENS")
        self.assertContains(page, "MANAGERS")
        self.assertContains(page, "Buyer")
        self.assertContains(page, "TRANSFER WINDOW OPEN")
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
