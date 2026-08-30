from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from auctions.models import PlayerAuction
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.admin import approve_match_submission
from mgl.market import (
    close_expired_auctions,
    create_manager_auction,
    create_transfer_offer,
    list_player_for_sale,
    place_auction_bid,
    settle_auction,
)
from mgl.models import (
    ApprovalStatus,
    ClubApplication,
    Fixture,
    ManagerNotification,
    MatchSubmission,
    PlayerListing,
    PressConference,
    TeamMatchStats,
)
from mgl.press import create_press_question
from mgl.standings import build_league_table
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


class ApprovalWorkflowAuditTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.owner = _user("owner", role=User.OWNER)
        self.admin = _user("siteadmin", role=User.ADMIN)
        self.user_a = _user("kai")
        self.user_b = _user("rival")
        self.user_c = _user("other")
        self.mgr_a = _manager(self.user_a)
        self.mgr_b = _manager(self.user_b)
        self.mgr_c = _manager(self.user_c)
        self.team_a = Team.objects.create(
            name="Arsenal Test", short_name="ATX", league=self.league, manager=self.user_a
        )
        self.team_b = Team.objects.create(
            name="Chelsea Test", short_name="CTX", league=self.league, manager=self.user_b
        )
        self.team_c = Team.objects.create(
            name="Spurs Test", short_name="STX", league=self.league, manager=self.user_c
        )
        self.home_st = Player.objects.create(
            name="Home Striker", position="ST", overall=80, mgl_team=self.team_a
        )
        self.away_st = Player.objects.create(
            name="Away Striker", position="ST", overall=78, mgl_team=self.team_b
        )
        self.player_b = Player.objects.create(
            name="Blue Midfielder", position="CM", overall=79, mgl_team=self.team_b
        )
        self.fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            matchweek=2,
            is_released=True,
            status="SCHEDULED",
        )

    def _submit_score(self, username="kai"):
        self.client.login(username=username, password="test-pass-123")
        return self.client.post(
            reverse("submit_match", args=[self.fixture.id]),
            {
                "home_goals": "2",
                "away_goals": "1",
                "home_goal_1": str(self.home_st.id),
                "home_goal_2": str(self.home_st.id),
                "away_goal_1": str(self.away_st.id),
                "home_shots": "8",
                "away_shots": "4",
                "home_possession": "55",
                "away_possession": "45",
                "home_yellow_cards": "0",
                "away_yellow_cards": "0",
                "home_red_cards": "0",
                "away_red_cards": "0",
            },
        )

    def _table_points(self, team):
        row = next(item for item in build_league_table(self.league) if item["team"].id == team.id)
        return row["played"], row["points"], row["wins"]

    def test_match_two_stage_updates_table_once(self):
        self._submit_score()
        submission = MatchSubmission.objects.get(fixture=self.fixture)
        self.assertEqual(submission.opponent_response, ApprovalStatus.PENDING)
        self.assertEqual(self._table_points(self.team_a), (0, 0, 0))
        self.assertFalse(
            ManagerNotification.objects.filter(
                recipient=self.owner,
                source_key=f"admin-result-{submission.pk}",
            ).exists()
        )

        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"score-submitted-{self.fixture.pk}",
        )
        self.client.login(username="rival", password="test-pass-123")
        inbox = self.client.get(reverse("manager_notifications"))
        self.assertContains(inbox, "2–1")
        self.assertContains(inbox, "Shots 8-4")
        self.assertContains(inbox, "ACCEPT")
        self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "accept"},
        )
        submission.refresh_from_db()
        self.assertEqual(submission.opponent_response, ApprovalStatus.APPROVED)
        self.assertEqual(submission.status, ApprovalStatus.PENDING)
        self.assertEqual(self._table_points(self.team_a), (0, 0, 0))

        admin_notice = ManagerNotification.objects.get(
            recipient=self.owner,
            source_key=f"admin-result-{submission.pk}",
        )
        self.assertEqual(admin_notice.response_status, ManagerNotification.PENDING)
        self.client.login(username="kai", password="test-pass-123")
        stolen = self.client.post(
            reverse("manager_notification_respond", args=[admin_notice.id]),
            {"action": "accept"},
        )
        self.assertEqual(stolen.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, ApprovalStatus.PENDING)

        self.client.login(username="owner", password="test-pass-123")
        control = self.client.get(reverse("control_centre"))
        self.assertContains(control, "Arsenal Test vs Chelsea Test")
        approved = self.client.post(reverse("control_approve_result", args=[submission.id]))
        self.assertEqual(approved.status_code, 302)
        submission.refresh_from_db()
        self.fixture.refresh_from_db()
        self.assertEqual(submission.status, ApprovalStatus.APPROVED)
        self.assertEqual(self.fixture.status, "COMPLETED")
        self.assertEqual(self._table_points(self.team_a), (1, 3, 1))
        again = self.client.post(reverse("control_approve_result", args=[submission.id]))
        self.assertEqual(again.status_code, 302)
        self.assertEqual(self._table_points(self.team_a), (1, 3, 1))
        self.home_st.refresh_from_db()
        self.assertEqual(self.home_st.goals, 2)

    def test_opponent_reject_blocks_admin_and_allows_resubmit(self):
        self._submit_score()
        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"score-submitted-{self.fixture.pk}",
        )
        self.client.login(username="rival", password="test-pass-123")
        self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "reject"},
        )
        first = MatchSubmission.objects.get(fixture=self.fixture)
        self.assertEqual(first.status, ApprovalStatus.REJECTED)
        self.assertFalse(
            ManagerNotification.objects.filter(
                recipient=self.owner,
                source_key=f"admin-result-{first.pk}",
            ).exists()
        )
        self.client.login(username="owner", password="test-pass-123")
        control = self.client.get(reverse("control_centre"))
        self.assertNotContains(control, reverse("control_approve_result", args=[first.id]))
        blocked = approve_match_submission(first, self.owner)
        self.assertFalse(blocked[0])

        submitter = ManagerNotification.objects.get(
            recipient=self.user_a,
            source_key=f"score-response-{first.pk}",
        )
        self.assertIn("rejected", submitter.message.lower())

        self.client.login(username="kai", password="test-pass-123")
        again = self._submit_score()
        self.assertEqual(again.status_code, 302)
        second = MatchSubmission.objects.get(fixture=self.fixture)
        self.assertEqual(second.status, ApprovalStatus.PENDING)
        self.assertEqual(second.opponent_response, ApprovalStatus.PENDING)
        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(self._table_points(self.team_a), (0, 0, 0))

    def test_transfer_two_stage_moves_player_once(self):
        listing = create_transfer_offer(self.player_b, self.mgr_a, "8.00")
        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"transfer-offer-{listing.pk}",
        )
        self.client.login(username="rival", password="test-pass-123")
        self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "accept"},
        )
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.PENDING)
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_b.mgl_team_id, self.team_b.id)
        admin_notice = ManagerNotification.objects.get(
            recipient=self.owner,
            source_key=f"admin-listing-{listing.pk}",
        )
        self.client.login(username="owner", password="test-pass-123")
        self.client.post(
            reverse("manager_notification_respond", args=[admin_notice.id]),
            {"action": "accept"},
        )
        listing.refresh_from_db()
        self.player_b.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.SOLD)
        self.assertEqual(self.player_b.mgl_team_id, self.team_a.id)
        self.assertEqual(Player.objects.filter(pk=self.player_b.id).count(), 1)
        self.client.post(
            reverse("manager_notification_respond", args=[admin_notice.id]),
            {"action": "accept"},
        )
        self.assertEqual(Player.objects.filter(mgl_team=self.team_a, pk=self.player_b.id).count(), 1)

    def test_transfer_reject_does_not_move_player(self):
        listing = create_transfer_offer(self.player_b, self.mgr_a, "6.00")
        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"transfer-offer-{listing.pk}",
        )
        self.client.login(username="rival", password="test-pass-123")
        self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "reject"},
        )
        listing.refresh_from_db()
        self.player_b.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.REJECTED)
        self.assertEqual(self.player_b.mgl_team_id, self.team_b.id)
        self.assertFalse(
            ManagerNotification.objects.filter(
                recipient=self.owner,
                source_key=f"admin-listing-{listing.pk}",
            ).exists()
        )

    def test_manager_cannot_approve_manager_or_job_or_press(self):
        applicant = _user("applicant")
        application = ManagerApplication.objects.create(
            user=applicant,
            display_name="Applicant",
            gamertag="APP",
            status=ManagerApplication.PENDING,
        )
        vacant = Team.objects.create(
            name="Vacant Test", short_name="VTX", league=self.league
        )
        job = ClubApplication.objects.create(
            manager=self.mgr_c,
            team=vacant,
            status=ApprovalStatus.PENDING,
        )
        press = create_press_question(
            manager=self.user_a,
            team=self.team_a,
            question="What changed the game?",
            question_key="win_key",
            category="win",
            trigger=PressConference.MATCH,
        )
        press.answer = "The first goal."
        press.save(update_fields=["answer"])
        self.client.login(username="kai", password="test-pass-123")
        for url in (
            reverse("control_approve_manager", args=[application.id]),
            reverse("control_approve_job", args=[job.id]),
            reverse("control_approve_press", args=[press.id]),
            reverse("control_centre"),
        ):
            response = self.client.post(url) if "approve" in url or "reject" in url else self.client.get(url)
            if url == reverse("control_centre"):
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], reverse("manager_hub"))
            else:
                self.assertEqual(response.status_code, 302)
        application.refresh_from_db()
        job.refresh_from_db()
        press.refresh_from_db()
        self.assertEqual(application.status, ManagerApplication.PENDING)
        self.assertEqual(job.status, ApprovalStatus.PENDING)
        self.assertEqual(press.status, ApprovalStatus.PENDING)
        self.assertIsNone(vacant.manager_id)

        self.client.login(username="owner", password="test-pass-123")
        control = self.client.get(reverse("control_centre"))
        self.assertContains(control, "Applicant")
        self.assertContains(control, "Vacant Test")
        self.assertContains(control, "What changed the game?")

    def test_sale_listing_is_live_without_admin(self):
        listing = list_player_for_sale(self.player_b, self.mgr_b, "5.00")
        self.assertEqual(listing.status, PlayerListing.LIVE)
        self.client.login(username="kai", password="test-pass-123")
        market = self.client.get(reverse("transfer_market"))
        self.assertContains(market, "Blue Midfielder")
        self.assertContains(market, reverse("purchase_listing", args=[listing.id]))
        self.assertNotContains(market, reverse("buy_player", args=[listing.id]))
        self.assertNotContains(market, ">OFFER</button>")
        self.client.login(username="owner", password="test-pass-123")
        inbox = self.client.get(reverse("manager_notifications"))
        self.assertNotContains(inbox, f"admin-listing-{listing.pk}")

    def test_auction_sell_and_unsold_return(self):
        auction = create_manager_auction(self.player_b, self.mgr_b, 30, starting_bid=1)
        self.player_b.refresh_from_db()
        self.assertIsNone(self.player_b.mgl_team_id)
        self.client.login(username="rival", password="test-pass-123")
        squad = self.client.get(reverse("team_management"))
        self.assertNotContains(squad, "BLUE MIDFIELDER")
        place_auction_bid(auction, self.mgr_a, 3)
        settle_auction(auction)
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_b.mgl_team_id, self.team_a.id)

        extra = Player.objects.create(
            name="Return Winger", position="LW", overall=70, mgl_team=self.team_a
        )
        unsold = create_manager_auction(extra, self.mgr_a, 30, starting_bid=0)
        extra.refresh_from_db()
        self.assertIsNone(extra.mgl_team_id)
        from django.utils import timezone
        from datetime import timedelta

        unsold.ends_at = timezone.now() - timedelta(minutes=1)
        unsold.save(update_fields=["ends_at"])
        close_expired_auctions()
        extra.refresh_from_db()
        unsold.refresh_from_db()
        self.assertEqual(extra.mgl_team_id, self.team_a.id)
        self.assertEqual(unsold.status, PlayerAuction.ENDED)
        self.assertIsNone(unsold.winning_manager_id)

    def test_manager_cannot_approve_own_or_unrelated_match(self):
        self._submit_score()
        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"score-submitted-{self.fixture.pk}",
        )
        self.client.login(username="kai", password="test-pass-123")
        own = self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "accept"},
        )
        self.assertEqual(own.status_code, 302)
        submission = MatchSubmission.objects.get(fixture=self.fixture)
        self.assertEqual(submission.opponent_response, ApprovalStatus.PENDING)

        self.client.login(username="other", password="test-pass-123")
        unrelated = self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "accept"},
        )
        self.assertEqual(unrelated.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.opponent_response, ApprovalStatus.PENDING)

    def test_public_pages_and_owner_control_still_work(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        club = self.client.get(reverse("club_page", args=[self.team_a.short_name]))
        self.assertEqual(club.status_code, 200)
        self.assertContains(club, "HOME STRIKER")
        self.client.login(username="owner", password="test-pass-123")
        control = self.client.get(reverse("control_centre"))
        self.assertEqual(control.status_code, 200)
        self.assertContains(control, "OWNER / ADMIN CONTROL")
        self.assertContains(control, "MATCH RESULTS")
        self.assertContains(control, "TRANSFER REQUESTS")
