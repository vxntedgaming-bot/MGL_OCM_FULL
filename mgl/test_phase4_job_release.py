from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from auctions.models import PlayerAuction
from leagues.models import League
from managers.models import ManagerApplication
from mgl.job_applications import (
    GAMES_PER_WEEK_CHOICES,
    approve_job_application,
    parse_club_application,
    reject_job_application,
    submit_job_application,
)
from mgl.market import (
    close_expired_auctions,
    create_free_agent_auction,
    create_manager_auction,
    list_player_for_sale,
    place_auction_bid,
    settle_auction,
)
from mgl.models import ApprovalStatus, ClubApplication, PlayerListing, PlayerReleaseRequest
from mgl.player_state import (
    CLUB_OWNED,
    TEMPORARILY_LISTED,
    UNSIGNED,
    UFL_FREE_AGENT,
    enter_ufl_free_agency,
    free_agents,
    is_ufl_free_agent,
    ufl_player_status,
)
from mgl.recruitment import choose_recruitment_player, open_recruitment_pack
from mgl.scouting import choose_scout_player, complete_ready_assignments, dispatch_scout
from mgl.services import request_player_release, sign_free_agent
from mgl.tokens import MANAGER_AUCTION_LISTING_FEE
from players.models import Player
from teams.models import Team


JOB_APPLY = {
    "gamertag": "EAIDPHASE4",
    "discord_username": "phase4user",
    "games_per_week": "3-5",
    "referred_by": "A Friend",
    "new_gen_confirmed": "on",
}


def _user(username, role=User.MANAGER, **kwargs):
    return User.objects.create_user(
        username=username,
        password="test-pass-123",
        role=role,
        **kwargs,
    )


def _identity(user, status=ManagerApplication.PENDING, tokens="20.00"):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=status,
        tokens=Decimal(tokens),
    )


def _league():
    return League.objects.create(name="Phase Four League", short_name="P4L", season="1")


def _club(league, name, short, manager=None):
    return Team.objects.create(
        name=name,
        short_name=short,
        league=league,
        manager=manager,
    )


def _player(**kwargs):
    defaults = {
        "name": "Phase Player",
        "position": "ST",
        "overall": 68,
        "is_free_agent": False,
        "mgl_team": None,
        "released_at": None,
    }
    defaults.update(kwargs)
    return Player.objects.create(**defaults)


class JobApplicationFieldTests(TestCase):
    def test_games_per_week_choices_are_locked(self):
        self.assertEqual(GAMES_PER_WEEK_CHOICES, ("1-3", "3-5", "6+"))

    def test_parse_requires_locked_fields(self):
        empty = parse_club_application({})
        self.assertTrue(empty["errors"])
        bad_games = parse_club_application(
            {
                "gamertag": "EA",
                "discord_username": "disc",
                "games_per_week": "3",
                "new_gen_confirmed": "on",
            }
        )
        self.assertIn("Games per week must be 1–3, 3–5, or 6+.", bad_games["errors"])
        no_box = parse_club_application(
            {
                "gamertag": "EA",
                "discord_username": "disc",
                "games_per_week": "1-3",
            }
        )
        self.assertIn("New gen confirmation is required.", no_box["errors"])
        no_discord = parse_club_application(
            {
                "gamertag": "EA",
                "discord_id": "123456789",
                "games_per_week": "6+",
                "new_gen_confirmed": "on",
            }
        )
        self.assertIn("Discord username is required.", no_discord["errors"])
        ok = parse_club_application(JOB_APPLY)
        self.assertEqual(ok["errors"], [])
        self.assertEqual(ok["discord_username"], "phase4user")
        self.assertEqual(ok["games_per_week"], "3-5")


class JobApplicationWorkflowTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.owner = _user("owner", role=User.OWNER)
        self.admin = _user("admin", role=User.ADMIN)
        self.member_user = _user("member")
        self.member = _identity(self.member_user)
        self.vacant = _club(self.league, "Vacant United", "VAC")
        self.other_vacant = _club(self.league, "Other Vacant", "OVC")
        self.client = Client(HTTP_HOST="127.0.0.1", enforce_csrf_checks=True)

    def _login(self, username="member"):
        self.assertTrue(self.client.login(username=username, password="test-pass-123"))

    def _csrf(self, url=None):
        page = self.client.get(url or reverse("job_centre"))
        return page.cookies["csrftoken"].value

    def test_member_can_submit_without_managerapplication_approval(self):
        self.assertEqual(self.member.status, ManagerApplication.PENDING)
        self._login()
        token = self._csrf()
        response = self.client.post(
            reverse("apply_for_club", args=[self.vacant.id]),
            {**JOB_APPLY, "csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 302)
        app = ClubApplication.objects.get(manager=self.member, team=self.vacant)
        self.assertEqual(app.status, ApprovalStatus.PENDING)
        self.assertEqual(app.discord_username, "phase4user")
        self.assertEqual(app.games_per_week, "3-5")
        self.assertEqual(app.referred_by, "A Friend")
        self.assertTrue(app.new_gen_confirmed)
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, ManagerApplication.PENDING)
        self.assertIsNone(self.vacant.manager_id)

    def test_form_shows_locked_fields_and_status(self):
        self._login()
        page = self.client.get(reverse("job_centre"))
        self.assertContains(page, "EA ID / GAMERTAG")
        self.assertContains(page, "DISCORD USERNAME")
        self.assertNotContains(page, "DISCORD USER ID")
        self.assertContains(page, "1–3")
        self.assertContains(page, "3–5")
        self.assertContains(page, "6+")
        self.assertContains(page, "I confirm I am playing on a new gen console.")
        token = page.cookies["csrftoken"].value
        self.client.post(
            reverse("apply_for_club", args=[self.vacant.id]),
            {**JOB_APPLY, "csrfmiddlewaretoken": token},
        )
        status = self.client.get(reverse("job_centre"))
        self.assertContains(status, "mgl-job-status")
        self.assertContains(status, "YOUR JOB APPLICATION")
        self.assertContains(status, "PENDING")
        self.assertContains(status, "phase4user")

    def test_duplicate_pending_application_blocked(self):
        self._login()
        token = self._csrf()
        first = self.client.post(
            reverse("apply_for_club", args=[self.vacant.id]),
            {**JOB_APPLY, "csrfmiddlewaretoken": token},
        )
        self.assertEqual(first.status_code, 302)
        second = self.client.post(
            reverse("apply_for_club", args=[self.other_vacant.id]),
            {**JOB_APPLY, "csrfmiddlewaretoken": self._csrf()},
        )
        self.assertEqual(second.status_code, 302)
        self.assertEqual(ClubApplication.objects.filter(manager=self.member).count(), 1)
        self.assertEqual(
            ClubApplication.objects.filter(
                manager=self.member, status=ApprovalStatus.PENDING
            ).count(),
            1,
        )

    def test_csrf_required_on_apply(self):
        self._login()
        response = self.client.post(
            reverse("apply_for_club", args=[self.vacant.id]),
            JOB_APPLY,
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ClubApplication.objects.exists())

    def test_admin_sees_and_approves_atomically(self):
        self._login()
        token = self._csrf()
        self.client.post(
            reverse("apply_for_club", args=[self.vacant.id]),
            {**JOB_APPLY, "csrfmiddlewaretoken": token},
        )
        app = ClubApplication.objects.get(manager=self.member)
        self.client.logout()
        self._login("admin")
        review = self.client.get(reverse("control_managers"))
        self.assertContains(review, "JOB APPLICATIONS")
        self.assertContains(review, "EAIDPHASE4")
        self.assertContains(review, "phase4user")
        self.assertContains(review, "3-5")
        self.assertContains(review, "A Friend")
        self.assertContains(review, "CONFIRMED")
        self.assertContains(review, "APPROVE")
        self.assertContains(review, "REJECT")
        approve = self.client.post(
            reverse("control_approve_job", args=[app.id]),
            {"csrfmiddlewaretoken": self._csrf(reverse("control_managers"))},
        )
        self.assertEqual(approve.status_code, 302)
        app.refresh_from_db()
        self.member.refresh_from_db()
        self.vacant.refresh_from_db()
        self.member_user.refresh_from_db()
        self.assertEqual(app.status, ApprovalStatus.APPROVED)
        self.assertEqual(self.member.status, ManagerApplication.APPROVED)
        self.assertEqual(self.vacant.manager_id, self.member_user.id)
        self.assertEqual(self.member_user.role, User.MANAGER)
        self.assertTrue(self.member.club_spells.filter(team=self.vacant, ended_at__isnull=True).exists())
        self.client.logout()
        self._login()
        hub = self.client.get(reverse("manager_hub"))
        self.assertEqual(hub.status_code, 200)
        team = self.client.get(reverse("team_management"))
        self.assertEqual(team.status_code, 200)

    def test_no_second_managerapplication_approval_required(self):
        self.assertEqual(self.member.status, ManagerApplication.PENDING)
        payload = parse_club_application(JOB_APPLY)
        app = submit_job_application(self.member, self.vacant, payload)
        approve_job_application(app, self.owner)
        self.member.refresh_from_db()
        self.vacant.refresh_from_db()
        self.assertEqual(self.member.status, ManagerApplication.APPROVED)
        self.assertEqual(self.vacant.manager_id, self.member_user.id)
        self.assertEqual(
            ClubApplication.objects.filter(manager=self.member, status=ApprovalStatus.APPROVED).count(),
            1,
        )

    def test_approval_is_atomic_when_club_already_taken(self):
        other_user = _user("taken")
        _identity(other_user, status=ManagerApplication.APPROVED)
        payload = parse_club_application(JOB_APPLY)
        app = submit_job_application(self.member, self.vacant, payload)
        self.vacant.manager = other_user
        self.vacant.save(update_fields=["manager"])
        with self.assertRaises(ValueError):
            approve_job_application(app, self.owner)
        app.refresh_from_db()
        self.member.refresh_from_db()
        self.assertEqual(app.status, ApprovalStatus.PENDING)
        self.assertEqual(self.member.status, ManagerApplication.PENDING)
        self.assertNotEqual(self.vacant.manager_id, self.member_user.id)

    def test_admin_reject_leaves_member(self):
        payload = parse_club_application(JOB_APPLY)
        app = submit_job_application(self.member, self.vacant, payload)
        reject_job_application(app, self.admin)
        app.refresh_from_db()
        self.member.refresh_from_db()
        self.vacant.refresh_from_db()
        self.assertEqual(app.status, ApprovalStatus.REJECTED)
        self.assertEqual(self.member.status, ManagerApplication.PENDING)
        self.assertIsNone(self.vacant.manager_id)
        again = submit_job_application(
            self.member,
            self.other_vacant,
            parse_club_application({**JOB_APPLY, "games_per_week": "1-3"}),
        )
        self.assertEqual(again.status, ApprovalStatus.PENDING)

    def test_member_and_manager_cannot_approve(self):
        payload = parse_club_application(JOB_APPLY)
        app = submit_job_application(self.member, self.vacant, payload)
        self._login()
        blocked = self.client.post(
            reverse("control_approve_job", args=[app.id]),
            {"csrfmiddlewaretoken": self._csrf()},
        )
        self.assertEqual(blocked.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, ApprovalStatus.PENDING)

        approve_job_application(app, self.owner)
        rival_user = _user("rival")
        rival = _identity(rival_user)
        rival_app = submit_job_application(
            rival,
            self.other_vacant,
            parse_club_application({**JOB_APPLY, "discord_username": "rival"}),
        )
        self.client.logout()
        self._login()
        manager_blocked = self.client.post(
            reverse("control_approve_job", args=[rival_app.id]),
            {"csrfmiddlewaretoken": self._csrf(reverse("manager_hub"))},
        )
        self.assertEqual(manager_blocked.status_code, 302)
        rival_app.refresh_from_db()
        self.assertEqual(rival_app.status, ApprovalStatus.PENDING)
        self.assertIsNone(self.other_vacant.manager_id)

    def test_optional_discord_id_is_preserved_without_replacing_username(self):
        self._login()
        token = self._csrf()
        self.client.post(
            reverse("apply_for_club", args=[self.vacant.id]),
            {
                **JOB_APPLY,
                "discord_id": "123456789012345678",
                "csrfmiddlewaretoken": token,
            },
        )
        app = ClubApplication.objects.get(manager=self.member)
        self.member_user.refresh_from_db()
        self.assertEqual(app.discord_username, "phase4user")
        self.assertEqual(self.member_user.discord_id, "123456789012345678")


class PlayerReleaseLifecycleTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.owner = _user("owner", role=User.OWNER)
        self.user_a = _user("alpha")
        self.user_b = _user("bravo")
        self.mgr_a = _identity(self.user_a, status=ManagerApplication.APPROVED)
        self.mgr_b = _identity(self.user_b, status=ManagerApplication.APPROVED)
        self.team_a = _club(self.league, "Alpha FC", "ALP", manager=self.user_a)
        self.team_b = _club(self.league, "Bravo FC", "BRV", manager=self.user_b)
        self.owned = _player(name="Owned Striker", mgl_team=self.team_a)
        self.other = _player(name="Other Mid", position="CM", mgl_team=self.team_b)
        self.client = Client(HTTP_HOST="127.0.0.1", enforce_csrf_checks=True)

    def _login(self, username="alpha"):
        self.assertTrue(self.client.login(username=username, password="test-pass-123"))

    def _csrf(self, url=None):
        page = self.client.get(url or reverse("team_management"))
        return page.cookies["csrftoken"].value

    def test_manager_release_creates_genuine_fa_immediately(self):
        tokens_before = self.mgr_a.tokens
        self._login()
        response = self.client.post(
            reverse("release_my_player", args=[self.owned.id]),
            {"csrfmiddlewaretoken": self._csrf()},
        )
        self.assertEqual(response.status_code, 302)
        self.owned.refresh_from_db()
        self.mgr_a.refresh_from_db()
        self.assertIsNone(self.owned.mgl_team_id)
        self.assertIsNotNone(self.owned.released_at)
        self.assertTrue(is_ufl_free_agent(self.owned))
        self.assertEqual(ufl_player_status(self.owned), UFL_FREE_AGENT)
        self.assertEqual(self.mgr_a.tokens, tokens_before)
        self.assertTrue(free_agents().filter(pk=self.owned.pk).exists())
        row = PlayerReleaseRequest.objects.get(player=self.owned)
        self.assertEqual(row.status, ApprovalStatus.APPROVED)
        page = self.client.get(reverse("free_agents"))
        self.assertContains(page, "OWNED STRIKER")
        self.assertContains(page, "SIGN FOR 0 TKN")

    def test_sign_free_agent_costs_zero_and_becomes_club_owned(self):
        request_player_release(self.owned, self.team_a, self.mgr_a)
        tokens_before = self.mgr_b.tokens
        signed = sign_free_agent(self.owned, self.mgr_b)
        self.owned.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(signed.mgl_team_id, self.team_b.id)
        self.assertFalse(is_ufl_free_agent(self.owned))
        self.assertIsNone(self.owned.released_at)
        self.assertEqual(ufl_player_status(self.owned), CLUB_OWNED)
        self.assertEqual(self.mgr_b.tokens, tokens_before)
        self.assertFalse(free_agents().filter(pk=self.owned.pk).exists())

    def test_cannot_release_other_club_or_repeat(self):
        self._login()
        other = self.client.post(
            reverse("release_my_player", args=[self.other.id]),
            {"csrfmiddlewaretoken": self._csrf()},
        )
        self.assertEqual(other.status_code, 404)
        self.other.refresh_from_db()
        self.assertEqual(self.other.mgl_team_id, self.team_b.id)
        self.client.post(
            reverse("release_my_player", args=[self.owned.id]),
            {"csrfmiddlewaretoken": self._csrf()},
        )
        repeat = self.client.post(
            reverse("release_my_player", args=[self.owned.id]),
            {"csrfmiddlewaretoken": self._csrf(reverse("team_management"))},
        )
        self.assertEqual(repeat.status_code, 404)
        self.assertEqual(PlayerReleaseRequest.objects.filter(player=self.owned).count(), 1)

    def test_release_blocked_during_auction_and_listing(self):
        create_manager_auction(self.owned, self.mgr_a, 30)
        self.owned.refresh_from_db()
        with self.assertRaises(ValueError):
            request_player_release(self.owned, self.team_a, self.mgr_a)
        listed = _player(name="Listed Winger", position="LW", mgl_team=self.team_a)
        list_player_for_sale(listed, self.mgr_a, "3")
        with self.assertRaises(ValueError):
            request_player_release(listed, self.team_a, self.mgr_a)

    def test_csrf_required_on_release(self):
        self._login()
        response = self.client.post(reverse("release_my_player", args=[self.owned.id]), {})
        self.assertEqual(response.status_code, 403)
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.mgl_team_id, self.team_a.id)


class RecruitmentScoutStatusTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.user = _user("recruiter")
        self.manager = _identity(self.user, status=ManagerApplication.APPROVED, tokens="80.00")
        self.team = _club(self.league, "Recruit FC", "REC", manager=self.user)
        for index in range(8):
            _player(name=f"Pool ST {index}", position="ST", overall=66 + index)
        for index in range(8):
            _player(name=f"Bronze ST {index}", position="ST", overall=50 + (index % 8))

    def test_recruitment_rejects_stay_unsigned(self):
        opening = open_recruitment_pack(self.user, "ST")
        self.assertEqual(len(opening.player_ids), 3)
        chosen_id = opening.player_ids[0]
        others = opening.player_ids[1:]
        choose_recruitment_player(self.user, opening.id, chosen_id)
        chosen = Player.objects.get(pk=chosen_id)
        self.assertEqual(ufl_player_status(chosen), CLUB_OWNED)
        self.assertFalse(is_ufl_free_agent(chosen))
        for pk in others:
            other = Player.objects.get(pk=pk)
            self.assertEqual(ufl_player_status(other), UNSIGNED)
            self.assertFalse(is_ufl_free_agent(other))
            self.assertIsNone(other.released_at)

    def test_scout_rejects_stay_unsigned(self):
        assignment = dispatch_scout(self.manager, "BRONZE", "anywhere", "ST")
        assignment.ready_at = timezone.now() - timedelta(seconds=5)
        assignment.save(update_fields=["ready_at"])
        complete_ready_assignments(self.manager)
        assignment.refresh_from_db()
        self.assertEqual(len(assignment.player_ids), 4)
        chosen_id = assignment.player_ids[0]
        others = assignment.player_ids[1:]
        choose_scout_player(self.manager, assignment.id, chosen_id)
        chosen = Player.objects.get(pk=chosen_id)
        self.assertEqual(ufl_player_status(chosen), CLUB_OWNED)
        for pk in others:
            other = Player.objects.get(pk=pk)
            self.assertEqual(ufl_player_status(other), UNSIGNED)
            self.assertFalse(is_ufl_free_agent(other))


class AuctionAndStatusIntegrityTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.owner = _user("owner", role=User.OWNER)
        self.user_a = _user("seller")
        self.user_b = _user("buyer")
        self.mgr_a = _identity(self.user_a, status=ManagerApplication.APPROVED, tokens="20.00")
        self.mgr_b = _identity(self.user_b, status=ManagerApplication.APPROVED, tokens="20.00")
        self.team_a = _club(self.league, "Sell FC", "SEL", manager=self.user_a)
        self.team_b = _club(self.league, "Buy FC", "BUY", manager=self.user_b)
        self.owned = _player(name="Auction Club", mgl_team=self.team_a)
        self.unsigned = _player(name="Auction Unsigned", is_free_agent=True)

    def test_manager_listing_fee_and_no_bid_returns_home(self):
        self.assertEqual(MANAGER_AUCTION_LISTING_FEE, Decimal("0.10"))
        before = self.mgr_a.tokens
        auction = create_manager_auction(self.owned, self.mgr_a, 30)
        self.owned.refresh_from_db()
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, before - MANAGER_AUCTION_LISTING_FEE)
        self.assertEqual(ufl_player_status(self.owned), TEMPORARILY_LISTED)
        self.assertFalse(is_ufl_free_agent(self.owned))
        auction.ends_at = timezone.now() - timedelta(minutes=1)
        auction.save(update_fields=["ends_at"])
        close_expired_auctions()
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.mgl_team_id, self.team_a.id)
        self.assertEqual(ufl_player_status(self.owned), CLUB_OWNED)
        self.assertFalse(is_ufl_free_agent(self.owned))

    def test_manager_sold_auction_transfers(self):
        auction = create_manager_auction(self.owned, self.mgr_a, 30, starting_bid=1)
        place_auction_bid(auction, self.mgr_b, 5)
        settle_auction(auction)
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.mgl_team_id, self.team_b.id)
        self.assertEqual(ufl_player_status(self.owned), CLUB_OWNED)
        self.assertFalse(is_ufl_free_agent(self.owned))

    def test_admin_unsigned_no_bid_becomes_genuine_fa(self):
        auction = create_free_agent_auction(self.unsigned, self.owner, 30)
        auction.ends_at = timezone.now() - timedelta(minutes=1)
        auction.save(update_fields=["ends_at"])
        settle_auction(auction)
        self.unsigned.refresh_from_db()
        self.assertTrue(is_ufl_free_agent(self.unsigned))
        self.assertEqual(ufl_player_status(self.unsigned), UFL_FREE_AGENT)
        self.assertTrue(free_agents().filter(pk=self.unsigned.pk).exists())

    def test_legacy_flag_does_not_create_fa(self):
        leftover = _player(name="Legacy Flag", is_free_agent=True, released_at=None)
        self.assertEqual(ufl_player_status(leftover), UNSIGNED)
        self.assertFalse(is_ufl_free_agent(leftover))
        self.assertFalse(free_agents().filter(pk=leftover.pk).exists())

    def test_no_dual_club_or_club_plus_fa(self):
        self.assertEqual(ufl_player_status(self.owned), CLUB_OWNED)
        self.assertFalse(is_ufl_free_agent(self.owned))
        self.assertEqual(Player.objects.filter(pk=self.owned.pk, mgl_team__isnull=False).count(), 1)
        enter_ufl_free_agency(self.owned)
        self.owned.refresh_from_db()
        self.assertIsNone(self.owned.mgl_team_id)
        self.assertTrue(is_ufl_free_agent(self.owned))
        self.assertFalse(
            Player.objects.filter(pk=self.owned.pk, mgl_team__isnull=False, released_at__isnull=False).exists()
        )


class RoleBoundaryTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.member_user = _user("member")
        self.member = _identity(self.member_user)
        self.vacant = _club(self.league, "Boundary Club", "BND")
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_anonymous_cannot_apply_or_release(self):
        apply = self.client.post(reverse("apply_for_club", args=[self.vacant.id]), JOB_APPLY)
        self.assertEqual(apply.status_code, 302)
        self.assertIn(reverse("manager_login").rstrip("/"), apply["Location"])
        self.assertFalse(ClubApplication.objects.exists())
        player = _player(name="Safe")
        release = self.client.post(reverse("release_my_player", args=[player.id]))
        self.assertEqual(release.status_code, 302)

    def test_member_cannot_open_manager_controls(self):
        self.client.login(username="member", password="test-pass-123")
        for name in ("team_management", "free_agents", "live_auctions"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], reverse("job_centre"))
        control = self.client.get(reverse("control_centre"))
        self.assertEqual(control.status_code, 302)
