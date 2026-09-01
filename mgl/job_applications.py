"""Official UFL Job Application (DEC-041).

ClubApplication is the single application process for becoming a Manager.
ManagerApplication remains the token/identity row created at registration.
It is not a second Admin approval gate on the official path.
"""

from django.db import transaction
from django.utils import timezone

from managers.models import ManagerApplication
from managers.services import STARTING_TOKENS, approve_manager_application

from .models import ApprovalStatus, ClubApplication


GAMES_PER_WEEK_CHOICES = ("1-3", "3-5", "6+")
GAMES_PER_WEEK_LABELS = {
    "1-3": "1–3",
    "3-5": "3–5",
    "6+": "6+",
}


def job_centre_discord_invite():
    """Public invite from Site Management / DISCORD_INVITE_URL. Not a secret."""
    from mgl.site_cms import resolved_discord_invite

    return resolved_discord_invite()


def games_per_week_options():
    return [(value, GAMES_PER_WEEK_LABELS[value]) for value in GAMES_PER_WEEK_CHOICES]


def pending_job_application(manager):
    if manager is None:
        return None
    return (
        manager.club_applications.filter(status=ApprovalStatus.PENDING)
        .select_related("team", "team__league")
        .order_by("-created_at")
        .first()
    )


def latest_job_application(manager):
    if manager is None:
        return None
    return (
        manager.club_applications.select_related("team", "team__league")
        .order_by("-created_at")
        .first()
    )


def parse_club_application(post):
    gamertag = (post.get("gamertag") or "").strip()
    discord_username = (post.get("discord_username") or "").strip()
    discord_id = (post.get("discord_id") or "").strip()
    games_per_week = (post.get("games_per_week") or "").strip()
    referred_by = (post.get("referred_by") or "").strip()
    new_gen = (post.get("new_gen_confirmed") or "").strip().lower() in {
        "on",
        "1",
        "true",
        "yes",
    }
    errors = []
    if not gamertag:
        errors.append("EA ID / Gamertag is required.")
    if not discord_username:
        errors.append("Discord username is required.")
    if discord_id and not discord_id.isdigit():
        errors.append("Discord User ID must be numeric if provided.")
    if games_per_week not in GAMES_PER_WEEK_CHOICES:
        errors.append("Games per week must be 1–3, 3–5, or 6+.")
    if not new_gen:
        errors.append("New gen confirmation is required.")
    return {
        "gamertag": gamertag,
        "discord_username": discord_username,
        "discord_id": discord_id,
        "games_per_week": games_per_week,
        "referred_by": referred_by,
        "new_gen_confirmed": new_gen,
        "errors": errors,
    }


def can_submit_job_application(manager, user=None):
    if manager is None:
        return False
    if manager.status == ManagerApplication.REJECTED:
        return False
    from .market import club_for_user

    holder = user if user is not None else getattr(manager, "user", None)
    if club_for_user(holder):
        return False
    return pending_job_application(manager) is None


@transaction.atomic
def submit_job_application(manager, team, payload, message=""):
    """Create the official Job Application. One PENDING row per manager."""
    manager = ManagerApplication.objects.select_for_update().get(pk=manager.pk)
    if manager.status == ManagerApplication.REJECTED:
        raise ValueError("Your manager application was rejected.")
    from .market import club_for_user

    if club_for_user(manager.user):
        raise ValueError("You already manage a club.")
    if pending_job_application(manager):
        raise ValueError("You already have a pending job application.")
    if team.manager_id:
        raise ValueError("That club already has a manager.")
    if manager.gamertag != payload["gamertag"]:
        manager.gamertag = payload["gamertag"]
        manager.save(update_fields=["gamertag"])
    discord_id = payload.get("discord_id") or ""
    user = manager.user
    if discord_id and user.discord_id != discord_id:
        from accounts.models import User

        taken = (
            User.objects.filter(discord_id=discord_id).exclude(pk=user.pk).exists()
        )
        if not taken:
            user.discord_id = discord_id
            user.save(update_fields=["discord_id"])
    return ClubApplication.objects.create(
        manager=manager,
        team=team,
        gamertag=payload["gamertag"],
        discord_username=payload["discord_username"],
        games_per_week=payload["games_per_week"],
        referred_by=payload["referred_by"],
        new_gen_confirmed=payload["new_gen_confirmed"],
        message=message or "",
        status=ApprovalStatus.PENDING,
    )


