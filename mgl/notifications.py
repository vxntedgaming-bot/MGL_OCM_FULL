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
    listing_id: int = None

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
            "listing_id": self.listing_id,
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
    if press.trigger == PressConference.RELEASE:
        return "Sky Sports have a question for you after a player release."
    if press.trigger == PressConference.DAILY:
        return "MGL Sports has a question for you."
    if press.trigger == PressConference.ODD_MATCHDAY:
        return "Sky Sports have a question for you."
    return "You have a press conference question waiting."


class PressConferenceSource(NotificationSource):
    def pending_for(self, user):
        now = timezone.now()
        for press in (
            PressConference.objects.filter(
                manager=user,
                status=ApprovalStatus.PENDING,
                answer="",
            )
            .filter(Q(available_at__isnull=True) | Q(available_at__lte=now))
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
            MatchSubmission.objects.filter(fixture__in=club_fixtures)
            .exclude(status=ApprovalStatus.REJECTED)
            .values_list("fixture_id", flat=True)
        )
        rejected_other_ids = set(
            MatchSubmission.objects.filter(
                fixture__in=club_fixtures,
                status=ApprovalStatus.REJECTED,
            )
            .exclude(submitted_by=user)
            .values_list("fixture_id", flat=True)
        )
        submitted_ids |= rejected_other_ids
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
            PlayerListing.objects.filter(
                status=PlayerListing.PENDING,
                reserved_buyer__isnull=False,
            )
            .select_related("player", "team", "reserved_buyer")
            .order_by("-created_at")[:12]
        ):
            yield NotificationItem(
                key=f"admin-listing-{listing.pk}",
                type="TRANSFER",
                title="TRANSFER REQUEST",
                description=(
                    f"{listing.reserved_buyer.display_name} wants {listing.player.name} "
                    f"from {listing.team.name}."
                ),
                url=reverse("control_centre"),
                cta="REVIEW",
                actor=listing.team.name,
                created_at=listing.created_at,
                team_id=listing.team_id,
                player_id=listing.player_id,
                listing_id=listing.pk,
            )
        for submission in (
            MatchSubmission.objects.filter(
                status=ApprovalStatus.PENDING,
                opponent_response=ApprovalStatus.APPROVED,
            )
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
                    "needs Owner/Admin approval."
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
    fixture=None,
    listing=None,
    details=None,
    response_status="",
    is_action=False,
):
    """Create a manager-owned inbox row. Idempotent on (recipient, source_key)."""
    if user is None or not getattr(user, "pk", None):
        return None
    team_id = getattr(team, "pk", team)
    player_id = getattr(player, "pk", player)
    fixture_id = getattr(fixture, "pk", fixture)
    listing_id = getattr(listing, "pk", listing)
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
            "fixture_id": fixture_id,
            "listing_id": listing_id,
            "details": details or {},
            "response_status": response_status or ManagerNotification.NONE,
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
        "fixture",
        "fixture__home_team",
        "fixture__away_team",
        "listing",
        "listing__player",
        "listing__team",
        "listing__reserved_buyer",
        "listing__seller",
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
        is_admin_listing = row["key"].startswith("admin-listing-")
        is_admin_result = row["key"].startswith("admin-result-")
        is_admin_action = is_admin_listing or is_admin_result
        if row["key"] in existing:
            if is_admin_action:
                ManagerNotification.objects.filter(
                    recipient=user,
                    source_key=row["key"],
                ).exclude(response_status__in=[
                    ManagerNotification.ACCEPTED,
                    ManagerNotification.REJECTED,
                ]).update(
                    listing_id=row.get("listing_id"),
                    response_status=ManagerNotification.PENDING,
                    is_action=True,
                    title=row["title"],
                    message=row["description"],
                )
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
                listing_id=row.get("listing_id"),
                is_action=True,
                response_status=(
                    ManagerNotification.PENDING
                    if is_admin_action
                    else ManagerNotification.NONE
                ),
            )
        )
    if to_create:
        ManagerNotification.objects.bulk_create(to_create, ignore_conflicts=True)
    stale_actions = ManagerNotification.objects.filter(
        recipient=user,
        is_action=True,
        read_at__isnull=True,
    ).exclude(response_status=ManagerNotification.PENDING)
    if pending_keys:
        stale_actions.exclude(source_key__in=pending_keys).update(read_at=timezone.now())
    else:
        stale_actions.update(read_at=timezone.now())
    return pending


