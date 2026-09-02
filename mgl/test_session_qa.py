from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.models import ApprovalStatus, ClubApplication, ManagerNotification
from mgl.notifications import inbox_for_user, notify_user, unread_count_for_user
from mgl.verification import NOT_VERIFIED, PENDING, VERIFIED, verification_snapshot
from teams.models import Team


def _user(username, role=User.MANAGER):
    return User.objects.create_user(
        username=username,
        password="test-pass-123",
        role=role,
    )


class ManagerSessionQaTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.user = _user("sessionmgr")
        self.manager = ManagerApplication.objects.create(
            user=self.user,
            display_name="Session Manager",
            gamertag="SESMGR",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("20.00"),
        )
        self.team = Team.objects.create(
            name="Session United",
            short_name="SSU",
            league=self.league,
            manager=self.user,
        )

    def test_manager_login_unlocks_hub_team_notifications_and_verification(self):
        login = self.client.login(username="sessionmgr", password="test-pass-123")
        self.assertTrue(login)

        hub = self.client.get(reverse("manager_hub"))
        self.assertEqual(hub.status_code, 200)
        self.assertContains(hub, "Session United")
        self.assertContains(hub, reverse("team_management"))
        self.assertContains(hub, reverse("manager_notifications"))
        self.assertContains(hub, reverse("manager_verification"))
        self.assertContains(hub, "MY TEAM")
        self.assertNotContains(hub, "CONTROL CENTRE")

        team = self.client.get(reverse("team_management"))
        self.assertEqual(team.status_code, 200)
        self.assertContains(team, "Session United")
        self.assertContains(team, 'class="ufl-coin-amt">20.00</span>')

        inbox = self.client.get(reverse("manager_notifications"))
        self.assertEqual(inbox.status_code, 200)
        for label in ("ALL", "UNREAD", "TRANSFERS", "FIXTURES", "CLUB", "MANAGER", "SYSTEM"):
            self.assertContains(inbox, label)
        self.assertNotContains(inbox, "mgl-inbox-filters")

        verify = self.client.get(reverse("manager_verification"))
        self.assertEqual(verify.status_code, 200)
        self.assertContains(verify, "VERIFIED")
        self.assertEqual(verification_snapshot(self.user)["status"], VERIFIED)


class AdminSessionQaTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.owner = _user("sessionowner", role=User.OWNER)
        self.applicant_user = _user("sessionapp")
        self.applicant = ManagerApplication.objects.create(
            user=self.applicant_user,
            display_name="Session Applicant",
            gamertag="SESAPP",
            status=ManagerApplication.PENDING,
        )
        self.vacant = Team.objects.create(
            name="Session Vacant",
            short_name="SSV",
            league=self.league,
        )
        self.job = ClubApplication.objects.create(
            manager=self.applicant,
            team=self.vacant,
            status=ApprovalStatus.PENDING,
        )

    def test_owner_opens_control_centre_notifications_and_verification_actions(self):
        login = self.client.login(username="sessionowner", password="test-pass-123")
        self.assertTrue(login)

        control = self.client.get(reverse("control_centre"))
        self.assertEqual(control.status_code, 200)
        self.assertContains(control, "OWNER / ADMIN CONTROL")
        self.assertContains(control, "OVERVIEW")
        self.assertContains(control, "MANAGER MANAGEMENT")
        self.assertContains(control, "CLUB MANAGEMENT")
        self.assertContains(control, "MATCH MANAGEMENT")
        self.assertContains(control, "TRANSFERS")
        self.assertContains(control, "NEWS / ACTIVITY")
        self.assertContains(control, "SYSTEM")
        self.assertContains(control, reverse("control_managers"))
        self.assertContains(control, reverse("control_clubs"))
        self.assertContains(control, reverse("control_scores"))
        self.assertContains(control, reverse("control_transfers"))
        self.assertContains(control, reverse("control_press"))
        self.assertContains(control, reverse("control_notifications"))
        self.assertContains(control, reverse("site_management"))

        inbox = self.client.get(reverse("control_notifications"))
        self.assertEqual(inbox.status_code, 200)

        managers = self.client.get(reverse("control_managers"))
        self.assertEqual(managers.status_code, 200)
        self.assertContains(managers, "Session Applicant")
        self.assertContains(managers, "Session Vacant")
        self.assertContains(managers, "mgl-cp-approve")
        self.assertContains(managers, "mgl-cp-reject")
        self.assertContains(managers, ">APPROVE</button>")
        self.assertContains(managers, ">REJECT</button>")
        self.assertEqual(verification_snapshot(self.applicant_user)["status"], PENDING)


class NotificationSessionQaTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.user = _user("sessionnote")
        ManagerApplication.objects.create(
            user=self.user,
            display_name="Note Manager",
            gamertag="NOTEMGR",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("20.00"),
        )
        self.team = Team.objects.create(
            name="Note United",
            short_name="NTU",
            league=self.league,
            manager=self.user,
        )

    def test_manager_can_read_existing_notification_workflow(self):
        notify_user(
            self.user,
            source_key="session-qa-note",
            notification_type="SYSTEM",
            title="SESSION QA NOTICE",
            message="Existing notification workflow check.",
            team=self.team,
        )
        self.assertEqual(unread_count_for_user(self.user), 1)
        self.client.login(username="sessionnote", password="test-pass-123")
        inbox = self.client.get(reverse("manager_notifications"))
        self.assertContains(inbox, "SESSION QA NOTICE")
        self.assertContains(inbox, "is-unread")
        self.assertContains(inbox, "SYSTEM")
        self.client.post(reverse("notification_mark_all_read"))
        self.assertEqual(unread_count_for_user(self.user), 0)
        items = inbox_for_user(self.user)
        self.assertTrue(items)
        self.assertFalse(ManagerNotification.objects.filter(recipient=self.user, read_at__isnull=True).exists())


class RegistrationDoesNotAssignClubTests(TestCase):
    def test_new_account_is_not_verified_and_has_no_club(self):
        user = _user("sessionreg")
        snapshot = verification_snapshot(user)
        self.assertEqual(snapshot["status"], NOT_VERIFIED)
        self.assertIsNone(snapshot["club"])
        self.assertFalse(Team.objects.filter(manager=user).exists())
