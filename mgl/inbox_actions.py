"""Server-side Accept/Reject for private manager notifications."""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from mgl.market import respond_to_transfer_offer
from mgl.models import ApprovalStatus, ManagerNotification, MatchSubmission
from mgl.notifications import inbox_queryset_for_user, mark_notification_response, notify_user


class InboxActionError(ValueError):
    pass


def notification_for_recipient(user, notification_id):
    return inbox_queryset_for_user(user).filter(pk=notification_id).first()


@transaction.atomic
def respond_to_match_notification(notification, user, accept):
    fixture = notification.fixture
    if fixture is None:
        raise InboxActionError("This notification is missing match details.")
    submission = (
        MatchSubmission.objects.select_for_update()
        .select_related("fixture__home_team", "fixture__away_team", "submitted_by")
        .filter(fixture=fixture)
        .first()
    )
    if submission is None:
        raise InboxActionError("That match submission is no longer available.")
    if submission.status != ApprovalStatus.PENDING:
        raise InboxActionError("The league office has already reviewed this result.")
    home_id = fixture.home_team.manager_id
    away_id = fixture.away_team.manager_id
    if user.id not in {home_id, away_id}:
        raise PermissionDenied("You can only respond to a result that involves your club.")
    if user.id == submission.submitted_by_id:
        raise PermissionDenied("You cannot accept or reject your own match submission.")
    opponent_id = away_id if submission.submitted_by_id == home_id else home_id
    if user.id != opponent_id:
        raise PermissionDenied("Only the opposing manager can respond to this result.")
    if submission.opponent_response in {
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
    }:
        raise InboxActionError("This result has already been accepted or rejected.")
    if notification.response_status != ManagerNotification.PENDING:
        raise InboxActionError("This notification has already been handled.")

    now = timezone.now()
    status = ApprovalStatus.APPROVED if accept else ApprovalStatus.REJECTED
    inbox_status = (
        ManagerNotification.ACCEPTED if accept else ManagerNotification.REJECTED
    )
    submission.opponent_response = status
    submission.opponent_responded_at = now
    submission.opponent_responded_by = user
    submission.save(
        update_fields=[
            "opponent_response",
            "opponent_responded_at",
            "opponent_responded_by",
        ]
    )
    mark_notification_response(user, notification.source_key, inbox_status)

    fixture_name = f"{fixture.home_team.name} vs {fixture.away_team.name}"
    if accept:
        title = "RESULT CONFIRMED"
        message = (
            f"{fixture_name} was confirmed by the opposing manager. "
            "It still needs Owner/Admin approval before it is official."
        )
    else:
        title = "RESULT DISPUTED"
        message = (
            f"{fixture_name} was rejected by the opposing manager. "
            "The league office still has to review the original submission."
        )
    notify_user(
        submission.submitted_by,
        source_key=f"score-response-{submission.pk}",
        notification_type="MATCH",
        title=title,
        message=message,
        actor=user.username,
        team=fixture.home_team if user.id == fixture.away_team.manager_id else fixture.away_team,
        fixture=fixture,
        details=notification.details,
    )
    return submission


def respond_to_inbox_notification(user, notification, accept):
    if notification is None:
        raise PermissionDenied("That notification does not belong to your account.")
    if notification.recipient_id != user.id:
        raise PermissionDenied("That notification does not belong to your account.")
    if notification.response_status != ManagerNotification.PENDING:
        raise InboxActionError("This notification has already been handled.")

    source = notification.source_key or ""
    if source.startswith("score-submitted-") or notification.fixture_id:
        return respond_to_match_notification(notification, user, accept)
    if source.startswith("transfer-offer-") or notification.listing_id:
        listing = notification.listing
        if listing is None:
            raise InboxActionError("This notification is missing transfer details.")
        return respond_to_transfer_offer(listing, user, accept)
    raise InboxActionError("This notification does not require a response.")
