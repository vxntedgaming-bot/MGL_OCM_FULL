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
from mgl.activity import activity_payloads, teams_for_post
from mgl.models import ManagerNotification
from mgl.notifications import (
    NotificationItem,
    inbox_for_user,
    inbox_queryset_for_user,
    notifications_for_user,
    notify_user,
    unread_count_for_user,
)
from mgl.press import approve_press_conference, create_press_question, publish_press_answer
from mgl.services import create_news
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
        self.assertNotContains(home, "Recruitment Drive")
        self.assertNotContains(home, "MY TEAM")
        self.assertNotContains(home, "MY CLUB")
        self.assertContains(home, "JOBS")
        self.assertContains(home, "LOGIN")
        self.assertNotContains(home, "YOUR APPLICATIONS")
        self.assertNotContains(home, ">STATUS</h2>")

    def test_press_creates_one_notification_and_answer_publishes(self):
        press = create_press_question(
            manager=self.user_a,
            team=self.team_a,
            question="How pleased were you with the performance?",
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
        self.assertContains(hub, reverse("manager_notifications"))
        self.assertContains(hub, "data-notify-dropdown")
        self.assertContains(hub, "mgl-notify-count")
        self.assertNotContains(hub, "1 Notification")
        self.assertNotContains(hub, "ACTION REQUIRED")
        self.assertNotContains(hub, "PENDING ACTIONS")
        inbox = self.client.get(reverse("manager_notifications"))
        self.assertContains(inbox, "PRESS CONFERENCE")
        self.assertContains(inbox, "PRESS CONFERENCE QUESTION")
        self.assertContains(inbox, "mgl-press-brief")
        self.assertContains(inbox, "mgl-press-brief.css")
        self.assertContains(inbox, "KAI")
        self.assertContains(inbox, "ARSENAL TEST")
        self.assertContains(inbox, "How pleased were you with the performance?")
        self.assertContains(inbox, "Sky Sports")
        self.assertContains(inbox, "ANSWER NOW")
        self.assertContains(inbox, reverse("answer_press", args=[press.pk]))
        self.assertContains(inbox, "mgl-team-logo")

        page = self.client.get(reverse("answer_press", args=[press.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "ANSWER PRESS QUESTION")
        self.assertContains(page, "How pleased were you with the performance?")

        posted = self.client.post(
            reverse("answer_press", args=[press.pk]),
            {"answer": "We controlled the game from the start."},
        )
        self.assertEqual(posted.status_code, 302)
        self.assertEqual(posted["Location"], reverse("pressroom"))

        press.refresh_from_db()
        self.assertEqual(press.status, ApprovalStatus.PENDING)
        self.assertEqual(press.answer, "We controlled the game from the start.")
        remaining = [
            row for row in notifications_for_user(self.user_a) if row["key"].startswith("press-")
        ]
        self.assertEqual(remaining, [])
        after = self.client.get(reverse("manager_notifications"))
        self.assertNotContains(after, "ANSWER NOW")
        self.assertNotContains(after, reverse("answer_press", args=[press.pk]))
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("20.50"))
        reward_notes = inbox_queryset_for_user(self.user_a).filter(
            source_key=f"press-reward-{press.pk}"
        )
        self.assertEqual(reward_notes.count(), 1)
        self.client.post(reverse("notification_mark_all_read"))
        self.assertEqual(unread_count_for_user(self.user_a), 0)

        pending_room = self.client.get(reverse("pressroom"))
        self.assertNotContains(pending_room, "We controlled the game from the start.")
        self.assertFalse(NewsPost.objects.filter(category=NewsPost.PRESS).exists())
        pending_activity = self.client.get(reverse("live_activity"))
        self.assertContains(pending_activity, "No league activity yet.")
        self.assertNotContains(pending_activity, "We controlled the game from the start.")

        self.client.logout()
        self.client.login(username="owner", password="test-pass-123")
        approved = self.client.post(reverse("control_approve_press", args=[press.pk]))
        self.assertEqual(approved.status_code, 302)
        press.refresh_from_db()
        self.assertEqual(press.status, ApprovalStatus.APPROVED)

        self.client.logout()
        room = self.client.get(reverse("pressroom"))
        self.assertContains(room, "mgl-press-story")
        self.assertContains(room, "mgl-press-story.css")
        self.assertContains(room, "mgl-pressroom.css")
        self.assertContains(room, "ARSENAL TEST")
        self.assertContains(room, "KAI")
        self.assertNotContains(room, "Manager: Kai")
        self.assertContains(room, "How pleased were you with the performance?")
        self.assertContains(room, "We controlled the game from the start.")
        self.assertContains(room, "PRESS CONFERENCE")
        self.assertContains(room, "Read full response")
        self.assertContains(room, f"#press-{press.pk}-answer")
        self.assertNotContains(room, "YOUR QUESTIONS")
        self.assertNotContains(room, "<span>Q:</span>")
        self.assertNotContains(room, "<span>A:</span>")
        self.assertNotContains(room, "Latest News")
        self.assertNotContains(room, "Official News")

        self.assertTrue(
            NewsPost.objects.filter(category=NewsPost.PRESS, published=True).exists()
        )
        activity = self.client.get(reverse("live_activity"))
        self.assertNotContains(activity, "PRESS CONFERENCE")
        self.assertNotContains(activity, "We controlled the game from the start.")
        news = NewsPost.objects.get(category=NewsPost.PRESS)
        self.assertEqual(news.primary_team_id, self.team_a.id)
        payload = activity_payloads([news])[0]
        self.assertEqual([row.pk for row in payload["teams"]], [self.team_a.id])

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
            opponent_response=ApprovalStatus.APPROVED,
        )
        TeamMatchStats.objects.create(
            submission=submission, team=self.team_a, goals=3, shots=10, possession=55
        )
        TeamMatchStats.objects.create(
            submission=submission, team=self.team_b, goals=2, shots=8, possession=45
        )
        ok, _ = approve_match_submission(submission, self.owner)
        self.assertTrue(ok)
        news = NewsPost.objects.get(category=NewsPost.RESULTS)
        self.assertEqual(news.primary_team_id, self.team_a.id)
        self.assertEqual(news.secondary_team_id, self.team_b.id)
        payload = activity_payloads([news])[0]
        self.assertEqual(
            [row.pk for row in payload["teams"]],
            [self.team_a.id, self.team_b.id],
        )
        activity = self.client.get(reverse("live_activity"))
        self.assertContains(activity, "RESULT")
        self.assertContains(activity, "Arsenal Test")
        self.assertContains(activity, "Chelsea Test")
        self.assertContains(activity, "mgl-activity-card")
        self.assertContains(activity, "mgl-activity-feed.css")
        news = self.client.get(reverse("news_centre"), follow=True)
        self.assertContains(news, "mgl-activity-card")
        self.assertContains(news, "Arsenal Test")

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
        self.assertContains(page, "HISTORY")
        self.assertContains(page, "A record of every season in Ultimate Fantasy League.")
        self.assertContains(page, "LEAGUE WINNER")
        self.assertContains(page, "CUP WINNER")
        self.assertContains(page, "MANAGER OF THE SEASON")
        self.assertContains(page, "TEAM OF THE SEASON")
        self.assertContains(page, "Golden Boot")
        self.assertContains(page, "TOP ASSISTS")
        self.assertContains(page, "To be recorded")
        self.assertContains(page, "CURRENT TABLE")
        self.assertNotContains(page, "SEASON 2")

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
        self.assertContains(home, "TABLES")
        self.assertContains(home, "STATISTICS")
        self.assertContains(home, reverse("leagues_page"))
        self.assertContains(home, reverse("league_stats", kwargs={"slug": "premier-league"}))
        self.assertContains(home, "ACCOUNT")
        self.assertContains(home, "data-notify-dropdown")
        self.assertNotContains(home, "ACTION REQUIRED")
        self.assertNotContains(home, reverse("unassigned_players"))
        control = self.client.get(reverse("control_centre"))
        self.assertEqual(control.status_code, 200)

    def test_linked_team_badges_ignore_unrelated_names_in_copy(self):
        post = create_news(
            NewsPost.RESULTS,
            "Final whistle",
            "Result approved without naming either club.",
            team=self.team_a,
            secondary_team=self.team_b,
        )
        teams = teams_for_post(post)
        self.assertEqual([row.pk for row in teams], [self.team_a.id, self.team_b.id])

    def test_transfer_news_uses_actual_clubs(self):
        post = create_news(
            NewsPost.TRANSFER,
            "Player moved clubs",
            "Transfer completed.",
            team=self.team_b,
            secondary_team=self.team_a,
        )
        self.assertEqual(post.primary_team_id, self.team_b.id)
        self.assertEqual(post.secondary_team_id, self.team_a.id)
        self.assertEqual(
            [row.pk for row in teams_for_post(post)],
            [self.team_b.id, self.team_a.id],
        )

    def test_legacy_news_falls_back_to_team_name_matching(self):
        post = NewsPost.objects.create(
            category=NewsPost.TRANSFER,
            title="Arsenal Test signed a player from Chelsea Test",
            body="Completed.",
            published=True,
        )
        self.assertIsNone(post.primary_team_id)
        names = {row.name for row in teams_for_post(post)}
        self.assertEqual(names, {"Arsenal Test", "Chelsea Test"})

    def test_press_related_row_supplies_badge_without_stored_fk(self):
        press = create_press_question(
            manager=self.user_a,
            team=self.team_a,
            question="What was the turning point?",
            question_key="win_key",
            category="win",
            trigger=PressConference.MATCH,
        )
        publish_press_answer(press, "The first goal.")
        approve_press_conference(press)
        NewsPost.objects.filter(category=NewsPost.PRESS).update(
            primary_team=None, secondary_team=None
        )
        legacy = NewsPost.objects.get(category=NewsPost.PRESS)
        legacy.refresh_from_db()
        self.assertIsNone(legacy.primary_team_id)
        teams = teams_for_post(legacy)
        self.assertEqual([row.pk for row in teams], [self.team_a.id])

    def test_notification_items_expose_extensible_fields(self):
        create_press_question(
            manager=self.user_a,
            team=self.team_a,
            question="Any late thoughts?",
            question_key="pm_late",
            category="performance",
            trigger=PressConference.MATCH,
        )
        row = notifications_for_user(self.user_a)[0]
        for field in ("key", "type", "title", "description", "url", "complete"):
            self.assertIn(field, row)
        self.assertFalse(row["complete"])
        item = NotificationItem(
            key="future-offer-1",
            type="TRANSFER OFFER",
            title="TRANSFER OFFER",
            description="Placeholder for a future offer model.",
            url="/market/",
            cta="VIEW OFFER",
        )
        self.assertFalse(item.complete)
        self.assertEqual(item.as_template()["key"], "future-offer-1")

    def test_hub_notification_button_uses_unread_count_and_own_inbox(self):
        create_press_question(
            manager=self.user_a,
            team=self.team_a,
            question="How pleased were you with the performance?",
            question_key="perf_hub",
            category="performance",
            trigger=PressConference.MATCH,
        )
        notify_user(
            self.user_b,
            source_key="admin-message-b",
            notification_type="ADMIN",
            title="CHELSEA ONLY",
            message="This belongs to the Chelsea manager.",
            actor="UFL Admin",
        )
        self.client.login(username="kai", password="test-pass-123")
        hub = self.client.get(reverse("manager_hub"))
        self.assertContains(hub, reverse("manager_notifications"))
        self.assertContains(hub, "data-notify-dropdown")
        self.assertContains(hub, "mgl-notify-count")
        self.assertContains(hub, f'href="{reverse("manager_profile")}"')
        self.assertContains(hub, "RESIGN")
        self.assertNotContains(hub, "Club Profile")

        inbox = self.client.get(reverse("manager_notifications"))
        self.assertEqual(inbox.status_code, 200)
        self.assertContains(inbox, "PRESS CONFERENCE")
        self.assertContains(inbox, "Sky Sports")
        self.assertNotContains(inbox, "CHELSEA ONLY")
        self.assertFalse(
            inbox_queryset_for_user(self.user_a)
            .filter(source_key="admin-message-b")
            .exists()
        )
        self.assertEqual(
            list(
                inbox_queryset_for_user(self.user_a).values_list(
                    "recipient_id", flat=True
                )
            ),
            [self.user_a.id]
            * inbox_queryset_for_user(self.user_a).count(),
        )

        self.client.post(reverse("notification_mark_all_read"))
        hub_after = self.client.get(reverse("manager_hub"))
        self.assertContains(hub_after, "Notifications")
        self.assertNotContains(hub_after, 'class="mgl-notify-count"')
        self.assertEqual(unread_count_for_user(self.user_a), 0)
        self.assertEqual(unread_count_for_user(self.user_b), 1)

    def test_press_brief_does_not_restyle_other_notifications(self):
        notify_user(
            self.user_a,
            source_key="admin-message-plain",
            notification_type="ADMIN",
            title="OWNER DECISION",
            message="Your listing needs a review.",
            actor="UFL Admin",
        )
        self.client.login(username="kai", password="test-pass-123")
        inbox = self.client.get(reverse("manager_notifications"))
        self.assertContains(inbox, "OWNER DECISION")
        self.assertContains(inbox, "mgl-notify-item")
        self.assertNotContains(inbox, 'class="mgl-press-brief"')
        self.assertNotContains(inbox, "PRESS CONFERENCE QUESTION")

    def test_manager_cannot_answer_another_managers_press(self):
        press = create_press_question(
            manager=self.user_a,
            team=self.team_a,
            question="Was that the turning point?",
            question_key="win_secret",
            category="win",
            trigger=PressConference.MATCH,
        )
        self.client.login(username="rival", password="test-pass-123")
        forbidden = self.client.get(reverse("answer_press", args=[press.pk]))
        self.assertEqual(forbidden.status_code, 404)
        posted = self.client.post(
            reverse("answer_press", args=[press.pk]),
            {"answer": "I should not be able to answer this."},
        )
        self.assertEqual(posted.status_code, 404)
        press.refresh_from_db()
        self.assertEqual(press.status, ApprovalStatus.PENDING)
        self.assertEqual(press.answer, "")

    def test_manager_cannot_open_another_managers_notifications(self):
        notify_user(
            self.user_a,
            source_key="admin-message-a",
            notification_type="ADMIN",
            title="ARSENAL ONLY",
            message="This belongs to the Arsenal manager.",
            actor="UFL Admin",
        )
        notify_user(
            self.user_b,
            source_key="admin-message-b2",
            notification_type="ADMIN",
            title="CHELSEA ONLY",
            message="This belongs to the Chelsea manager.",
            actor="UFL Admin",
        )
        self.client.login(username="rival", password="test-pass-123")
        page = self.client.get(reverse("manager_notifications"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "CHELSEA ONLY")
        self.assertNotContains(page, "ARSENAL ONLY")
        guessed = self.client.get("/mgl/notifications/%s/" % self.user_a.id)
        self.assertEqual(guessed.status_code, 404)
        self.assertEqual(
            set(inbox_queryset_for_user(self.user_b).values_list("recipient_id", flat=True)),
            {self.user_b.id},
        )

    def test_anonymous_users_cannot_open_notifications(self):
        response = self.client.get(reverse("manager_notifications"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_unread_count_uses_persisted_rows_not_a_hardcoded_one(self):
        self.assertEqual(unread_count_for_user(self.user_a), 0)
        for index in range(5):
            notify_user(
                self.user_a,
                source_key=f"admin-batch-{index}",
                notification_type="ADMIN",
                title=f"UPDATE {index}",
                message="Owner decision for your club.",
                actor="UFL Owner",
                team=self.team_a,
            )
        self.assertEqual(unread_count_for_user(self.user_a), 5)
        self.client.login(username="kai", password="test-pass-123")
        hub = self.client.get(reverse("manager_hub"))
        self.assertContains(hub, "mgl-notify-count")
        self.assertContains(hub, ">5</span>")
        inbox_for_user(self.user_a)
        ManagerNotification.objects.filter(
            recipient=self.user_a, source_key="admin-batch-0"
        ).update(read_at=None)
        self.client.post(reverse("notification_mark_all_read"))
        self.assertEqual(unread_count_for_user(self.user_a), 0)

    def test_duplicate_notification_keys_are_not_repeated(self):
        press = create_press_question(
            manager=self.user_a,
            team=self.team_a,
            question="How did the team recover?",
            question_key="loss_recover",
            category="loss",
            trigger=PressConference.MATCH,
        )
        notes = notifications_for_user(self.user_a)
        keys = [row["key"] for row in notes]
        self.assertEqual(keys.count(f"press-{press.pk}"), 1)
        self.assertEqual(len(keys), len(set(keys)))