@transaction.atomic
def approve_job_application(application, reviewer):
    """DEC-041 official accept: approve identity (if needed) and assign the club atomically."""
    application = (
        ClubApplication.objects.select_for_update()
        .select_related("manager__user", "team")
        .get(pk=application.pk)
    )
    if application.status != ApprovalStatus.PENDING:
        raise ValueError("This job application is no longer pending.")

    from teams.models import Team

    team = Team.objects.select_for_update().get(pk=application.team_id)
    if team.manager_id:
        raise ValueError(f"{team.name} already has a manager.")

    manager = ManagerApplication.objects.select_for_update().select_related("user").get(
        pk=application.manager_id
    )
    if manager.status == ManagerApplication.REJECTED:
        raise ValueError("This manager identity was rejected.")

    from .market import club_for_user

    if club_for_user(manager.user):
        raise ValueError("That manager already has a club.")

    if manager.status == ManagerApplication.PENDING:
        approve_manager_application(manager, reviewer)
        manager.refresh_from_db()
    if manager.status != ManagerApplication.APPROVED:
        raise ValueError("The manager identity could not be approved.")
    if manager.tokens is None:
        manager.tokens = STARTING_TOKENS
        manager.save(update_fields=["tokens"])

    user = manager.user
    if getattr(user, "role", None) != user.MANAGER:
        user.role = user.MANAGER
        user.is_active = True
        user.save(update_fields=["role", "is_active"])

    team.manager = user
    team.save(update_fields=["manager"])

    from .tenure import open_club_spell

    open_club_spell(manager, team)

    application.status = ApprovalStatus.APPROVED
    application.reviewed_at = timezone.now()
    application.reviewed_by = reviewer
    application.save(update_fields=["status", "reviewed_at", "reviewed_by"])

    from mgl.press import create_appointment_press
    from mgl.services import create_news
    from mgl.models import NewsPost

    create_news(
        NewsPost.MANAGER,
        f"{manager.display_name} appointed",
        f"{manager.display_name} has been appointed as manager of {team.name}.",
        team=team,
        discord_idempotency_key=f"job.approve:{application.pk}",
    )
    create_appointment_press(user, team)

    from django.urls import reverse
    from mgl.notifications import notify_user

    notify_user(
        user,
        source_key=f"job-approved-{application.pk}",
        notification_type="ADMIN",
        title="CLUB APPOINTMENT",
        message=f"You have been appointed as manager of {team.name}.",
        actor="UFL Admin",
        action_url=reverse("manager_hub"),
        action_label="OPEN HUB",
        team=team,
    )
    from mgl.audit import log_ocm_action

    log_ocm_action(
        reviewer,
        action="job.approve",
        object_type="ClubApplication",
        object_id=application.pk,
        object_label=team.name,
        new_value="APPROVED",
        summary=f"Appointed {manager.display_name} to {team.name}.",
    )
    return application


@transaction.atomic
def reject_job_application(application, reviewer):
    """Reject the Job Application only. The user stays a Member."""
    application = (
        ClubApplication.objects.select_for_update()
        .select_related("manager__user", "team")
        .get(pk=application.pk)
    )
    if application.status != ApprovalStatus.PENDING:
        raise ValueError("This job application is no longer pending.")
    application.status = ApprovalStatus.REJECTED
    application.reviewed_at = timezone.now()
    application.reviewed_by = reviewer
    application.save(update_fields=["status", "reviewed_at", "reviewed_by"])

    from django.urls import reverse
    from mgl.notifications import notify_user

    notify_user(
        application.manager.user,
        source_key=f"job-rejected-{application.pk}",
        notification_type="ADMIN",
        title="CLUB APPLICATION REJECTED",
        message=f"Your application for {application.team.name} was rejected.",
        actor="UFL Admin",
        action_url=reverse("job_centre"),
        action_label="JOB OFFERS",
        team=application.team,
    )
    from mgl.audit import log_ocm_action

    log_ocm_action(
        reviewer,
        action="job.reject",
        object_type="ClubApplication",
        object_id=application.pk,
        object_label=application.team.name,
        new_value="REJECTED",
        summary=(
            f"{application.manager.display_name}'s job application for "
            f"{application.team.name} was rejected."
        ),
    )
    return application
