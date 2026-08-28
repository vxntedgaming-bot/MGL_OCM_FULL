from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.models import League
from managers.models import ManagerApplication
from managers.services import STARTING_TOKENS, approve_manager_application
from mgl.models import ManagerCareerStat, ManagerClubSpell, Trophy
from mgl.tenure import open_club_spell, resign_manager_from_club
from players.models import Player
from teams.models import Team


def _user(username, role=User.MANAGER, **kwargs):
    return User.objects.create_user(
        username=username,
        password="test-pass-123",
        role=role,
        **kwargs,
    )


def _manager(user, tokens="8.00", status=ManagerApplication.APPROVED):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=status,
        tokens=Decimal(tokens),
    )


class ManagerResignTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = League.objects.create(name="Resign League", short_name="RSL", season="1")
        self.owner = _user("owner", role=User.OWNER)
        self.user = _user("hopper")
        self.rival_user = _user("rival")
        self.manager = _manager(self.user, tokens="8.00")
        self.rival = _manager(self.rival_user, tokens="11.00")
        self.club = Team.objects.create(
            name="Arsenal",
            short_name="ARS",
            league=self.league,
            manager=self.user,
        )
        self.other_club = Team.objects.create(
            name="Chelsea",
            short_name="CHE",
            league=self.league,
            manager=self.rival_user,
        )
        self.vacant = Team.objects.create(
            name="Liverpool",
            short_name="LIV",
            league=self.league,
        )
        self.player = Player.objects.create(
            name="Club Striker",
            position="ST",
            overall=74,
            mgl_team=self.club,
            is_free_agent=False,
        )
        self.kept = Player.objects.create(
            name="Club Keeper",
            position="GK",
            overall=70,
            mgl_team=self.club,
            is_free_agent=False,
        )
        open_club_spell(self.manager, self.club)
        open_club_spell(self.rival, self.other_club)
        ManagerCareerStat.objects.create(manager=self.manager, wins=4, draws=1, losses=2, trophies=1)
        Trophy.objects.create(manager=self.manager, name="Community Shield", season="2026")

    def _login(self, username="hopper"):
        self.assertTrue(self.client.login(username=username, password="test-pass-123"))

    def test_manager_with_club_sees_resign_button(self):
        self._login()
        page = self.client.get(reverse("manager_profile"))
        self.assertContains(page, "RESIGN FROM CLUB")
        self.assertContains(page, "ARS")
        self.assertNotContains(page, "RESIGN FROM CLUB?")

    def test_resign_confirmation_does_not_leave_the_club(self):
        self._login()
        page = self.client.get(reverse("manager_profile") + "?resign=1")
        self.assertContains(page, "RESIGN FROM CLUB?")
        self.assertContains(page, "Are you sure you want to resign from Arsenal?")
        self.assertContains(page, "CONFIRM RESIGNATION")
        self.assertContains(page, "CANCEL")
        self.club.refresh_from_db()
        self.assertEqual(self.club.manager_id, self.user.id)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("8.00"))

    def test_manager_without_a_club_has_no_working_resignation(self):
        self.club.manager = None
        self.club.save(update_fields=["manager"])
        self._login()
        page = self.client.get(reverse("manager_profile"))
        self.assertNotContains(page, "RESIGN FROM CLUB")
        self.assertContains(page, "No Club")
        self.assertContains(page, "AVAILABLE FOR MANAGEMENT")
        blocked = self.client.post(reverse("resign_from_club"))
        self.assertEqual(blocked.status_code, 302)
        self.assertEqual(blocked["Location"], reverse("manager_profile"))
        self.club.refresh_from_db()
        self.assertIsNone(self.club.manager_id)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("8.00"))
        confirm = self.client.get(reverse("manager_profile") + "?resign=1")
        self.assertNotContains(confirm, "RESIGN FROM CLUB?")

    def test_resignation_requires_post(self):
        self._login()
        response = self.client.get(reverse("resign_from_club"))
        self.assertEqual(response.status_code, 405)
        self.club.refresh_from_db()
        self.assertEqual(self.club.manager_id, self.user.id)

    def test_resignation_requires_authentication(self):
        anonymous = Client(HTTP_HOST="127.0.0.1")
        response = anonymous.post(reverse("resign_from_club"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"))
        self.club.refresh_from_db()
        self.assertEqual(self.club.manager_id, self.user.id)

    def test_csrf_protection_rejects_post_without_token(self):
        csrf_client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
        csrf_client.login(username="hopper", password="test-pass-123")
        csrf_client.get(reverse("manager_profile"))
        rejected = csrf_client.post(reverse("resign_from_club"))
        self.assertEqual(rejected.status_code, 403)
        self.club.refresh_from_db()
        self.assertEqual(self.club.manager_id, self.user.id)

        token = csrf_client.cookies["csrftoken"].value
        accepted = csrf_client.post(
            reverse("resign_from_club"),
            {"csrfmiddlewaretoken": token},
        )
        self.assertEqual(accepted.status_code, 302)
        self.club.refresh_from_db()
        self.assertIsNone(self.club.manager_id)

    def test_manager_can_resign_from_own_club(self):
        self._login()
        response = self.client.post(reverse("resign_from_club"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("manager_profile"))
        self.club.refresh_from_db()
        self.manager.refresh_from_db()
        self.user.refresh_from_db()
        self.assertIsNone(self.club.manager_id)
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.manager.status, ManagerApplication.APPROVED)
        self.assertEqual(self.manager.tokens, Decimal("8.00"))

        profile = self.client.get(reverse("manager_profile"))
        self.assertContains(profile, "No Club")
        self.assertContains(profile, "AVAILABLE FOR MANAGEMENT")
        self.assertContains(profile, "8.00")
        self.assertContains(profile, "Arsenal")
        self.assertContains(profile, "Status: Resigned")
        self.assertNotContains(profile, "RESIGN FROM CLUB")

    def test_manager_cannot_resign_another_manager(self):
        self._login("rival")
        self.client.post(
            reverse("resign_from_club"),
            {
                "manager_id": self.manager.id,
                "user_id": self.user.id,
                "team_id": self.club.id,
            },
        )
        self.club.refresh_from_db()
        self.other_club.refresh_from_db()
        self.assertEqual(self.club.manager_id, self.user.id)
        self.assertIsNone(self.other_club.manager_id)
        self.manager.refresh_from_db()
        self.rival.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("8.00"))
        self.assertEqual(self.rival.tokens, Decimal("11.00"))
        missing = self.client.get("/mgl/profile/resign/%s/" % self.user.id)
        self.assertEqual(missing.status_code, 404)

    def test_duplicate_resignation_is_rejected(self):
        self._login()
        first = self.client.post(reverse("resign_from_club"))
        self.assertEqual(first.status_code, 302)
        second = self.client.post(reverse("resign_from_club"), follow=True)
        self.assertContains(second, "You do not currently manage a club.")
        self.assertEqual(Team.objects.filter(pk=self.club.pk).count(), 1)
        self.assertEqual(ManagerApplication.objects.filter(user=self.user).count(), 1)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("8.00"))

    def test_club_and_players_remain_after_resignation(self):
        player_id = self.player.id
        kept_id = self.kept.id
        club_id = self.club.id
        self._login()
        self.client.post(reverse("resign_from_club"))
        self.assertTrue(Team.objects.filter(pk=club_id).exists())
        self.player.refresh_from_db()
        self.kept.refresh_from_db()
        self.assertEqual(self.player.id, player_id)
        self.assertEqual(self.kept.id, kept_id)
        self.assertEqual(self.player.mgl_team_id, club_id)
        self.assertEqual(self.kept.mgl_team_id, club_id)
        self.assertFalse(self.player.is_free_agent)
        self.assertFalse(self.kept.is_free_agent)
        self.assertEqual(Player.objects.filter(mgl_team=self.club).count(), 2)

    def test_career_history_and_previous_spell_are_preserved(self):
        self._login()
        self.client.post(reverse("resign_from_club"))
        career = ManagerCareerStat.objects.get(manager=self.manager)
        self.assertEqual(career.wins, 4)
        self.assertEqual(career.draws, 1)
        self.assertEqual(career.losses, 2)
        self.assertEqual(career.trophies, 1)
        self.assertTrue(Trophy.objects.filter(manager=self.manager, name="Community Shield").exists())
        spells = list(self.manager.club_spells.filter(team=self.club))
        self.assertEqual(len(spells), 1)
        self.assertIsNotNone(spells[0].ended_at)
        self.assertEqual(spells[0].end_reason, ManagerClubSpell.RESIGNED)
        self.assertEqual(self.manager.club_spells.filter(ended_at__isnull=True).count(), 0)

    def test_resigned_manager_can_apply_and_join_without_token_reset(self):
        self._login()
        self.client.post(reverse("resign_from_club"))
        jobs = self.client.get(reverse("job_centre"))
        self.assertContains(jobs, "Arsenal")
        self.assertContains(jobs, "Liverpool")
        apply = self.client.post(reverse("apply_for_club", args=[self.vacant.id]))
        self.assertEqual(apply.status_code, 302)
        job = self.manager.club_applications.get(team=self.vacant)
        self.client.logout()
        self._login("owner")
        approve = self.client.post(reverse("control_approve_job", args=[job.id]))
        self.assertEqual(approve.status_code, 302)
        self.vacant.refresh_from_db()
        self.manager.refresh_from_db()
        self.club.refresh_from_db()
        self.assertEqual(self.vacant.manager_id, self.user.id)
        self.assertIsNone(self.club.manager_id)
        self.assertEqual(self.manager.tokens, Decimal("8.00"))
        self.assertEqual(ManagerApplication.objects.filter(user=self.user).count(), 1)
        self.assertEqual(self.manager.club_spells.count(), 2)
        self.assertEqual(
            self.manager.club_spells.filter(team=self.club, end_reason=ManagerClubSpell.RESIGNED).count(),
            1,
        )
        self.assertEqual(self.manager.club_spells.filter(team=self.vacant, ended_at__isnull=True).count(), 1)

    def test_new_manager_signup_still_receives_exactly_20_tokens(self):
        newbie = _user("newbie", is_active=False)
        application = ManagerApplication.objects.create(
            user=newbie,
            display_name="Newbie",
            gamertag="NEW",
            status=ManagerApplication.PENDING,
        )
        self.assertEqual(application.tokens, STARTING_TOKENS)
        approve_manager_application(application, self.owner)
        application.refresh_from_db()
        self.assertEqual(application.tokens, Decimal("20.00"))
        self.assertEqual(ManagerApplication.objects.filter(user=newbie).count(), 1)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("8.00"))

    def test_helper_does_not_touch_tokens_or_duplicate_records(self):
        team = resign_manager_from_club(self.manager)
        self.assertEqual(team.pk, self.club.pk)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("8.00"))
        self.assertEqual(ManagerApplication.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Player.objects.filter(pk=self.player.pk, mgl_team=self.club).count(), 1)
        with self.assertRaises(ValueError):
            resign_manager_from_club(self.manager)
        with self.assertRaises(ValueError):
            resign_manager_from_club(None)
