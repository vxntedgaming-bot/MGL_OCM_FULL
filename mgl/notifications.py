"""Manager/admin notifications derived from existing pending rows.

Completing the source action (answering press, submitting a result,
selling/withdrawing a listing, or approving a control item) clears the
matching notification. No separate Notification model.
"""

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


def notifications_for_user(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return []

    items = []
    seen = set()

    def add(item):
        key = item["key"]
        if key in seen:
            return
        seen.add(key)
        items.append(item)

    for press in (
        PressConference.objects.filter(
            manager=user,
            status=ApprovalStatus.PENDING,
        )
        .select_related("team")
        .order_by("-created_at")
    ):
        add(
            {
                "key": f"press-{press.pk}",
                "kind": "PRESS CONFERENCE",
                "title": "PRESS CONFERENCE",
                "body": _press_copy(press),
                "cta": "ANSWER NOW",
                "url": reverse("answer_press", args=[press.pk]),
            }
        )

    club = club_for_user(user)
    if club is not None:
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
            add(
                {
                    "key": f"result-{fixture.pk}",
                    "kind": "RESULT SUBMISSION",
                    "title": "RESULT SUBMISSION",
                    "body": (
                        f"Your fixture vs {opponent.name} is ready for submission."
                    ),
                    "cta": "SUBMIT RESULT",
                    "url": reverse("submit_match", args=[fixture.pk]),
                }
            )

        for listing in (
            PlayerListing.objects.filter(team=club, status=PlayerListing.LIVE)
            .select_related("player", "team")
            .order_by("-created_at")
        ):
            add(
                {
                    "key": f"listing-{listing.pk}",
                    "kind": "TRANSFER",
                    "title": "TRANSFER",
                    "body": (
                        f"{listing.player.name} is listed on the transfer market."
                    ),
                    "cta": "VIEW",
                    "url": reverse("team_management"),
                }
            )

    if getattr(user, "role", None) in (User.OWNER, User.ADMIN):
        for listing in (
            PlayerListing.objects.filter(status=PlayerListing.PENDING)
            .select_related("player", "team")
            .order_by("-created_at")[:12]
        ):
            add(
                {
                    "key": f"admin-listing-{listing.pk}",
                    "kind": "TRANSFER",
                    "title": "TRANSFER",
                    "body": (
                        f"{listing.team.name} listed {listing.player.name} "
                        "and it needs approval."
                    ),
                    "cta": "REVIEW",
                    "url": reverse("control_centre"),
                }
            )
        for submission in (
            MatchSubmission.objects.filter(status=ApprovalStatus.PENDING)
            .select_related("fixture__home_team", "fixture__away_team")
            .order_by("-submitted_at")[:12]
        ):
            fixture = submission.fixture
            add(
                {
                    "key": f"admin-result-{submission.pk}",
                    "kind": "RESULT",
                    "title": "RESULT",
                    "body": (
                        f"{fixture.home_team.name} vs {fixture.away_team.name} "
                        "needs approval."
                    ),
                    "cta": "REVIEW",
                    "url": reverse("control_centre"),
                }
            )
        for application in (
            ClubApplication.objects.filter(status=ApprovalStatus.PENDING)
            .select_related("manager", "team")
            .order_by("-created_at")[:12]
        ):
            add(
                {
                    "key": f"admin-job-{application.pk}",
                    "kind": "ADMIN",
                    "title": "CLUB APPLICATION",
                    "body": (
                        f"{application.manager.display_name} applied for "
                        f"{application.team.name}."
                    ),
                    "cta": "REVIEW",
                    "url": reverse("control_centre"),
                }
            )
        for application in ManagerApplication.objects.filter(
            status=ManagerApplication.PENDING
        ).order_by("-id")[:12]:
            add(
                {
                    "key": f"admin-manager-{application.pk}",
                    "kind": "ADMIN",
                    "title": "MANAGER APPLICATION",
                    "body": (
                        f"{application.display_name} is waiting for "
                        "manager approval."
                    ),
                    "cta": "REVIEW",
                    "url": reverse("control_centre"),
                }
            )

    return items