def unread_count_for_user(user):
    from mgl.runtime_tick import runtime_tick

    runtime_tick(user)
    sync_pending_notifications(user)
    return (
        inbox_queryset_for_user(user)
        .filter(read_at__isnull=True)
        .exclude(
            response_status__in=[
                ManagerNotification.ACCEPTED,
                ManagerNotification.REJECTED,
            ]
        )
        .count()
    )


def pending_action_count_for_user(user):
    sync_pending_notifications(user)
    return inbox_queryset_for_user(user).filter(
        response_status=ManagerNotification.PENDING
    ).count()


def mark_notification_response(user, source_key, status):
    if user is None or not source_key:
        return 0
    now = timezone.now()
    return inbox_queryset_for_user(user).filter(
        source_key=source_key,
        response_status=ManagerNotification.PENDING,
    ).update(
        response_status=status,
        actioned_at=now,
        read_at=now,
    )


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
            press
            and press.status == ApprovalStatus.PENDING
            and not (press.answer or "").strip()
        )
    return items


def _detail_rows(item):
    details = getattr(item, "details", None) or {}
    rows = []
    mapping = (
        ("scoreline", "Submitted score"),
        ("fixture", "Match"),
        ("submitted_by", "Submitted by"),
        ("submitted_at", "Submitted"),
        ("match_stats", "Match stats"),
        ("player", "Player"),
        ("buyer_manager", "Buyer manager"),
        ("requesting_club", "Requesting club"),
        ("current_club", "Current club"),
        ("transfer_type", "Transfer type"),
        ("buyer_receives", "Buying club receives"),
        ("seller_receives", "Selling club receives"),
        ("offered_player", "Players offered"),
        ("amount", "Proposed amount"),
    )
    for key, label in mapping:
        value = details.get(key)
        if value not in (None, ""):
            if key == "amount":
                rows.append((label, f"{value} TKN"))
            else:
                rows.append((label, value))
    if item.team_id and not details.get("current_club"):
        rows.append(("Team", item.team.name))
    if item.player_id and not details.get("player"):
        rows.append(("Player", item.player.name))
    return rows


def decorate_inbox_items(items):
    for item in items:
        status = getattr(item, "response_status", "") or ManagerNotification.NONE
        item.can_respond = status == ManagerNotification.PENDING
        source = getattr(item, "source_key", "") or ""
        if status == ManagerNotification.PENDING:
            item.status_label = "PENDING"
        elif status == ManagerNotification.ACCEPTED:
            item.status_label = "ACCEPTED"
        elif status == ManagerNotification.REJECTED:
            item.status_label = "REJECTED"
        else:
            item.status_label = ""
        item.detail_rows = _detail_rows(item)
        kind = (item.notification_type or "").upper()
        if "MATCH" in kind or "RESULT" in kind or "SCORE" in kind:
            item.card_kind = "match"
        elif "TRANSFER" in kind:
            item.card_kind = "transfer"
        else:
            item.card_kind = "notice"
    return items


def inbox_for_user(user):
    sync_pending_notifications(user)
    items = attach_press_briefs(list(inbox_queryset_for_user(user)), user)
    return decorate_inbox_items(items)


def _match_submission_details(fixture, submission, submitted_by):
    rows = {row.team_id: row for row in submission.team_stats.all()}
    home = rows.get(fixture.home_team_id)
    away = rows.get(fixture.away_team_id)
    home_goals = getattr(home, "goals", 0)
    away_goals = getattr(away, "goals", 0)
    submitter_team = (
        fixture.home_team
        if submitted_by.id == fixture.home_team.manager_id
        else fixture.away_team
    )
    submitted_at = submission.submitted_at
    if submitted_at is not None:
        submitted_label = timezone.localtime(submitted_at).strftime("%d %b %Y %H:%M")
    else:
        submitted_label = ""
    return {
        "fixture": f"{fixture.home_team.name} vs {fixture.away_team.name}",
        "scoreline": (
            f"{fixture.home_team.name} {home_goals}–{away_goals} {fixture.away_team.name}"
        ),
        "home_team": fixture.home_team.name,
        "away_team": fixture.away_team.name,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "submitter_club": submitter_team.name,
        "submitted_by": getattr(submitted_by, "username", "") or submitter_team.name,
        "submitted_at": submitted_label,
        "match_stats": (
            f"Shots {getattr(home, 'shots', 0)}-{getattr(away, 'shots', 0)} · "
            f"Possession {getattr(home, 'possession', 0)}%-{getattr(away, 'possession', 0)}%"
        ),
    }


