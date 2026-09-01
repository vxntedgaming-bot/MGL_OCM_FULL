from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from auctions.models import PlayerAuction
from leagues.models import League
from managers.models import ManagerApplication
from mgl.market import (
    counter_transfer_offer,
    create_listed_purchase_offer,
    list_player_for_sale,
    place_auction_bid,
    request_listing_changes,
    respond_to_transfer_offer,
)
from mgl.models import DiscordEvent, PlayerListing, PressConference, ScoutSquadException
from mgl.press import approve_press_conference, create_press_question, submit_press_answer
from mgl.scouting import dispatch_scout, resolve_scout_exception
from mgl.test_scouting import _finish
from players.models import Player
from teams.models import Team


def _user(name, role=User.MANAGER):
    return User.objects.create_user(username=name, password="test-pass-123", role=role)


def _manager(user, tokens="20.00"):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username,
        gamertag=user.username[:8],
        status=ManagerApplication.APPROVED,
        tokens=Decimal(tokens),
    )


class UFLCareerModeTests(TestCase):
    def setUp(self):
        self.league = League.objects.create(name="Career", short_name="CAR", season="1")
        self.owner = _user("career-owner", User.OWNER)
        self.user_a = _user("career-a")
        self.user_b = _user("career-b")
        self.mgr_a = _manager(self.user_a, "20.00")
        self.mgr_b = _manager(self.user_b, "20.00")
        self.club_a = Team.objects.create(name="Alpha", short_name="ALP", league=self.league, manager=self.user_a)
        self.club_b = Team.objects.create(name="Beta", short_name="BET", league=self.league, manager=self.user_b)
        self.player = Player.objects.create(
            name="Career Striker", position="ST", overall=66, mgl_team=self.club_a, is_free_agent=False
        )
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_public_pages_are_visible(self):
        for name in ("home", "leagues_page", "clubs_index", "player_database", "transfer_market", "live_auctions", "pressroom", "ufl_rules"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

    def test_negotiation_counter_then_accept_stays_owned_until_admin(self):
        listing = list_player_for_sale(self.player, self.mgr_a, "8")
        listing.status = PlayerListing.LIVE
        listing.save(update_fields=["status"])
        create_listed_purchase_offer(listing, self.mgr_b, "8")
        listing.refresh_from_db()
        counter_transfer_offer(listing, self.user_a, "10")
        listing.refresh_from_db()
        self.assertEqual(listing.asking_price, Decimal("10"))
        self.assertEqual(listing.status, PlayerListing.OFFER)
        self.assertEqual(listing.negotiation_events.count(), 2)
        respond_to_transfer_offer(listing, self.user_a, True)
        listing.refresh_from_db()
        self.player.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.PENDING)
        self.assertEqual(self.player.mgl_team_id, self.club_a.id)

    def test_self_auction_bid_is_rejected(self):
        from mgl.market import create_manager_auction

        auction = create_manager_auction(self.player, self.mgr_a, 30, 1)
        with self.assertRaisesMessage(ValueError, "your own auction"):
            place_auction_bid(auction, self.mgr_a, 2)
        self.assertEqual(PlayerAuction.objects.get(pk=auction.pk).winning_bid, 0)

    def test_press_pays_only_after_approval(self):
        press = create_press_question(
            manager=self.user_a,
            team=self.club_a,
            question="What pleased you most?",
            question_key="career_press",
            category="performance",
            trigger=PressConference.MATCH,
        )
        submit_press_answer(press, "The pressing.")
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("20.00"))
        approve_press_conference(press, reviewer=self.owner)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("20.50"))

    def test_full_squad_scout_creates_exception(self):
        for index in range(27):
            Player.objects.create(
                name=f"Filled {index}",
                position="CM",
                overall=61,
                nationality="England",
                mgl_team=self.club_a,
                is_free_agent=False,
            )
        target = Player.objects.create(
            name="Waiting Prospect",
            position="ST",
            overall=50,
            nationality="France",
            is_free_agent=False,
        )
        assignment = dispatch_scout(self.mgr_a, "BRONZE", "europe", "ST")
        _finish(assignment)
        target.refresh_from_db()
        self.assertIsNone(target.mgl_team_id)
        self.assertTrue(ScoutSquadException.objects.filter(player=target, status="PENDING").exists())
        self.assertEqual(Player.objects.filter(mgl_team=self.club_a).count(), 28)

    def test_request_changes_returns_deal_without_ownership_change(self):
        listing = list_player_for_sale(self.player, self.mgr_a, "8")
        listing.status = PlayerListing.LIVE
        listing.save(update_fields=["status"])
        create_listed_purchase_offer(listing, self.mgr_b, "8")
        respond_to_transfer_offer(listing, self.user_a, True)
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.PENDING)
        request_listing_changes(listing, self.owner, "Raise the token offer.")
        listing.refresh_from_db()
        self.player.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.OFFER)
        self.assertEqual(listing.request_changes_note, "Raise the token offer.")
        self.assertEqual(self.player.mgl_team_id, self.club_a.id)
        self.client.login(username="career-owner", password="test-pass-123")
        response = self.client.post(
            reverse("control_request_listing_changes", args=[listing.id]),
            {"reason": "Need a swap player too."},
        )
        self.assertEqual(response.status_code, 302)

    def test_listed_player_leaves_active_roster_ui(self):
        list_player_for_sale(self.player, self.mgr_a, "5")
        self.client.login(username="career-a", password="test-pass-123")
        response = self.client.get(reverse("team_management"))
        self.assertContains(response, "OFF ACTIVE ROSTER")
        self.assertContains(response, "TRANSFER LISTED")
        self.assertContains(response, "Career Striker")

    def test_homepage_renders_live_modules(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RECENT RESULTS")
        self.assertContains(response, "LATEST TRANSFERS")
        self.assertContains(response, "LIVE AUCTIONS")
        self.assertContains(response, "FEATURED PLAYERS")
        self.assertContains(response, "LEAGUE ACTIVITY")

    def test_discord_link_rejects_username_and_theft(self):
        self.user_b.discord_id = "999888777"
        self.user_b.save(update_fields=["discord_id"])
        self.client.login(username="career-a", password="test-pass-123")
        blocked = self.client.post(reverse("manager_profile"), {"action": "link_discord", "discord_id": "not-a-number"})
        self.assertEqual(blocked.status_code, 302)
        self.user_a.refresh_from_db()
        self.assertFalse(self.user_a.discord_id)
        stolen = self.client.post(reverse("manager_profile"), {"action": "link_discord", "discord_id": "999888777"})
        self.assertEqual(stolen.status_code, 302)
        self.user_a.refresh_from_db()
        self.assertNotEqual(self.user_a.discord_id, "999888777")
        linked = self.client.post(reverse("manager_profile"), {"action": "link_discord", "discord_id": "111222333"})
        self.assertEqual(linked.status_code, 302)
        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.discord_id, "111222333")

    def test_notification_category_filter_and_personal_discord(self):
        self.user_a.discord_id = "444555666"
        self.user_a.save(update_fields=["discord_id"])
        from mgl.notifications import notify_user

        notify_user(
            self.user_a,
            source_key="career-transfer-note",
            notification_type="TRANSFER",
            title="OFFER RECEIVED",
            message="Beta bid 8 TKN.",
            action_url="/mgl/transfers/requests/",
        )
        self.assertTrue(
            any(
                (event.payload or {}).get("discord_id") == "444555666"
                for event in DiscordEvent.objects.filter(channel_key="DM")
            )
        )
        self.client.login(username="career-a", password="test-pass-123")
        transfers = self.client.get(reverse("manager_notifications"), {"category": "Transfers"})
        self.assertContains(transfers, "OFFER RECEIVED")
        press = self.client.get(reverse("manager_notifications"), {"category": "Press"})
        self.assertNotContains(press, "OFFER RECEIVED")

    def test_owner_can_resolve_scout_exception(self):
        for index in range(27):
            Player.objects.create(
                name=f"Cap {index}",
                position="CM",
                overall=61,
                nationality="England",
                mgl_team=self.club_a,
                is_free_agent=False,
            )
        target = Player.objects.create(
            name="Exception Prospect",
            position="ST",
            overall=51,
            nationality="Spain",
            is_free_agent=False,
        )
        assignment = dispatch_scout(self.mgr_a, "BRONZE", "europe", "ST")
        _finish(assignment)
        exception = ScoutSquadException.objects.get(player=target, status="PENDING")
        resolve_scout_exception(exception, self.owner, assign=False, note="Keep the pool balanced.")
        exception.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(exception.status, ScoutSquadException.RELEASED)
        self.assertIsNone(target.mgl_team_id)
        self.assertEqual(Player.objects.filter(mgl_team=self.club_a).count(), 28)

    def test_public_cannot_access_control_or_bid(self):
        from mgl.market import create_manager_auction

        listing = list_player_for_sale(self.player, self.mgr_a, "8")
        listing.status = PlayerListing.PENDING
        listing.save(update_fields=["status"])
        forbidden = self.client.post(reverse("control_approve_listing", args=[listing.id]))
        self.assertIn(forbidden.status_code, (302, 403))
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.PENDING)
        extra = Player.objects.create(
            name="Public Auction", position="CM", overall=64, mgl_team=self.club_b, is_free_agent=False
        )
        create_manager_auction(extra, self.mgr_b, 30, 1)
        auction = self.client.get(reverse("live_auctions"))
        self.assertEqual(auction.status_code, 200)
        self.assertContains(auction, "SIGN IN TO BID")
