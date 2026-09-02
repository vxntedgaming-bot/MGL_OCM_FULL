from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.admin import approve_match_submission
from mgl.market import approve_listing, create_transfer_offer, respond_to_transfer_offer
from mgl.models import (
    ApprovalStatus,
    Fixture,
    ManagerNotification,
    MatchSubmission,
    PlayerListing,
)
from mgl.notifications import inbox_queryset_for_user, unread_count_for_user
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


class InboxActionWorkflowTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.owner = _user("owner", role=User.OWNER)
        self.user_a = _user("kai")
        self.user_b = _user("rival")
        self.mgr_a = _manager(self.user_a, "20.00")
        self.mgr_b = _manager(self.user_b, "20.00")
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
        self.player_b = Player.objects.create(
            name="Blue Midfielder",
            position="CM",
            overall=80,
            mgl_team=self.team_b,
            is_free_agent=False,
        )
        self.home_st = Player.objects.create(
            name="Home Striker",
            position="ST",
            overall=81,
            mgl_team=self.team_a,
            is_free_agent=False,
        )
        self.away_st = Player.objects.create(
            name="Away Striker",
            position="ST",
            overall=79,
            mgl_team=self.team_b,
            is_free_agent=False,
        )
        self.fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            matchweek=3,
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

    def test_opponent_receives_match_card_and_submitter_does_not(self):
        response = self._submit_score()
        self.assertEqual(response.status_code, 302)
        submission = MatchSubmission.objects.get(fixture=self.fixture)
        self.assertEqual(submission.status, ApprovalStatus.PENDING)
        self.assertEqual(self.fixture.status, "SCHEDULED")

        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"score-submitted-{self.fixture.pk}",
        )
        self.assertEqual(notice.response_status, ManagerNotification.PENDING)
        self.assertIn("2–1", notice.details.get("scoreline", ""))
        self.assertFalse(
            inbox_queryset_for_user(self.user_a)
            .filter(source_key=f"score-submitted-{self.fixture.pk}")
            .exists()
        )

        self.client.login(username="rival", password="test-pass-123")
        inbox = self.client.get(reverse("manager_notifications"))
        self.assertEqual(inbox.status_code, 200)
        self.assertContains(inbox, "core/css/ufl.css")
        self.assertContains(inbox, "mgl-ncard")
        self.assertContains(inbox, "Match Result Submitted")
        self.assertContains(inbox, "Arsenal Test vs Chelsea Test")
        self.assertContains(inbox, "Arsenal Test has submitted a match result involving your team.")
        self.assertContains(inbox, "2–1")
        self.assertContains(inbox, "ACCEPT")
        self.assertContains(inbox, "REJECT")
        self.assertContains(inbox, "PENDING")
        self.assertNotContains(inbox, "CHELSEA ONLY")

        self.client.login(username="kai", password="test-pass-123")
        submitter_inbox = self.client.get(reverse("manager_notifications"))
        self.assertNotContains(submitter_inbox, "Match Result Submitted")
        self.assertNotContains(
            submitter_inbox,
            reverse("manager_notification_respond", args=[notice.id]),
        )

    def test_match_accept_does_not_approve_result_and_blocks_duplicates(self):
        self._submit_score()
        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"score-submitted-{self.fixture.pk}",
        )
        url = reverse("manager_notification_respond", args=[notice.id])
        self.client.login(username="rival", password="test-pass-123")
        accepted = self.client.post(url, {"action": "accept"})
        self.assertEqual(accepted.status_code, 302)

        notice.refresh_from_db()
        submission = MatchSubmission.objects.get(fixture=self.fixture)
        self.fixture.refresh_from_db()
        self.assertEqual(notice.response_status, ManagerNotification.ACCEPTED)
        self.assertEqual(submission.opponent_response, ApprovalStatus.APPROVED)
        self.assertEqual(submission.status, ApprovalStatus.PENDING)
        self.assertEqual(self.fixture.status, "SCHEDULED")

        inbox = self.client.get(reverse("manager_notifications"))
        self.assertContains(inbox, "ACCEPTED")
        self.assertNotContains(inbox, ">ACCEPT</button>")
        self.assertNotContains(inbox, ">REJECT</button>")

        again = self.client.post(url, {"action": "accept"})
        self.assertEqual(again.status_code, 302)
        notice.refresh_from_db()
        self.assertEqual(notice.response_status, ManagerNotification.ACCEPTED)
        self.assertEqual(
            ManagerNotification.objects.filter(
                recipient=self.user_b,
                source_key=f"score-submitted-{self.fixture.pk}",
            ).count(),
            1,
        )

        ok, _ = approve_match_submission(submission, self.owner)
        self.assertTrue(ok)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.status, "COMPLETED")

    def test_manager_cannot_action_another_managers_notification(self):
        self._submit_score()
        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"score-submitted-{self.fixture.pk}",
        )
        self.client.login(username="kai", password="test-pass-123")
        stolen = self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "accept"},
        )
        self.assertEqual(stolen.status_code, 302)
        notice.refresh_from_db()
        self.assertEqual(notice.response_status, ManagerNotification.PENDING)
        submission = MatchSubmission.objects.get(fixture=self.fixture)
        self.assertEqual(submission.opponent_response, ApprovalStatus.PENDING)

    def test_transfer_request_notifies_current_club_and_respects_admin(self):
        self.client.login(username="kai", password="test-pass-123")
        profile = self.client.get(reverse("player_profile", args=[self.player_b.id]))
        self.assertContains(profile, "BUY")
        posted = self.client.post(
            reverse("request_player_transfer", args=[self.player_b.id]),
            {"asking_price": "8.00"},
        )
        self.assertEqual(posted.status_code, 302)
        listing = PlayerListing.objects.get(player=self.player_b, status=PlayerListing.OFFER)
        self.assertEqual(listing.reserved_buyer_id, self.mgr_a.id)
        self.assertEqual(listing.asking_price, Decimal("8.00"))
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_b.mgl_team_id, self.team_b.id)

        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"transfer-offer-{listing.pk}",
        )
        self.assertFalse(
            inbox_queryset_for_user(self.user_a)
            .filter(source_key=f"transfer-offer-{listing.pk}")
            .exists()
        )
        self.client.login(username="rival", password="test-pass-123")
        inbox = self.client.get(reverse("manager_notifications"))
        self.assertContains(inbox, "Transfer Request")
        self.assertContains(inbox, "Blue Midfielder")
        self.assertContains(inbox, "Arsenal Test has submitted a transfer request")
        self.assertContains(inbox, "8.00")
        self.assertContains(inbox, "ACCEPT")
        self.assertContains(inbox, "REJECT")
        self.assertNotContains(inbox, "REVIEW REQUEST")

        accepted = self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "accept"},
        )
        self.assertEqual(accepted.status_code, 302)
        listing.refresh_from_db()
        notice.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.PENDING)
        self.assertEqual(notice.response_status, ManagerNotification.ACCEPTED)
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_b.mgl_team_id, self.team_b.id)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("20.00"))

        inbox = self.client.get(reverse("manager_notifications"))
        self.assertContains(inbox, "ACCEPTED")
        self.assertNotContains(inbox, ">ACCEPT</button>")

        approved = approve_listing(listing, self.owner)
        self.assertEqual(approved.status, PlayerListing.SOLD)
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_b.mgl_team_id, self.team_a.id)
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("12.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("28.00"))

    def test_transfer_reject_keeps_player_and_disables_buttons(self):
        listing = create_transfer_offer(self.player_b, self.mgr_a, "6.00")
        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"transfer-offer-{listing.pk}",
        )
        self.client.login(username="rival", password="test-pass-123")
        rejected = self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "reject"},
        )
        self.assertEqual(rejected.status_code, 302)
        listing.refresh_from_db()
        notice.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.REJECTED)
        self.assertEqual(notice.response_status, ManagerNotification.REJECTED)
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_b.mgl_team_id, self.team_b.id)
        inbox = self.client.get(reverse("manager_notifications"))
        self.assertContains(inbox, "REJECTED")
        self.assertNotContains(inbox, ">ACCEPT</button>")

    def test_cannot_buy_own_player_or_overspend_or_bypass_window(self):
        own = Player.objects.create(
            name="Home Forward",
            position="ST",
            overall=79,
            mgl_team=self.team_a,
            is_free_agent=False,
        )
        self.client.login(username="kai", password="test-pass-123")
        own_page = self.client.get(reverse("player_profile", args=[own.id]))
        self.assertNotContains(own_page, 'name="asking_price"')
        own_post = self.client.post(
            reverse("request_player_transfer", args=[own.id]),
            {"asking_price": "4.00"},
        )
        self.assertEqual(own_post.status_code, 302)
        self.assertFalse(PlayerListing.objects.filter(player=own).exists())

        expensive = self.client.post(
            reverse("request_player_transfer", args=[self.player_b.id]),
            {"asking_price": "50.00"},
        )
        self.assertEqual(expensive.status_code, 302)
        self.assertFalse(
            PlayerListing.objects.filter(player=self.player_b).exists()
        )

        with patch("mgl.market.transfer_window_is_open", return_value=False):
            closed = self.client.post(
                reverse("request_player_transfer", args=[self.player_b.id]),
                {"asking_price": "4.00"},
            )
        self.assertEqual(closed.status_code, 302)
        self.assertFalse(
            PlayerListing.objects.filter(player=self.player_b).exists()
        )

    def test_owner_control_and_public_pages_still_work(self):
        listing = create_transfer_offer(self.player_b, self.mgr_a, "5.00")
        listing.status = PlayerListing.PENDING
        listing.save(update_fields=["status"])
        self.client.login(username="owner", password="test-pass-123")
        control = self.client.get(reverse("control_centre"))
        self.assertEqual(control.status_code, 200)
        self.assertContains(control, "Blue Midfielder")
        self.assertContains(control, "BUYER Kai")
        self.assertContains(control, "SELLER RECEIVES")

        self.client.logout()
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        club = self.client.get(reverse("club_page", args=[self.team_b.short_name]))
        self.assertEqual(club.status_code, 200)
        self.assertContains(club, "BLUE MIDFIELDER")
        self.assertNotContains(club, ">BUY</a>")
        public_player = self.client.get(reverse("player_profile", args=[self.player_b.id]))
        self.assertEqual(public_player.status_code, 200)
        self.assertNotContains(public_player, 'name="asking_price"')

    def test_unread_count_includes_new_action_and_drops_after_handle(self):
        self._submit_score()
        self.assertEqual(unread_count_for_user(self.user_b), 1)
        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"score-submitted-{self.fixture.pk}",
        )
        self.client.login(username="rival", password="test-pass-123")
        self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "reject"},
        )
        self.assertEqual(unread_count_for_user(self.user_b), 0)
        notice.refresh_from_db()
        self.assertEqual(notice.response_status, ManagerNotification.REJECTED)
        self.assertIsNotNone(notice.actioned_at)

    def test_sale_listing_goes_live_without_admin(self):
        from mgl.market import list_player_for_sale

        listing = list_player_for_sale(self.player_b, self.mgr_b, "7.00")
        self.assertEqual(listing.status, PlayerListing.LIVE)
        self.assertFalse(
            ManagerNotification.objects.filter(
                source_key=f"admin-listing-{listing.pk}"
            ).exists()
        )
        self.client.login(username="kai", password="test-pass-123")
        market = self.client.get(reverse("transfer_market"))
        self.assertContains(market, "Blue Midfielder")
        self.assertContains(market, "7.00")
        self.assertContains(market, "Chelsea Test")
        self.assertContains(market, reverse("purchase_listing", args=[listing.id]))
        self.assertNotContains(market, reverse("buy_player", args=[listing.id]))
        self.assertNotContains(market, "NO PLAYERS LISTED")

        self.client.login(username="owner", password="test-pass-123")
        inbox = self.client.get(reverse("manager_notifications"))
        self.assertNotContains(inbox, "PLAYER LISTED FOR SALE")

    def test_owner_inbox_reject_keeps_transfer_request_off_squad(self):
        listing = create_transfer_offer(self.player_b, self.mgr_a, "4.00")
        respond_to_transfer_offer(listing, self.user_b, True)
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.PENDING)
        notice = ManagerNotification.objects.get(
            recipient=self.owner,
            source_key=f"admin-listing-{listing.pk}",
        )
        self.client.login(username="owner", password="test-pass-123")
        self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "reject"},
        )
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.REJECTED)
        self.player_b.refresh_from_db()
        self.assertEqual(self.player_b.mgl_team_id, self.team_b.id)
        market = self.client.get(reverse("transfer_market"))
        self.assertNotContains(market, reverse("buy_player", args=[listing.id]))
