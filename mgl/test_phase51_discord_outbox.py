import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from leagues.models import League
from managers.models import ManagerApplication
from mgl.admin import approve_selected_totw
from mgl.discord_channels import parse_channel_map, resolve_channel_id
from mgl.discord_queue import (
    MAX_ATTEMPTS,
    backoff_seconds,
    event_payload_preview,
    mark_discord_failed,
    mark_discord_sent,
    pending_discord_events,
    queue_discord_event,
    queue_from_news,
    queue_personal_discord,
    retry_discord_event,
)
from mgl.job_applications import job_centre_discord_invite
from mgl.models import DiscordEvent, NewsPost, TeamOfTheWeek
from mgl.notifications import notify_user
from mgl.services import create_news
from players.models import Player
from teams.models import Team


def _user(username, role=User.MANAGER, **kwargs):
    return User.objects.create_user(
        username=username,
        password="test-pass-123",
        role=role,
        **kwargs,
    )


def _manager(user, tokens="50.00"):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=ManagerApplication.APPROVED,
        tokens=Decimal(tokens),
    )


class Phase51DiscordOutboxTests(TestCase):
    def setUp(self):
        self.league = League.objects.create(name="UFL Test", short_name="UFL", season="1")
        self.owner = _user("owner51", User.OWNER)
        self.admin = _user("admin51", User.ADMIN)
        self.manager_user = _user("manager51")
        self.member_user = _user("member51")
        self.mgr = _manager(self.manager_user)
        ManagerApplication.objects.create(
            user=self.member_user,
            display_name="Member 51",
            gamertag="MEM51",
            status=ManagerApplication.PENDING,
        )
        self.team = Team.objects.create(
            name="Outbox United",
            short_name="OUT",
            league=self.league,
            manager=self.manager_user,
            roster_limit=30,
        )
        self.player = Player.objects.create(
            name="Outbox Striker",
            position="ST",
            overall=67,
            mgl_team=self.team,
            is_free_agent=False,
            fc27_id="fc-outbox-1",
        )

    def test_create_news_queues_pending_event_with_news_key(self):
        post = create_news(NewsPost.TRANSFER, "Deal done", "A completed transfer.")
        event = DiscordEvent.objects.get(news_post=post)
        self.assertEqual(event.status, DiscordEvent.PENDING)
        self.assertEqual(event.idempotency_key, f"news:{post.pk}")
        self.assertEqual(event.attempt_count, 0)
        self.assertIn(event, pending_discord_events())

    def test_action_key_prevents_duplicate_events_across_news_rows(self):
        first = create_news(
            NewsPost.AUCTION,
            "Sold once",
            "Auction completed.",
            discord_idempotency_key="auction.sold:99",
        )
        second = create_news(
            NewsPost.AUCTION,
            "Sold again",
            "Same auction retried.",
            discord_idempotency_key="auction.sold:99",
        )
        self.assertNotEqual(first.pk, second.pk)
        events = DiscordEvent.objects.filter(idempotency_key="auction.sold:99")
        self.assertEqual(events.count(), 1)
        self.assertEqual(DiscordEvent.objects.filter(news_post=first).count(), 1)
        self.assertEqual(DiscordEvent.objects.filter(news_post=second).count(), 0)

    def test_queue_from_news_and_direct_queue_are_idempotent(self):
        post = create_news(NewsPost.PRESS, "Press", "Answer approved.")
        first = DiscordEvent.objects.get(news_post=post)
        self.assertEqual(queue_from_news(post).pk, first.pk)
        again = queue_from_news(post, idempotency_key=f"news:{post.pk}")
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(DiscordEvent.objects.filter(news_post=post).count(), 1)
        duplicate = queue_discord_event(
            "TRANSFER",
            {"text": "again"},
            idempotency_key=first.idempotency_key,
        )
        self.assertEqual(duplicate.pk, first.pk)

    def test_personal_discord_uses_source_key(self):
        self.manager_user.discord_id = "555666777"
        self.manager_user.save(update_fields=["discord_id"])
        notify_user(
            self.manager_user,
            source_key="transfer-bought-12",
            notification_type="TRANSFER",
            title="PLAYER SIGNED",
            message="Signed.",
        )
        notify_user(
            self.manager_user,
            source_key="transfer-bought-12",
            notification_type="TRANSFER",
            title="PLAYER SIGNED",
            message="Signed.",
        )
        events = DiscordEvent.objects.filter(channel_key="DM", idempotency_key="dm:transfer-bought-12")
        self.assertEqual(events.count(), 1)
        again = queue_personal_discord(
            self.manager_user,
            "TRANSFER",
            "PLAYER SIGNED",
            "Signed.",
            idempotency_key="dm:transfer-bought-12",
        )
        self.assertEqual(again.pk, events.get().pk)

    def test_successful_event_is_sent_once(self):
        event = queue_discord_event("NEWS", {"text": "ok"}, idempotency_key="news.ok:1")
        mark_discord_sent(event)
        event.refresh_from_db()
        self.assertEqual(event.status, DiscordEvent.SENT)
        self.assertEqual(event.attempt_count, 1)
        self.assertIsNone(event.next_attempt_at)
        self.assertEqual(pending_discord_events(), [])

    def test_temporary_failure_retries_with_backoff(self):
        event = queue_discord_event("NEWS", {"text": "later"}, idempotency_key="news.later:1")
        mark_discord_failed(event, "timeout")
        event.refresh_from_db()
        self.assertEqual(event.status, DiscordEvent.PENDING)
        self.assertEqual(event.attempt_count, 1)
        self.assertEqual(event.error, "timeout")
        self.assertIsNotNone(event.next_attempt_at)
        self.assertGreater(event.next_attempt_at, timezone.now())
        self.assertEqual(pending_discord_events(), [])
        event.next_attempt_at = timezone.now() - timedelta(seconds=1)
        event.save(update_fields=["next_attempt_at"])
        self.assertEqual(pending_discord_events()[0].pk, event.pk)

    def test_backoff_increases_then_fails_permanently(self):
        self.assertEqual(backoff_seconds(1), 10)
        self.assertEqual(backoff_seconds(2), 30)
        self.assertEqual(backoff_seconds(3), 60)
        self.assertLess(backoff_seconds(2), backoff_seconds(5))
        event = queue_discord_event("NEWS", {"text": "perm"}, idempotency_key="news.perm:1")
        for attempt in range(MAX_ATTEMPTS - 1):
            mark_discord_failed(event, f"err-{attempt}")
            event.refresh_from_db()
            self.assertEqual(event.status, DiscordEvent.PENDING)
        mark_discord_failed(event, "final")
        event.refresh_from_db()
        self.assertEqual(event.status, DiscordEvent.FAILED)
        self.assertEqual(event.attempt_count, MAX_ATTEMPTS)
        self.assertIsNone(event.next_attempt_at)
        self.assertEqual(event.error, "final")
        self.assertEqual(pending_discord_events(), [])

    def test_bot_restart_still_sees_due_pending_events(self):
        due = queue_discord_event("NEWS", {"text": "due"}, idempotency_key="restart.due:1")
        waiting = queue_discord_event("NEWS", {"text": "wait"}, idempotency_key="restart.wait:1")
        mark_discord_failed(waiting, "offline")
        waiting.refresh_from_db()
        ids = {event.pk for event in pending_discord_events()}
        self.assertIn(due.pk, ids)
        self.assertNotIn(waiting.pk, ids)
        DiscordEvent.objects.filter(pk=waiting.pk).update(
            next_attempt_at=timezone.now() - timedelta(seconds=1)
        )
        ids = {event.pk for event in pending_discord_events()}
        self.assertIn(waiting.pk, ids)

    def test_failed_event_remains_auditable(self):
        event = queue_discord_event("NEWS", {"text": "keep"}, idempotency_key="news.keep:1")
        event.attempt_count = MAX_ATTEMPTS - 1
        event.save(update_fields=["attempt_count"])
        mark_discord_failed(event, "channel missing")
        event.refresh_from_db()
        self.assertEqual(event.status, DiscordEvent.FAILED)
        self.assertTrue(DiscordEvent.objects.filter(pk=event.pk, error="channel missing").exists())

    def _login(self, user):
        client = Client()
        client.force_login(user)
        return client

    def test_owner_and_admin_can_inspect_outbox(self):
        event = queue_discord_event(
            "TRANSFER",
            {"title": "Deal", "text": "Posted", "discord_id": "should-hide"},
            idempotency_key="inspect:1",
        )
        for user in (self.owner, self.admin):
            client = self._login(user)
            listing = client.get(reverse("control_discord_outbox"))
            self.assertEqual(listing.status_code, 200)
            self.assertContains(listing, "TRANSFER")
            self.assertContains(listing, "PENDING")
            self.assertContains(listing, event.destination_display)
            self.assertNotContains(listing, "should-hide")
            detail = client.get(reverse("control_discord_outbox_detail", args=[event.pk]))
            self.assertEqual(detail.status_code, 200)
            self.assertContains(detail, "inspect:1")
            self.assertNotContains(detail, "should-hide")

    def test_outbox_status_filters(self):
        pending = queue_discord_event("NEWS", {"text": "p"}, idempotency_key="filter.p")
        sent = queue_discord_event("NEWS", {"text": "s"}, idempotency_key="filter.s")
        failed = queue_discord_event("NEWS", {"text": "f"}, idempotency_key="filter.f")
        mark_discord_sent(sent)
        failed.attempt_count = MAX_ATTEMPTS - 1
        failed.save(update_fields=["attempt_count"])
        mark_discord_failed(failed, "gone")
        client = self._login(self.owner)
        pending_page = client.get(reverse("control_discord_outbox"), {"status": "PENDING"})
        self.assertContains(pending_page, reverse("control_discord_outbox_detail", args=[pending.pk]))
        self.assertNotContains(pending_page, reverse("control_discord_outbox_detail", args=[sent.pk]))
        failed_page = client.get(reverse("control_discord_outbox"), {"status": "FAILED"})
        self.assertContains(failed_page, "gone")
        self.assertContains(failed_page, reverse("control_discord_outbox_detail", args=[failed.pk]))

    def test_owner_can_retry_failed_and_pending(self):
        failed = queue_discord_event("NEWS", {"text": "retry-f"}, idempotency_key="retry.f")
        failed.attempt_count = MAX_ATTEMPTS - 1
        failed.save(update_fields=["attempt_count"])
        mark_discord_failed(failed, "temp")
        pending = queue_discord_event("NEWS", {"text": "retry-p"}, idempotency_key="retry.p")
        mark_discord_failed(pending, "later")
        client = self._login(self.owner)
        fail_post = client.post(reverse("control_discord_outbox_retry", args=[failed.pk]))
        self.assertEqual(fail_post.status_code, 302)
        failed.refresh_from_db()
        self.assertEqual(failed.status, DiscordEvent.PENDING)
        self.assertLessEqual(failed.next_attempt_at, timezone.now())
        pend_post = client.post(reverse("control_discord_outbox_retry", args=[pending.pk]))
        self.assertEqual(pend_post.status_code, 302)
        pending.refresh_from_db()
        self.assertEqual(pending.status, DiscordEvent.PENDING)
        self.assertIn(pending.pk, {row.pk for row in pending_discord_events()})

    def test_admin_can_retry_failed_event(self):
        event = queue_discord_event("NEWS", {"text": "admin-retry"}, idempotency_key="retry.admin")
        event.attempt_count = MAX_ATTEMPTS - 1
        event.save(update_fields=["attempt_count"])
        mark_discord_failed(event, "down")
        client = self._login(self.admin)
        response = client.post(reverse("control_discord_outbox_retry", args=[event.pk]))
        self.assertEqual(response.status_code, 302)
        event.refresh_from_db()
        self.assertEqual(event.status, DiscordEvent.PENDING)

    def test_manager_cannot_open_or_retry_outbox(self):
        event = queue_discord_event("NEWS", {"text": "nope"}, idempotency_key="retry.mgr")
        client = self._login(self.manager_user)
        self.assertEqual(client.get(reverse("control_discord_outbox")).status_code, 302)
        self.assertEqual(
            client.get(reverse("control_discord_outbox_detail", args=[event.pk])).status_code,
            302,
        )
        self.assertEqual(
            client.post(reverse("control_discord_outbox_retry", args=[event.pk])).status_code,
            302,
        )
        event.refresh_from_db()
        self.assertEqual(event.attempt_count, 0)

    def test_member_cannot_open_or_retry_outbox(self):
        event = queue_discord_event("NEWS", {"text": "nope"}, idempotency_key="retry.mem")
        client = self._login(self.member_user)
        self.assertEqual(client.get(reverse("control_discord_outbox")).status_code, 302)
        self.assertEqual(
            client.post(reverse("control_discord_outbox_retry", args=[event.pk])).status_code,
            302,
        )
        event.refresh_from_db()
        self.assertEqual(event.status, DiscordEvent.PENDING)

    def test_retry_does_not_change_football_or_tokens(self):
        event = queue_discord_event("NEWS", {"text": "safe"}, idempotency_key="retry.safe")
        event.attempt_count = MAX_ATTEMPTS - 1
        event.save(update_fields=["attempt_count"])
        mark_discord_failed(event, "safe")
        tokens = self.mgr.tokens
        team_id = self.player.mgl_team_id
        retry_discord_event(event)
        self.mgr.refresh_from_db()
        self.player.refresh_from_db()
        self.assertEqual(self.mgr.tokens, tokens)
        self.assertEqual(self.player.mgl_team_id, team_id)
        self.assertFalse(self.player.is_free_agent)

    def test_totw_approval_enters_discord_event(self):
        totw = TeamOfTheWeek.objects.create(week_start=date(2026, 8, 24))
        request = RequestFactory().post("/")
        request.user = self.owner
        request.session = {}
        request._messages = FallbackStorage(request)
        approve_selected_totw(None, request, TeamOfTheWeek.objects.filter(pk=totw.pk))
        totw.refresh_from_db()
        self.assertTrue(totw.approved)
        event = DiscordEvent.objects.get(idempotency_key=f"totw.approve:{totw.pk}")
        self.assertEqual(event.status, DiscordEvent.PENDING)
        self.assertEqual(event.event_type, NewsPost.REWARD)
        self.assertTrue(NewsPost.objects.filter(title="UFL TEAM OF THE WEEK").exists())
        approve_selected_totw(None, request, TeamOfTheWeek.objects.filter(pk=totw.pk))
        self.assertEqual(DiscordEvent.objects.filter(idempotency_key=f"totw.approve:{totw.pk}").count(), 1)

    @override_settings(DISCORD_INVITE_URL="https://discord.gg/ufl-configured")
    def test_job_centre_invite_uses_configuration(self):
        self.assertEqual(job_centre_discord_invite(), "https://discord.gg/ufl-configured")
        source = Path(__file__).resolve().parent.joinpath("job_applications.py").read_text()
        self.assertNotIn("https://discord.gg/Jmf29wBafP", source)
        self.assertNotIn("JOBS_DISCORD_INVITE = ", source)

    def test_no_secret_leakage_in_control_or_source(self):
        secret = "SUPER-SECRET-BOT-TOKEN-9f3"
        event = queue_discord_event(
            "NEWS",
            {"title": "Safe", "text": "Hello", "discord_id": "999"},
            channel_key="DM",
            idempotency_key="secret.check:1",
        )
        client = self._login(self.owner)
        with mock.patch.dict(os.environ, {"DISCORD_TOKEN": secret}):
            listing = client.get(reverse("control_discord_outbox"))
            detail = client.get(reverse("control_discord_outbox_detail", args=[event.pk]))
        self.assertNotContains(listing, secret)
        self.assertNotContains(detail, secret)
        self.assertNotContains(listing, "DISCORD_TOKEN")
        self.assertNotContains(detail, "999")
        preview = event_payload_preview(event)
        self.assertNotIn("discord_id", preview)
        bot_source = Path(__file__).resolve().parents[1].joinpath("discord_bot/bot.py").read_text()
        queue_source = Path(__file__).resolve().parent.joinpath("discord_queue.py").read_text()
        self.assertNotIn("credit_manager", bot_source)
        self.assertNotIn("assign_player", bot_source)
        self.assertNotIn("StartingSquadLock", bot_source)
        self.assertNotIn("credit_manager", queue_source)
        self.assertNotIn("approve_job_application", queue_source)

    def test_channel_map_is_configurable_without_hardcoded_ids(self):
        mapping = parse_channel_map("NEWS:11,TRANSFERS:22,TRANSFER MARKET:33")
        self.assertEqual(resolve_channel_id(mapping, "TRANSFERS"), 22)
        self.assertEqual(resolve_channel_id(mapping, "TRANSFER"), 22)
        self.assertEqual(resolve_channel_id(mapping, "JOBS"), 11)
        self.assertIsNone(resolve_channel_id({}, "NEWS"))
        channel_source = Path(__file__).resolve().parent.joinpath("discord_channels.py").read_text()
        self.assertNotIn("discord.gg/", channel_source)
        self.assertNotRegex(channel_source, r"CHANNEL.*=\s*\d{6,}")
