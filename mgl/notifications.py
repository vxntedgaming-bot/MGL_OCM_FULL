"""Manager/admin notifications.

Pending action items are still derived from live MGL rows (press, results,
listings, control queues). Those items are persisted into ManagerNotification
so each manager has a private inbox with read/unread state.

Real MGL actions also write inbox rows through notify_user(). Do not invent
demo notifications. To add a future pending action, append a NotificationSource
to NOTIFICATION_SOURCES.
"""

from dataclasses import dataclass

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from managers.models import ManagerApplication
from mgl.market import club_for_user
from mgl.services import manager_for_user
from mgl.models import (
    ApprovalStatus,
    ClubApplication,
    Fixture,
    ManagerNotification,
    MatchSubmission,
    PlayerListing,
    PressConference,
)


@dataclass(frozen=True)
class NotificationItem:
    key: str
    type: str
    title: str
    description: str
    url: str
    cta: str = "VIEW"
    actor: str = ""
    created_at: object = None
    team_id: int = None
    player_id: int = None

    @property
    def complete(self):
        """Pending sources only yield incomplete items."""
        return False

    def as_template(self):
        return {
            "key": self.key,
            "type": self.type,
            "kind": self.type,
            "title": self.title,
            "description": self.description,
            "body": self.description,
            "url": self.url,
            "cta": self.cta,
            "complete": self.complete,
            "actor": self.actor,
            "created_at": self.created_at,
            "team_id": self.team_id,
            "player_id": self.player_id,
        }


class NotificationSource:
    """Override pending_for(user) in a subclass to register a new action."""

    def pending_for(self, user):
        return []


def _press_copy(press):
    if press.trigger == PressConference.MATCH:
        return "Sky Sports have a question for you after your latest result."
    if press.trigger == PressConference.APPOINTMENT:
        club = press.team.name if press.team_id else "your new club"
        return f"Sky Sports want to speak to you after your appointment at {club}."
    if press.trigger == PressConference.SIGNING:
        return "Sky Sports have a question for you after your latest signing."
    if press.trigger == PressConference.ODD_MATCHDAY:
        return "Sky Sports have a question for you."
    return "You have a press conference question waiting."


class PressConferenceSource(NotificationSource):
    def pending_for(self, user):
        for press in (
            PressConference.objects.filter(
                manager=user,
                status=ApprovalStatus.PENDING,
            )
            .select_related("team")
            .order_by("-created_at")
        ):
            yield NotificationItem(
                key=f"press-{press.pk}",
                type="PRESS CONFERENCE",
                title="PRESS CONFERENCE",
                description=_press_copy(press),
                url=reverse("answer_press", args=[press.pk]),
                cta="ANSWER NOW",
                actor="Sky Sports",
                created_at=press.created_at,
                team_id=press.team_id,
            )


class ResultSubmissionSource(NotificationSource):
    def pending_for(self, user):
        club = club_for_user(user)
        if club is None:
            return
        club_fixtures = Fixture.objects.filter(
            Q(home_team=club) | Q(away_team=club)
        )
        submitted_ids = set(
            MatchSubmission.objects.filter(fixture__in=club_fixtures).values_list(
                "fixture_id", flat=True
            )
        )
        for fixture in (
            club_fixtures.filter(status="SCHEDULED", is_released=True)
            .select_related("home_team", "away_team")
            .order_by("matchweek", "id")
        ):
            if fixture.id in submitted_ids:
                continue
            opponent = (
                fixture.away_team
                if fixture.home_team_id == club.id
                else fixture.home_team
            )
            yield NotificationItem(
                key=f"result-{fixture.pk}",
                type="RESULT SUBMISSION",
                title="RESULT SUBMISSION",
                description=(
                    f"Your fixture vs {opponent.name} is ready for submission."
                ),
                url=reverse("submit_match", args=[fixture.pk]),
                cta="SUBMIT RESULT",
                actor="MGL Fixtures",
                created_at=fixture.created_at,
                team_id=club.id,
            )


