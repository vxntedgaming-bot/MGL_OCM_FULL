"""Manager verification snapshot from existing UFL records. No schema changes."""

from managers.models import ManagerApplication
from mgl.market import club_for_user
from mgl.models import ApprovalStatus, ClubApplication
from mgl.permissions import approved_manager


NOT_VERIFIED = "NOT VERIFIED"
PENDING = "PENDING"
VERIFIED = "VERIFIED"
REJECTED = "REJECTED"
SUSPENDED = "SUSPENDED"


def _latest_job(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        ClubApplication.objects.filter(manager__user=user)
        .select_related("team", "manager")
        .order_by("-created_at")
        .first()
    )


def verification_snapshot(user):
    identity = None
    if user is not None and getattr(user, "is_authenticated", False):
        identity = ManagerApplication.objects.filter(user=user).first()
    job = _latest_job(user)
    club = club_for_user(user) if user is not None else None
    manager = approved_manager(user) if user is not None else None

    if user is None or not getattr(user, "is_authenticated", False):
        status = NOT_VERIFIED
    elif not getattr(user, "is_active", True):
        status = SUSPENDED
    elif manager and club:
        status = VERIFIED
    elif job and job.status == ApprovalStatus.PENDING:
        status = PENDING
    elif identity and identity.status == ManagerApplication.PENDING and not club:
        status = PENDING
    elif job and job.status == ApprovalStatus.REJECTED:
        status = REJECTED
    elif identity and identity.status == ManagerApplication.REJECTED:
        status = REJECTED
    elif manager:
        status = VERIFIED
    else:
        status = NOT_VERIFIED

    slug = {
        VERIFIED: "verified",
        PENDING: "pending",
        REJECTED: "rejected",
        SUSPENDED: "suspended",
    }.get(status, "unverified")

    return {
        "status": status,
        "status_slug": slug,
        "account_created": bool(user and getattr(user, "is_authenticated", False)),
        "application_submitted": bool(identity or job),
        "club": club,
        "club_name": club.name if club else (job.team.name if job and job.team_id else ""),
        "identity": identity,
        "job": job,
        "account_status": "ACTIVE" if getattr(user, "is_active", False) else "SUSPENDED",
        "is_verified": status == VERIFIED,
    }
