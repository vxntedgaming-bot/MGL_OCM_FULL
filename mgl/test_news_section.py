from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.admin import approve_match_submission
from mgl.market import (
    approve_listing,
    create_listed_purchase_offer,
    list_player_for_sale,
    reject_listing,
    respond_to_transfer_offer,
)
from mgl.models import (
    ApprovalStatus,
    Fixture,
    MatchSubmission,
    NewsPost,
    PlayerListing,
    PressConference,
    TeamMatchStats,
)
from mgl.activity import extract_newsroom_feed, extract_page_main, published_football_activity
from mgl.press import approve_press_conference, create_press_question, reject_press_conference
from mgl.services import sign_free_agent
from players.models import Player
from teams.models import Team


def _user(username, role=User.MANAGER):
    return User.objects.create_user(
        username=username,
        password="test-pass-123",
        role=role,
    )


def _manager(user, tokens="50.00"):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=ManagerApplication.APPROVED,
        tokens=Decimal(tokens),
    )


class NewsSectionTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.owner = _user("owner", role=User.OWNER)
        self.user_a = _user("kai")
        self.user_b = _user("rival")
        self.mgr_a = _manager(self.user_a)
        self.mgr_b = _manager(self.user_b)
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
        self.player = Player.objects.create(
            name="Moveable Mid",
            position="CM",
            overall=74,
            mgl_team=self.team_a,
            is_free_agent=False,
        )

    def _pending_match(self, home_goals=5, away_goals=8):
        fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            matchweek=4,
            is_released=True,
            status="SCHEDULED",
        )
        submission = MatchSubmission.objects.create(
            fixture=fixture,
            submitted_by=self.user_a,
            status=ApprovalStatus.PENDING,
            opponent_response=ApprovalStatus.APPROVED,
        )
        TeamMatchStats.objects.create(
            submission=submission, team=self.team_a, goals=home_goals, shots=10, possession=52
        )
        TeamMatchStats.objects.create(
            submission=submission, team=self.team_b, goals=away_goals, shots=9, possession=48
        )
        return fixture, submission

    def test_news_routes_and_nav_only_have_two_destinations(self):
        home = self.client.get("/")
        self.assertContains(home, reverse("live_activity"))
        self.assertNotContains(home, "Official News")

        centre = self.client.get(reverse("news_centre"))
        self.assertEqual(centre.status_code, 302)
        self.assertEqual(centre["Location"], reverse("live_activity"))
        press_tab = self.client.get(reverse("news_centre"), {"tab": "pressroom"})
        self.assertEqual(press_tab.status_code, 302)
        self.assertEqual(press_tab["Location"], reverse("pressroom"))

        activity = self.client.get(reverse("live_activity"))
        self.assertEqual(activity.status_code, 200)
        self.assertContains(activity, "LEAGUE")
        self.assertContains(activity, "ACTIVITY")
        self.assertContains(activity, "No league activity yet.")
        self.assertNotContains(activity, "Live feed of results, transfers and signings across all leagues.")
        self.assertNotContains(activity, "New results, transfers and signings will appear here.")
        self.assertNotContains(activity, "Latest News")
        self.assertNotContains(activity, "Official News")
        self.assertNotContains(activity, "Fulham")
        self.assertNotContains(activity, "Hull City")

        room = self.client.get(reverse("pressroom"))
        self.assertEqual(room.status_code, 200)
        self.assertContains(room, reverse("live_activity"))
        self.assertContains(room, "core/css/ufl.css")
        self.assertContains(room, "PRESS ROOM")
        self.assertContains(room, "Approved press answers")
        self.assertContains(room, "NO PRESSROOM STORIES YET")
        self.assertContains(room, "NO PRESS CONFERENCES YET")
        self.assertContains(room, "THE UFL WORLD IS WATCHING")
        self.assertNotContains(room, "Latest News")

    def test_pending_and_rejected_results_stay_off_live_activity(self):
        _fixture, submission = self._pending_match()
        page = self.client.get(reverse("live_activity"))
        self.assertNotContains(page, "Arsenal Test")
        self.assertFalse(published_football_activity().exists())

        submission.status = ApprovalStatus.REJECTED
        submission.save(update_fields=["status"])
        page = self.client.get(reverse("live_activity"))
        self.assertNotContains(page, "5 - 8")
        self.assertFalse(NewsPost.objects.filter(category=NewsPost.RESULTS).exists())

    def test_approved_result_appears_on_live_activity_not_pressroom(self):
        _fixture, submission = self._pending_match()
        ok, _ = approve_match_submission(submission, self.owner)
        self.assertTrue(ok)
        page = self.client.get(reverse("live_activity"))
        self.assertContains(page, "RESULT")
        self.assertContains(page, "MATCH COMPLETED")
        self.assertContains(page, "Arsenal Test")
        self.assertContains(page, "Chelsea Test")
        self.assertContains(page, "5 - 8")
        self.assertContains(page, "Kai")
        self.assertContains(page, "Rival")
        self.assertContains(page, "Gameweek 4")
        room = self.client.get(reverse("pressroom"))
        self.assertNotContains(room, "5 - 8")

    def test_unpublished_and_press_news_are_excluded_from_football_feed(self):
        NewsPost.objects.create(
            category=NewsPost.TRANSFER,
            title="Secret Chelsea Test deal",
            body="Pending transfer involving Arsenal Test.",
            published=False,
        )
        NewsPost.objects.create(
            category=NewsPost.PRESS,
            title="Interview night",
            body="Q: identity?\n\nA: high press.",
            published=True,
        )
        NewsPost.objects.create(
            category=NewsPost.TRANSFER,
            title="Moveable Mid listed for sale",
            body="Arsenal Test listed Moveable Mid for 8 tokens.",
            published=True,
            primary_team=self.team_a,
        )
        page = self.client.get(reverse("live_activity"))
        feed = extract_newsroom_feed(page.content.decode())
        self.assertNotIn("Secret Chelsea Test deal", feed)
        self.assertNotIn("Interview night", feed)
        self.assertNotIn("listed for sale", feed)
        self.assertFalse(published_football_activity().exists())

    def test_pending_listing_is_not_a_completed_transfer(self):
        listing = list_player_for_sale(self.player, self.mgr_a, 8)
        self.assertEqual(listing.status, "LIVE")
        page = self.client.get(reverse("live_activity"))
        feed = extract_newsroom_feed(page.content.decode())
        self.assertNotIn("Moveable Mid", feed)
        self.assertFalse(
            published_football_activity().filter(category=NewsPost.TRANSFER).exists()
        )

    def test_rejected_listing_is_not_live_activity(self):
        listing = list_player_for_sale(self.player, self.mgr_a, 8)
        listing.status = PlayerListing.PENDING
        listing.reserved_buyer = self.mgr_b
        listing.save(update_fields=["status", "reserved_buyer"])
        reject_listing(listing, self.owner)
        page = self.client.get(reverse("live_activity"))
        feed = extract_newsroom_feed(page.content.decode())
        self.assertNotIn("Moveable Mid", feed)

    def test_approved_completed_transfer_appears_on_live_activity(self):
        listing = list_player_for_sale(self.player, self.mgr_a, 8)
        listed_page = self.client.get(reverse("live_activity"))
        listed_feed = extract_newsroom_feed(listed_page.content.decode())
        self.assertNotIn("listed for sale", listed_feed)
        offer = create_listed_purchase_offer(listing, self.mgr_b, "8")
        respond_to_transfer_offer(offer, self.user_a, True)
        approve_listing(offer, self.owner)
        page = self.client.get(reverse("live_activity"))
        self.assertContains(page, "TRANSFER")
        self.assertContains(page, "Moveable Mid")
        self.assertContains(page, "Arsenal Test")
        self.assertContains(page, "Chelsea Test")
        self.assertContains(page, "TRANSFER COMPLETED")
        room = self.client.get(reverse("pressroom"))
        self.assertNotIn("Moveable Mid", extract_page_main(room.content.decode()))

    def test_approved_signing_does_not_appear_on_live_activity(self):
        fa = Player.objects.create(
            name="New Signing",
            position="ST",
            overall=66,
            is_free_agent=True,
            released_at=timezone.now(),
        )
        sign_free_agent(fa, self.mgr_a)
        self.assertTrue(NewsPost.objects.filter(category=NewsPost.SIGNING).exists())
        page = self.client.get(reverse("live_activity"))
        feed = extract_newsroom_feed(page.content.decode())
        self.assertNotIn("SIGNING", feed)
        self.assertNotIn("New Signing", feed)
        self.assertNotIn("New signing", feed)
        self.assertFalse(
            published_football_activity().filter(category=NewsPost.SIGNING).exists()
        )
        room = self.client.get(reverse("pressroom"))
        self.assertNotIn("New Signing", extract_page_main(room.content.decode()))

    def test_manager_cannot_publish_press_or_open_another_manager_answer(self):
        press = create_press_question(
            manager=self.user_a,
            team=self.team_a,
            question="What identity do you want?",
            question_key="id_q",
            category="identity",
            trigger=PressConference.APPOINTMENT,
        )
        self.client.login(username="kai", password="test-pass-123")
        posted = self.client.post(
            reverse("answer_press", args=[press.pk]),
            {"answer": "Vertical, aggressive football."},
        )
        self.assertEqual(posted.status_code, 302)
        press.refresh_from_db()
        self.assertEqual(press.status, ApprovalStatus.PENDING)
        self.assertFalse(NewsPost.objects.filter(category=NewsPost.PRESS).exists())
        room = self.client.get(reverse("pressroom"))
        self.assertNotContains(room, "Vertical, aggressive football.")
        forbidden = self.client.post(reverse("control_approve_press", args=[press.pk]))
        self.assertEqual(forbidden.status_code, 302)
        self.assertEqual(forbidden["Location"], reverse("manager_hub"))
        press.refresh_from_db()
        self.assertEqual(press.status, ApprovalStatus.PENDING)

        self.client.logout()
        self.client.login(username="rival", password="test-pass-123")
        other = self.client.get(reverse("answer_press", args=[press.pk]))
        self.assertEqual(other.status_code, 404)

        self.client.logout()
        self.client.login(username="owner", password="test-pass-123")
        control = self.client.get(reverse("control_centre"))
        self.assertContains(control, "PRESS CONFERENCE ANSWERS")
        self.assertContains(control, "What identity do you want?")
        self.client.post(reverse("control_approve_press", args=[press.pk]))
        press.refresh_from_db()
        self.assertEqual(press.status, ApprovalStatus.APPROVED)
        room = self.client.get(reverse("pressroom"))
        self.assertContains(room, "Vertical, aggressive football.")
        activity = self.client.get(reverse("live_activity"))
        self.assertNotContains(activity, "Vertical, aggressive football.")

    def test_rejected_press_answer_stays_off_pressroom(self):
        press = create_press_question(
            manager=self.user_a,
            team=self.team_a,
            question="Any regrets?",
            question_key="regrets",
            category="loss",
            trigger=PressConference.MATCH,
        )
        self.client.login(username="kai", password="test-pass-123")
        self.client.post(
            reverse("answer_press", args=[press.pk]),
            {"answer": "None."},
        )
        reject_press_conference(press)
        room = self.client.get(reverse("pressroom"))
        self.assertNotContains(room, "None.")
        self.assertFalse(NewsPost.objects.filter(category=NewsPost.PRESS).exists())
        activity = self.client.get(reverse("live_activity"))
        self.assertNotContains(activity, "None.")