class LiveListingSource(NotificationSource):
    def pending_for(self, user):
        club = club_for_user(user)
        if club is None:
            return
        for listing in (
            PlayerListing.objects.filter(team=club, status=PlayerListing.LIVE)
            .select_related("player", "team")
            .order_by("-created_at")
        ):
            yield NotificationItem(
                key=f"listing-{listing.pk}",
                type="TRANSFER",
                title="TRANSFER",
                description=(
                    f"{listing.player.name} is listed on the transfer market."
                ),
                url=reverse("team_management"),
                cta="VIEW",
                actor=listing.team.name,
                created_at=listing.created_at,
                team_id=listing.team_id,
                player_id=listing.player_id,
            )


class ControlQueueSource(NotificationSource):
    def pending_for(self, user):
        if getattr(user, "role", None) not in (User.OWNER, User.ADMIN):
            return
        for listing in (
            PlayerListing.objects.filter(status=PlayerListing.PENDING)
            .select_related("player", "team")
            .order_by("-created_at")[:12]
        ):
            yield NotificationItem(
                key=f"admin-listing-{listing.pk}",
                type="TRANSFER",
                title="TRANSFER",
                description=(
                    f"{listing.team.name} listed {listing.player.name} "
                    "and it needs approval."
                ),
                url=reverse("control_centre"),
                cta="REVIEW",
                actor=listing.team.name,
                created_at=listing.created_at,
                team_id=listing.team_id,
                player_id=listing.player_id,
            )
        for submission in (
            MatchSubmission.objects.filter(status=ApprovalStatus.PENDING)
            .select_related("fixture__home_team", "fixture__away_team", "submitted_by")
            .order_by("-submitted_at")[:12]
        ):
            fixture = submission.fixture
            yield NotificationItem(
                key=f"admin-result-{submission.pk}",
                type="RESULT",
                title="RESULT",
                description=(
                    f"{fixture.home_team.name} vs {fixture.away_team.name} "
                    "needs approval."
                ),
                url=reverse("control_centre"),
                cta="REVIEW",
                actor=submission.submitted_by.username if submission.submitted_by_id else "Manager",
                created_at=submission.submitted_at,
                team_id=fixture.home_team_id,
            )
        for application in (
            ClubApplication.objects.filter(status=ApprovalStatus.PENDING)
            .select_related("manager", "team")
            .order_by("-created_at")[:12]
        ):
            yield NotificationItem(
                key=f"admin-job-{application.pk}",
                type="ADMIN",
                title="CLUB APPLICATION",
                description=(
                    f"{application.manager.display_name} applied for "
                    f"{application.team.name}."
                ),
                url=reverse("control_centre"),
                cta="REVIEW",
                actor=application.manager.display_name,
                created_at=application.created_at,
                team_id=application.team_id,
            )
        for application in ManagerApplication.objects.filter(
            status=ManagerApplication.PENDING
        ).order_by("-id")[:12]:
            yield NotificationItem(
                key=f"admin-manager-{application.pk}",
                type="ADMIN",
                title="MANAGER APPLICATION",
                description=(
                    f"{application.display_name} is waiting for "
                    "manager approval."
                ),
                url=reverse("control_centre"),
                cta="REVIEW",
                actor=application.display_name,
            )


NOTIFICATION_SOURCES = (
    PressConferenceSource(),
    ResultSubmissionSource(),
    LiveListingSource(),
    ControlQueueSource(),
)


