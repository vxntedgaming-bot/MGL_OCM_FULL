from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.admin import approve_match_submission
from mgl.models import (
    ApprovalStatus,
    Fixture,
    MatchSubmission,
    NewsPost,
    PlayerListing,
    PressConference,
    TeamMatchStats,
)
from mgl.notifications import notifications_for_user
from mgl.press import create_press_question, publish_press_answer
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


class NotificationAndPressroomTests(TestCase):
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
            name="Listed Striker",
            position="ST",
            overall=78,
            mgl_team=self.team_a,
            is_free_agent=False,
        )

    def test_logged_out_home_has_no_notification_bar(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertNotContains(home, "data-notify-dropdown")
        self.assertContains(home, "Recruitment Drive")
        self.assertContains(home, "MY TEAM")
        self.assertNotContains(home, "MY CLUB")

    def test_press_creates_one_notification_and_answer_publishes(self):
        press = create_press_question(
            manager=self.user_a,
            team=self.team_a,
            question="How pleased were you with your team's performance?",
            question_key="perf_pleased",
            category="performance",
            trigger=PressConference.MATCH,
        )
        notes = notifications_for_user(self.user_a)
        press_notes = [row for row in notes if row["key"] == f"press-{press.pk}"]
        self.assertEqual(len(press_notes), 1)
        self.assertEqual(len({row["key"] for row in notes}), len(notes))
        self.assertIn("Sky Sports", press_notes[0]["body"])
        self.assertEqual(press_notes[0]["url"], reverse("answer_press", args=[press.pk]))

        self.client.login(username="kai", password="test-pass-123")
        hub = self.client.get(reverse("manager_hub"))
        self.assertContains(hub, "PRESS CONFERENCE")
        self.assertContains(hub, "ANSWER NOW")
        self.assertContains(hub, reverse("answer_press", args=[press.pk]))
        self.assertNotContains(hub, "PENDING ACTIONS")

        page = self.client.get(reverse("answer_press", args=[press.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "ANSWER PRESS QUESTION")
        self.assertContains(page, "How pleased were you with your team's performance?")

        posted = self.client.post(
            reverse("answer_press", args=[press.pk]),
            {"answer": "We controlled the game from the start."},
        )
        self.assertEqual(posted.status_code, 302)
        self.assertEqual(posted["Location"], reverse("pressroom"))

        press.refresh_from_db()
        self.assertEqual(press.status, ApprovalStatus.APPROVED)
        remaining = [
            row for row in notifications_for_user(self.user_a) if row["key"].startswith("press-")
        ]
        self.assertEqual(remaining, [])

        room = self.client.get(reverse("pressroom"))
        self.assertContains(room, "ARSENAL TEST")
        self.assertContains(room, "Manager: Kai")
        self.assertContains(room, "How pleased were you with your team's performance?")
        self.assertContains(room, "We controlled the game from the start.")
        self.assertContains(room, "PRESS CONFERENCE")
        self.assertNotContains(room, "YOUR QUESTIONS")

        self.assertTrue(
            NewsPost.objects.filter(category=NewsPost.PRESS, published=True).exists()
        )
        activity = self.client.get(reverse("live_activity"))
        self.assertContains(activity, "PRESS CONFERENCE")
        self.assertContains(activity, "Arsenal Test")

    def test_result_notification_clears_after_submit(self):
        fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            matchweek=2,
            is_released=True,
            status="SCHEDULED",
        )
        notes = notifications_for_user(self.user_a)
        result_notes = [row for row in notes if row["key"] == f"result-{fixture.pk}"]
        self.assertEqual(len(result_notes), 1)
        self.assertIn("Chelsea Test", result_notes[0]["body"])
        self.assertEqual(result_notes[0]["url"], reverse("submit_match", args=[fixture.pk]))

        MatchSubmission.objects.create(
            fixture=fixture,
            submitted_by=self.user_a,
            status=ApprovalStatus.PENDING,
        )
        after = [
            row
            for row in notifications_for_user(self.user_a)
            if row["key"] == f"result-{fixture.pk}"
        ]
        self.assertEqual(after, [])
        waiting = notifications_for_user(self.user_a)
        self.assertFalse(any("waiting for approval" in row["body"].lower() for row in waiting))

    def test_live_listing_creates_single_transfer_notification(self):
        listing = PlayerListing.objects.create(
            player=self.player,
            team=self.team_a,
            seller=self.mgr_a,
            asking_price=Decimal("5.00"),
            status=PlayerListing.LIVE,
        )
        notes = [
            row
            for row in notifications_for_user(self.user_a)
            if row["key"] == f"listing-{listing.pk}"
        ]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["kind"], "TRANSFER")
        listing.status = PlayerListing.SOLD
        listing.save(update_fields=["status"])
        self.assertFalse(
            any(
                row["key"] == f"listing-{listing.pk}"
                for row in notifications_for_user(self.user_a)
            )
        )

    def test_approved_result_shows_both_team_badges(self):
        fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            matchweek=1,
            is_released=True,
            status="SCHEDULED",
        )
        submission = MatchSubmission.objects.create(
            fixture=fixture,
            submitted_by=self.user_a,
            status=ApprovalStatus.PENDING,
        )
        TeamMatchStats.objects.create(
            submission=submission, team=self.team_a, goals=3, shots=10, possession=55
        )
        TeamMatchStats.objects.create(
            submission=submission, team=self.team_b, goals=2, shots=8, possession=45
        )
        ok, _ = approve_match_submission(submission, self.owner)
        self.assertTrue(ok)
        activity = self.client.get(reverse("live_activity"))
        self.assertContains(activity, "RESULT APPROVED")
        self.assertContains(activity, "ATX")
        self.assertContains(activity, "CTX")
        self.assertContains(activity, "mgl-activity-badges")
        news = self.client.get(reverse("news_centre"))
        self.assertContains(news, "mgl-activity-badges")
        self.assertContains(news, "ATX")

    def test_unpublished_news_is_not_live_activity(self):
        NewsPost.objects.create(
            category=NewsPost.TRANSFER,
            title="Secret Chelsea Test deal",
            body="Pending transfer involving Arsenal Test.",
            published=False,
        )
        page = self.client.get(reverse("live_activity"))
        self.assertNotContains(page, "Secret Chelsea Test deal")

    def test_history_page_is_structured_for_future_seasons(self):
        page = self.client.get(reverse("historical_tables"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "SEASON 1")
        self.assertContains(page, "SEASON 2")
        self.assertContains(page, "League Winner")
        self.assertContains(page, "Cup Winner")
        self.assertContains(page, "Manager of the Season")
        self.assertContains(page, "Team of the Season")
        self.assertContains(page, "Golden Boot")
        self.assertContains(page, "Top Assists")
        self.assertContains(page, "To be recorded")

    def test_activity_aliases_redirect(self):
        live = self.client.get("/mgl/live-activity/")
        self.assertEqual(live.status_code, 302)
        self.assertEqual(live["Location"], reverse("live_activity"))
        press = self.client.get("/mgl/pressroom/")
        self.assertEqual(press.status_code, 302)
        self.assertEqual(press["Location"], reverse("pressroom"))

    def test_manager_cannot_open_control_centre(self):
        self.client.login(username="kai", password="test-pass-123")
        response = self.client.get(reverse("control_centre"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("manager_hub"))

    def test_owner_sees_control_and_signed_in_nav(self):
        self.client.login(username="owner", password="test-pass-123")
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, "CONTROL")
        self.assertContains(home, reverse("control_centre"))
        self.assertContains(home, "MY CLUB")
        self.assertContains(home, "MARKET")
        self.assertContains(home, "COMMUNITY")
        self.assertContains(home, "NOTIFICATIONS")
        self.assertNotContains(home, reverse("unassigned_players"))
        control = self.client.get(reverse("control_centre"))
        self.assertEqual(control.status_code, 200)
