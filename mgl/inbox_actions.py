"""Server-side Accept/Reject for private manager notifications."""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from mgl.admin import approve_match_submission, reject_match_submission
from mgl.market import approve_listing, reject_listing, respond_to_transfer_offer
from mgl.models import ApprovalStatus, ManagerNotification, MatchSubmission, PlayerListing
from mgl.notifications import (
    inbox_queryset_for_user,
    mark_notification_response,
    notify_admins_of_confirmed_result,
    notify_user,
)


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
        notify_admins_of_confirmed_result(submission)
    else:
        submission.status = ApprovalStatus.REJECTED
        submission.save(update_fields=["status"])
        title = "RESULT REJECTED"
        message = (
            f"{fixture_name} was rejected by the opposing manager. "
            "Correct the score and submit it again. The league office will not see it until the opponent approves."
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
    if source.startswith("admin-listing-"):
        return respond_to_admin_listing_notification(notification, user, accept)
    if source.startswith("admin-result-"):
        return respond_to_admin_result_notification(notification, user, accept)
    if source.startswith("score-submitted-") or (
        notification.fixture_id and not source.startswith("admin-")
    ):
        return respond_to_match_notification(notification, user, accept)
    if source.startswith("transfer-offer-") or notification.listing_id:
        listing = notification.listing
        if listing is None:
            raise InboxActionError("This notification is missing transfer details.")
        return respond_to_transfer_offer(listing, user, accept)
    raise InboxActionError("This notification does not require a response.")


@transaction.atomic
def respond_to_admin_listing_notification(notification, user, accept):
    if getattr(user, "role", None) not in (User.OWNER, User.ADMIN):
        raise PermissionDenied("Only an owner or admin can approve a sale listing.")
    listing = notification.listing
    if listing is None:
        suffix = (notification.source_key or "").rsplit("-", 1)[-1]
        if suffix.isdigit():
            listing = PlayerListing.objects.filter(pk=int(suffix)).first()
    if listing is None:
        raise InboxActionError("This notification is missing transfer details.")
    if accept:
        result = approve_listing(listing, user)
        inbox_status = ManagerNotification.ACCEPTED
    else:
        result = reject_listing(listing, user)
        inbox_status = ManagerNotification.REJECTED
    mark_notification_response(user, notification.source_key, inbox_status)
    return result


@transaction.atomic
def respond_to_admin_result_notification(notification, user, accept):
    if getattr(user, "role", None) not in (User.OWNER, User.ADMIN):
        raise PermissionDenied("Only an owner or admin can approve a match result.")
    submission = None
    if notification.fixture_id:
        submission = (
            MatchSubmission.objects.select_for_update()
            .filter(fixture_id=notification.fixture_id)
            .first()
        )
    if submission is None:
        suffix = (notification.source_key or "").rsplit("-", 1)[-1]
        if suffix.isdigit():
            submission = MatchSubmission.objects.select_for_update().filter(pk=int(suffix)).first()
    if submission is None:
        raise InboxActionError("That match submission is no longer available.")
    if accept:
        ok, message = approve_match_submission(submission, user)
        inbox_status = ManagerNotification.ACCEPTED
    else:
        ok, message = reject_match_submission(submission, user)
        inbox_status = ManagerNotification.REJECTED
    if not ok:
        raise InboxActionError(message)
    mark_notification_response(user, notification.source_key, inbox_status)
    return submission