def notifications_for_user(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    items = []
    seen = set()
    for source in NOTIFICATION_SOURCES:
        for item in source.pending_for(user):
            if item.complete or item.key in seen:
                continue
            seen.add(item.key)
            items.append(item.as_template())
    return items


def notify_user(
    user,
    *,
    source_key,
    notification_type,
    title,
    message,
    action_url="",
    action_label="VIEW",
    actor="",
    team=None,
    player=None,
    is_action=False,
):
    """Create a manager-owned inbox row. Idempotent on (recipient, source_key)."""
    if user is None or not getattr(user, "pk", None):
        return None
    team_id = getattr(team, "pk", team)
    player_id = getattr(player, "pk", player)
    obj, _created = ManagerNotification.objects.get_or_create(
        recipient=user,
        source_key=source_key,
        defaults={
            "notification_type": notification_type,
            "title": title,
            "message": message,
            "actor": actor or "",
            "action_url": action_url or "",
            "action_label": action_label or "VIEW",
            "team_id": team_id,
            "player_id": player_id,
            "is_action": is_action,
        },
    )
    return obj


def inbox_queryset_for_user(user):
    """Backend ownership filter. Never accept another user's id from the URL."""
    if user is None or not getattr(user, "pk", None):
        return ManagerNotification.objects.none()
    return ManagerNotification.objects.filter(recipient=user).select_related(
        "team",
        "player",
    )


def sync_pending_notifications(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    pending = notifications_for_user(user)
    pending_keys = [row["key"] for row in pending]
    existing = set(
        ManagerNotification.objects.filter(
            recipient=user,
            source_key__in=pending_keys,
        ).values_list("source_key", flat=True)
    ) if pending_keys else set()
    to_create = []
    for row in pending:
        if row["key"] in existing:
            continue
        to_create.append(
            ManagerNotification(
                recipient=user,
                source_key=row["key"],
                notification_type=row["type"],
                title=row["title"],
                message=row["description"],
                actor=row.get("actor") or "",
                action_url=row.get("url") or "",
                action_label=row.get("cta") or "VIEW",
                team_id=row.get("team_id"),
                player_id=row.get("player_id"),
                is_action=True,
            )
        )
    if to_create:
        ManagerNotification.objects.bulk_create(to_create, ignore_conflicts=True)
    if pending_keys:
        ManagerNotification.objects.filter(
            recipient=user,
            is_action=True,
            read_at__isnull=True,
        ).exclude(source_key__in=pending_keys).update(read_at=timezone.now())
    else:
        ManagerNotification.objects.filter(
            recipient=user,
            is_action=True,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
    return pending


def unread_count_for_user(user):
    sync_pending_notifications(user)
    return inbox_queryset_for_user(user).filter(read_at__isnull=True).count()


def attach_press_briefs(items, user):
    """Attach the viewer's own PressConference rows to matching inbox items."""
    press_ids = []
    for item in items:
        key = getattr(item, "source_key", "") or ""
        if key.startswith("press-"):
            suffix = key.split("-", 1)[1]
            if suffix.isdigit():
                press_ids.append(int(suffix))
    found = {}
    if press_ids and user is not None:
        found = {
            row.pk: row
            for row in PressConference.objects.filter(
                pk__in=press_ids,
                manager=user,
            ).select_related("team", "manager")
        }
    application = manager_for_user(user) if user is not None else None
    manager_name = (
        application.display_name
        if application
        else getattr(user, "username", "")
    )
    for item in items:
        key = getattr(item, "source_key", "") or ""
        press = None
        if key.startswith("press-"):
            suffix = key.split("-", 1)[1]
            if suffix.isdigit():
                press = found.get(int(suffix))
        item.press = press
        item.is_press_brief = press is not None
        item.press_manager_name = manager_name
        item.press_pending = bool(
            press and press.status == ApprovalStatus.PENDING
        )
    return items


def inbox_for_user(user):
    sync_pending_notifications(user)
    return attach_press_briefs(list(inbox_queryset_for_user(user)), user)


def mark_inbox_read(user):
    now = timezone.now()
    inbox_queryset_for_user(user).filter(read_at__isnull=True).update(read_at=now)


def mark_action_complete(user, source_key):
    if user is None or not source_key:
        return
    inbox_queryset_for_user(user).filter(
        source_key=source_key,
        read_at__isnull=True,
    ).update(read_at=timezone.now())
