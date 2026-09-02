from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.models import ApprovalStatus, ClubApplication
from mgl.templatetags.mgl_ui import ovr_band, ovr_band_label
from mgl.verification import (
    NOT_VERIFIED,
    PENDING,
    REJECTED,
    SUSPENDED,
    VERIFIED,
    verification_snapshot,
)
from teams.models import Team


def _user(username, role=User.MANAGER, **kwargs):
    return User.objects.create_user(
        username=username,
        password="test-pass-123",
        role=role,
        **kwargs,
    )


class ManagerVerificationTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()

    def test_anonymous_verification_redirects_to_login(self):
        page = self.client.get(reverse("manager_verification"))
        self.assertEqual(page.status_code, 302)
        self.assertIn(reverse("manager_login"), page["Location"])

    def test_registering_does_not_assign_a_club(self):
        user = _user("newreg")
        snapshot = verification_snapshot(user)
        self.assertEqual(snapshot["status"], NOT_VERIFIED)
        self.assertIsNone(snapshot["club"])
        self.assertFalse(snapshot["is_verified"])

    def test_pending_job_application_is_pending(self):
        user = _user("applicant")
        identity = ManagerApplication.objects.create(
            user=user,
            display_name="Applicant",
            gamertag="APP1",
            status=ManagerApplication.PENDING,
        )
        team = Team.objects.create(name="Vacant Test", short_name="VTX", league=self.league)
        ClubApplication.objects.create(
            manager=identity,
            team=team,
            status=ApprovalStatus.PENDING,
        )
        snapshot = verification_snapshot(user)
        self.assertEqual(snapshot["status"], PENDING)
        self.assertEqual(snapshot["club_name"], "Vacant Test")
        self.assertFalse(snapshot["is_verified"])

        self.client.login(username="applicant", password="test-pass-123")
        page = self.client.get(reverse("manager_verification"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "UFL MANAGER VERIFICATION")
        self.assertContains(page, "PENDING")
        self.assertContains(page, "Vacant Test")
        self.assertContains(page, "VIEW JOB OFFERS")

    def test_rejected_job_is_rejected(self):
        user = _user("declined")
        identity = ManagerApplication.objects.create(
            user=user,
            display_name="Declined",
            gamertag="DEC1",
            status=ManagerApplication.REJECTED,
        )
        team = Team.objects.create(name="Rejected FC", short_name="RFC", league=self.league)
        ClubApplication.objects.create(
            manager=identity,
            team=team,
            status=ApprovalStatus.REJECTED,
        )
        self.assertEqual(verification_snapshot(user)["status"], REJECTED)

    def test_approved_manager_with_club_is_verified(self):
        user = _user("boss")
        ManagerApplication.objects.create(
            user=user,
            display_name="Boss",
            gamertag="BOSS",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("4.96"),
        )
        Team.objects.create(
            name="Bayer Test",
            short_name="B04",
            league=self.league,
            manager=user,
        )
        snapshot = verification_snapshot(user)
        self.assertEqual(snapshot["status"], VERIFIED)
        self.assertEqual(snapshot["club_name"], "Bayer Test")
        self.assertEqual(snapshot["account_status"], "ACTIVE")

        self.client.login(username="boss", password="test-pass-123")
        page = self.client.get(reverse("manager_verification"))
        self.assertContains(page, "VERIFIED")
        self.assertContains(page, "Bayer Test")
        self.assertContains(page, "ACTIVE")
        self.assertNotContains(page, "VIEW JOB OFFERS")

    def test_inactive_account_is_suspended(self):
        user = _user("benched", is_active=False)
        self.assertEqual(verification_snapshot(user)["status"], SUSPENDED)

    def test_nav_includes_verification_for_signed_in_manager(self):
        user = _user("navman")
        ManagerApplication.objects.create(
            user=user,
            display_name="Nav",
            gamertag="NAV1",
            status=ManagerApplication.APPROVED,
        )
        Team.objects.create(
            name="Nav Club",
            short_name="NAV",
            league=self.league,
            manager=user,
        )
        self.client.login(username="navman", password="test-pass-123")
        hub = self.client.get(reverse("manager_hub"))
        self.assertContains(hub, reverse("manager_verification"))
        self.assertContains(hub, "Manager Verification")


class RatingBandTests(TestCase):
    def test_ovr_bands_match_spec(self):
        self.assertEqual(ovr_band(99), "high")
        self.assertEqual(ovr_band(78), "high")
        self.assertEqual(ovr_band(77), "mid")
        self.assertEqual(ovr_band(65), "mid")
        self.assertEqual(ovr_band(64), "low")
        self.assertEqual(ovr_band(0), "low")
        self.assertEqual(ovr_band_label(91), "HIGH")
        self.assertEqual(ovr_band_label(70), "MID")
        self.assertEqual(ovr_band_label(48), "LOW")
