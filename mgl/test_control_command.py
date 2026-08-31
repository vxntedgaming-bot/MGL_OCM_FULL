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
            "control_scores",
            "control_transfers",
            "control_press",
            "control_weekly_awards",
            "control_monthly_awards",
            "control_managers",
            "control_tokens",
            "control_scouting",
            "control_auctions",
            "control_clubs",
            "control_notifications",
            "control_logs",
        )
        for name in pages:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
