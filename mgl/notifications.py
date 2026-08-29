"""Manager/admin notifications derived from existing pending rows.

No separate Notification model. Each source yields incomplete items;
completing the underlying row (answer, submit, sell, approve) means the
source no longer returns that key.

To add a future action (for example an incoming transfer offer once a
backend offer model exists), append a NotificationSource to
NOTIFICATION_SOURCES. Do not invent offer rows here.
"""

from dataclasses import dataclass

from django.db.models import Q
from django.urls import reverse

from accounts.models import User
from managers.models import ManagerApplication
from mgl.market import club_for_user
from mgl.models import (
    ApprovalStatus,
    ClubApplication,
    Fixture,
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
            )
        for submission in (
            MatchSubmission.objects.filter(status=ApprovalStatus.PENDING)
            .select_related("fixture__home_team", "fixture__away_team")
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
