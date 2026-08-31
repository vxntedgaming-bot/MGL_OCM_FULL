from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User


class ControlCommandCentreTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.owner = User.objects.create_user(
            username="owner", password="test-pass-123", role=User.OWNER
        )

    def test_dashboard_and_dedicated_pages_load(self):
        self.client.login(username="owner", password="test-pass-123")
        dashboard = self.client.get(reverse("control_centre"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "WHAT NEEDS MY ATTENTION")
        self.assertContains(dashboard, "PENDING ACTIONS")
        self.assertContains(dashboard, "MATCH RESULTS")
        self.assertContains(dashboard, "TRANSFER REQUESTS")
        self.assertContains(dashboard, reverse("control_scores"))
        self.assertContains(dashboard, reverse("control_transfers"))
        pages = (
            "control_pending",
            "control_approvals",
            "control_scores",
            "control_approvals_scores",
            "control_transfers",
            "control_approvals_transfers",
            "control_press",
            "control_approvals_press",
            "control_weekly_awards",
            "control_history_weekly",
            "control_monthly_awards",
            "control_history_monthly",
            "control_managers",
            "control_approvals_managers",
            "control_tokens",
            "control_scouting",
            "control_management_scouting",
            "control_auctions",
            "control_management_auctions",
            "control_clubs",
            "control_management_clubs",
            "control_notifications",
            "control_logs",
            "control_season_history",
            "control_season_controls",
            "control_starting_squads",
            "control_league",
        )
        for name in pages:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
        self.client.logout()
        User.objects.create_user(
            username="ctrlmgr", password="test-pass-123", role=User.MANAGER
        )
        self.client.login(username="ctrlmgr", password="test-pass-123")
        blocked = self.client.get(reverse("control_centre"))
        self.assertEqual(blocked.status_code, 302)