def reopen_notification(user, source_key, **kwargs):
    existing = ManagerNotification.objects.filter(
        recipient=user,
        source_key=source_key,
    ).first()
    if existing is None:
        return notify_user(user, source_key=source_key, **kwargs)
    existing.notification_type = kwargs.get("notification_type", existing.notification_type)
    existing.title = kwargs.get("title", existing.title)
    existing.message = kwargs.get("message", existing.message)
    existing.actor = kwargs.get("actor", existing.actor) or ""
    existing.action_url = kwargs.get("action_url", existing.action_url) or ""
    existing.action_label = kwargs.get("action_label", existing.action_label) or "VIEW"
    existing.team = kwargs.get("team", existing.team)
    existing.player = kwargs.get("player", existing.player)
    existing.fixture = kwargs.get("fixture", existing.fixture)
    existing.listing = kwargs.get("listing", existing.listing)
    existing.details = kwargs.get("details") or {}
    existing.response_status = kwargs.get("response_status") or ManagerNotification.PENDING
    existing.is_action = kwargs.get("is_action", True)
    existing.read_at = None
    existing.actioned_at = None
    existing.save()
    return existing


def notify_opponent_of_score_submission(fixture, submission, submitted_by):
    opponent_team = (
        fixture.away_team
        if submitted_by.id == fixture.home_team.manager_id
        else fixture.home_team
    )
    submitter_team = (
        fixture.home_team
        if submitted_by.id == fixture.home_team.manager_id
        else fixture.away_team
    )
    from django.urls import reverse

    return reopen_notification(
        opponent_team.manager,
        f"score-submitted-{fixture.pk}",
        notification_type="MATCH",
        title="Match Result Submitted",
        message=(
            f"{submitter_team.name} has submitted a match result involving your team."
        ),
        actor=submitter_team.name,
        action_url=reverse("manager_notifications"),
        action_label="REVIEW",
        team=opponent_team,
        fixture=fixture,
        is_action=True,
        response_status=ManagerNotification.PENDING,
        details=_match_submission_details(fixture, submission, submitted_by),
    )


def notify_admins_of_confirmed_result(submission):
    fixture = submission.fixture
    details = _match_submission_details(fixture, submission, submission.submitted_by)
    from django.urls import reverse

    notices = []
    for user in User.objects.filter(
        role__in=[User.OWNER, User.ADMIN],
        is_active=True,
    ):
        notices.append(
            reopen_notification(
                user,
                f"admin-result-{submission.pk}",
                notification_type="RESULT",
                title="RESULT READY FOR APPROVAL",
                message=(
                    f"{details['scoreline']} was confirmed by the opposing manager "
                    "and needs Owner/Admin approval."
                ),
                actor=details.get("submitted_by") or "Manager",
                action_url=reverse("control_centre"),
                action_label="REVIEW",
                team=fixture.home_team,
                fixture=fixture,
                is_action=True,
                response_status=ManagerNotification.PENDING,
                details=details,
            )
        )
    return notices


def close_admin_result_notices(submission, status):
    now = timezone.now()
    return ManagerNotification.objects.filter(
        source_key=f"admin-result-{submission.pk}",
        response_status=ManagerNotification.PENDING,
    ).update(
        response_status=status,
        actioned_at=now,
        read_at=now,
    )


def mark_inbox_read(user):
    now = timezone.now()
    inbox_queryset_for_user(user).filter(read_at__isnull=True).update(read_at=now)


def mark_notification_read(user, notification_id):
    now = timezone.now()
    return inbox_queryset_for_user(user).filter(
        pk=notification_id,
        read_at__isnull=True,
    ).update(read_at=now)


def mark_action_complete(user, source_key):
    if user is None or not source_key:
        return
    inbox_queryset_for_user(user).filter(
        source_key=source_key,
        read_at__isnull=True,
    ).update(read_at=timezone.now())
