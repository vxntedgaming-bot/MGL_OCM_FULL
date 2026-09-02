from decimal import Decimal
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.management import call_command
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from config.env import database_config, parse_database_url, sqlite_config
from managers.models import ManagerApplication
from mgl.views import home


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _fresh_settings_value(expression, extra_env=None):
    env = os.environ.copy()
    for key in (
        "DJANGO_DEBUG",
        "DJANGO_SECRET_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "DJANGO_EMAIL_BACKEND",
        "DATABASE_URL",
        "POSTGRES_DB",
        "POSTGRES_HOST",
    ):
        env.pop(key, None)
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, django\n"
            "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')\n"
            "django.setup()\n"
            "from django.conf import settings\n"
            f"print({expression})\n",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout.strip()


class PhaseBSettingsTests(SimpleTestCase):
    def test_local_defaults_keep_sqlite_debug_and_console_email(self):
        # Django's test runner forces settings.DEBUG=False in-process.
        # Inspect a fresh interpreter for the real local defaults.
        self.assertEqual(_fresh_settings_value("settings.DEBUG"), "True")
        self.assertEqual(
            _fresh_settings_value("settings.MAILERS['default']['BACKEND']"),
            "django.core.mail.backends.console.EmailBackend",
        )
        self.assertEqual(
            _fresh_settings_value("settings.DATABASES['default']['ENGINE']"),
            "django.db.backends.sqlite3",
        )
        self.assertEqual(_fresh_settings_value("settings.SECURE_SSL_REDIRECT"), "False")
        self.assertEqual(_fresh_settings_value("settings.SESSION_COOKIE_SECURE"), "False")
        self.assertEqual(_fresh_settings_value("settings.CSRF_COOKIE_SECURE"), "False")
        self.assertEqual(_fresh_settings_value("settings.SECURE_HSTS_SECONDS"), "0")
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3")
        self.assertIn("127.0.0.1", settings.ALLOWED_HOSTS)
        self.assertIn("whitenoise.middleware.WhiteNoiseMiddleware", settings.MIDDLEWARE)

    def test_static_and_media_paths_keep_existing_layout(self):
        self.assertEqual(settings.STATIC_URL, "/static/")
        self.assertEqual(settings.STATIC_ROOT, PROJECT_ROOT / "staticfiles")
        self.assertIn(PROJECT_ROOT / "static", settings.STATICFILES_DIRS)
        self.assertEqual(settings.MEDIA_URL, "/media/")
        self.assertEqual(settings.MEDIA_ROOT, PROJECT_ROOT / "media")
        self.assertTrue(settings.SERVE_MEDIA)

    def test_sqlite_is_used_when_postgres_env_is_absent(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in (
                "DATABASE_URL",
                "POSTGRES_DB",
                "POSTGRES_HOST",
                "SQLITE_PATH",
            ):
                os.environ.pop(key, None)
            config = sqlite_config(PROJECT_ROOT)
        self.assertEqual(config["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(config["NAME"], PROJECT_ROOT / "db.sqlite3")

    def test_database_url_selects_postgres_without_touching_sqlite(self):
        parsed = parse_database_url(
            "postgres://mgl:secret@db.example.com:5433/mgl_prod"
        )
        self.assertEqual(parsed["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(parsed["NAME"], "mgl_prod")
        self.assertEqual(parsed["USER"], "mgl")
        self.assertEqual(parsed["PASSWORD"], "secret")
        self.assertEqual(parsed["HOST"], "db.example.com")
        self.assertEqual(parsed["PORT"], "5433")

        with mock.patch.dict(
            os.environ,
            {"DATABASE_URL": "postgres://mgl:secret@127.0.0.1:5432/mgl"},
            clear=False,
        ):
            config = database_config(PROJECT_ROOT)
        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["NAME"], "mgl")


class PhaseBDeployCheckTests(SimpleTestCase):
    def test_production_env_passes_deploy_check(self):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_DEBUG": "false",
                "DJANGO_SECRET_KEY": "phase-b-production-secret-key-value-for-deploy-check-50",
                "DJANGO_ALLOWED_HOSTS": "ocm.example.com",
                "DJANGO_CSRF_TRUSTED_ORIGINS": "https://ocm.example.com",
                "DJANGO_SECURE_SSL_REDIRECT": "true",
            }
        )
        env.pop("DATABASE_URL", None)
        env.pop("POSTGRES_DB", None)
        env.pop("POSTGRES_HOST", None)
        result = subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy"],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            result.stdout + result.stderr,
        )


class PhaseBStaticTests(TestCase):
    def test_collectstatic_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            static_root = Path(tmp) / "staticfiles"
            with override_settings(STATIC_ROOT=static_root):
                call_command("collectstatic", interactive=False, verbosity=0)
            css = static_root / "core" / "css" / "mgl.css"
            cards = static_root / "mgl" / "cards" / "gold_card.png"
            self.assertTrue(css.exists(), css)
            self.assertTrue(cards.exists(), cards)

    def test_homepage_still_loads_existing_css(self):
        response = self.client.get("/", HTTP_HOST="127.0.0.1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "core/css/mgl.css")
        self.assertContains(response, "core/css/ufl.css")
        self.assertContains(response, "YOUR CLUB")


class PhaseBRegressionTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.user = User.objects.create_user(
            username="phaseb",
            password="test-pass-123",
        )
        ManagerApplication.objects.create(
            user=self.user,
            display_name="Phase B",
            gamertag="PB1",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("50.00"),
        )

    def test_public_routes_still_work(self):
        for url in ["/", "/login/", "/register/"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_mgl_index_and_logged_out_team_redirect(self):
        mgl = self.client.get("/mgl/")
        self.assertEqual(mgl.status_code, 302)
        self.assertEqual(mgl["Location"], "/")

        team = self.client.get("/mgl/team/")
        self.assertEqual(team.status_code, 302)
        self.assertIn(reverse("job_centre"), team["Location"])

    def test_authenticated_manager_routes_still_work(self):
        self.assertTrue(self.client.login(username="phaseb", password="test-pass-123"))
        for url in [
            "/mgl/hub/",
            "/mgl/team/",
            "/mgl/fixtures/",
            "/mgl/players/",
            "/mgl/rewards/",
            "/auctions/",
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_logout_post_still_works(self):
        self.client.login(username="phaseb", password="test-pass-123")
        response = self.client.post("/logout/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")
        follow = self.client.get("/mgl/hub/")
        self.assertEqual(follow.status_code, 302)
        self.assertIn(reverse("job_centre"), follow["Location"])

    def test_messages_still_render_on_homepage(self):
        factory = RequestFactory()
        request = factory.get("/")
        request.user = AnonymousUser()
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda req: None).process_request(request)
        messages.success(request, "Phase B flash message")
        response = home(request)
        self.assertContains(response, "Phase B flash message")
        self.assertContains(response, "mgl-messages")

    def test_homepage_still_uses_database_empty_states(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "NAPOLI")
        self.assertContains(response, "No upcoming fixtures have been released.")
        self.assertContains(response, reverse("home"))
