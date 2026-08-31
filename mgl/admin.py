from decimal import Decimal

from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone

from .models import (
    ApprovalStatus,
    AssistEvent,
    DefenderRating,
    Fixture,
    GKSave,
    GoalEvent,
    ManagerCareerStat,
    MatchSubmission,
    NewsPost,
    Pack,
    PackOpening,
    PackReward,
    PressConference,
    RewardTransaction,
    TeamMatchStats,
    TeamOfTheWeek,
    TOTWSelection,
    ManagerWeek,
    ApprovalRequest,
    WeeklyAwardBatch,
)

from mgl.match_official import (
    approve_match_submission,
    reject_match_submission,
    unapprove_match_submission,
)
from .services import create_news, credit_manager


@admin.action(description="Approve selected match submissions")
def approve_matches(modeladmin, request, queryset):

    approved = 0
    skipped = 0

    for submission in queryset:

        try:
            success, message = approve_match_submission(
                submission,
                request.user,
            )

            if success:
                approved += 1
            else:
                skipped += 1

        except Exception as exc:
            skipped += 1
            messages.error(
                request,
                f"{submission.fixture}: {exc}",
            )

    if approved:
        messages.success(
            request,
            f"{approved} match(es) approved successfully.",
        )

    if skipped:
        messages.warning(
            request,
            f"{skipped} match(es) were skipped or failed.",
        )


@admin.action(description="Reject selected match submissions")
def reject_matches(modeladmin, request, queryset):
    rejected = 0
    skipped = 0
    for submission in queryset:
        success, message = reject_match_submission(submission, request.user)
        if success:
            rejected += 1
        else:
            skipped += 1
            messages.error(request, f"{submission}: {message}")
    if rejected:
        messages.success(request, f"{rejected} match submission(s) rejected.")
    if skipped:
        messages.warning(request, f"{skipped} match submission(s) were skipped or failed.")


@admin.action(description="Roll back official match submissions")
def rollback_matches(modeladmin, request, queryset):
    rolled = 0
    skipped = 0
    for submission in queryset:
        success, message = unapprove_match_submission(submission, request.user)
        if success:
            rolled += 1
        else:
            skipped += 1
            messages.error(request, f"{submission}: {message}")
    if rolled:
        messages.success(request, f"{rolled} official result(s) rolled back.")
    if skipped:
        messages.warning(request, f"{skipped} match submission(s) were skipped or failed.")


@admin.register(MatchSubmission)
class MatchSubmissionAdmin(admin.ModelAdmin):

    list_display = (
        "fixture",
        "submitted_by",
        "status",
        "submitted_at",
        "reviewed_by",
    )

    list_filter = (
        "status",
    )

    search_fields = (
        "fixture__home_team__name",
        "fixture__away_team__name",
        "submitted_by__username",
    )

    actions = (
        approve_matches,
        reject_matches,
        rollback_matches,
    )

    readonly_fields = (
        "submitted_at",
        "reviewed_at",
    )


admin.site.register(Fixture)
admin.site.register(TeamMatchStats)
admin.site.register(GoalEvent)
admin.site.register(AssistEvent)
admin.site.register(DefenderRating)
admin.site.register(GKSave)
admin.site.register(TeamOfTheWeek)
admin.site.register(TOTWSelection)
admin.site.register(ManagerWeek)
admin.site.register(NewsPost)
admin.site.register(Pack)
admin.site.register(PackOpening)
admin.site.register(PackReward)
admin.site.register(ApprovalRequest)


@admin.action(
    description="Approve selected press conferences"
)
def approve_press(modeladmin, request, queryset):

    approved = 0

    for obj in queryset.filter(
        status=ApprovalStatus.PENDING
    ):

        with transaction.atomic():

            obj.status = ApprovalStatus.APPROVED
            obj.approved_at = timezone.now()

            obj.save(
                update_fields=[
                    "status",
                    "approved_at",
                ]
            )

            from managers.models import ManagerApplication

            manager = ManagerApplication.objects.get(
                user=obj.manager
            )

            credit_manager(
                manager,
                Decimal("0.50"),
                "Approved post-match press conference",
                "PRESS",
                obj.fixture,
                reference=f"press:{obj.pk}",
            )

            approved += 1

    messages.success(
        request,
        f"{approved} press conference(s) approved.",
    )


@admin.action(description="Reject selected press conferences")
def reject_press(modeladmin, request, queryset):

    updated = queryset.filter(
        status=ApprovalStatus.PENDING
    ).update(
        status=ApprovalStatus.REJECTED,
        approved_at=None,
    )

    messages.success(
        request,
        f"{updated} press conference(s) rejected.",
    )


@admin.register(PressConference)
class PressConferenceAdmin(admin.ModelAdmin):

    list_display = (
        "fixture",
        "team",
        "manager",
        "trigger",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "trigger",
    )

    search_fields = (
        "manager__username",
        "fixture__home_team__name",
        "fixture__away_team__name",
    )

    actions = (
        approve_press,
        reject_press,
    )


# ============================================================
# MGL TOTW / MANAGER OF THE WEEK ADMIN CONTROLS
# ============================================================

from datetime import date, timedelta

from django import forms
from django.http import HttpResponseRedirect
from django.urls import path
from django.template.response import TemplateResponse

from .totw_service import (
    generate_totw,
    approve_totw,
    generate_manager_of_week,
    approve_manager_of_week,
)


@admin.action(description="Generate selected TOTW week")
def generate_selected_totw(modeladmin, request, queryset):

    created = 0

    for totw in queryset:

        if totw.approved:
            continue

        try:
            generate_totw(totw.week_start)
            created += 1
        except Exception as exc:
            messages.error(
                request,
                f"TOTW {totw.week_start}: {exc}",
            )

    if created:
        messages.success(
            request,
            f"{created} TOTW calculation(s) generated.",
        )


@admin.action(description="Approve selected TOTW")
def approve_selected_totw(modeladmin, request, queryset):

    approved = 0

    for totw in queryset.filter(approved=False):

        try:
            approve_totw(totw, request.user)

            selections = list(
                totw.selections.select_related(
                    "player",
                    "player__mgl_team",
                )
            )

            lines = []

            for selection in selections:
                lines.append(
                    f"{selection.slot}: "
                    f"{selection.player.name}"
                )

            NewsPost.objects.create(
                category=NewsPost.REWARD,
                title="MGL TEAM OF THE WEEK",
                body=(
                    f"Official MGL Team of the Week "
                    f"for week beginning {totw.week_start}.\n\n"
                    f"Formation: 4-2-3-1\n\n"
                    + "\n".join(lines)
                    + "\n\n"
                    "Selected players earn their club manager "
                    "0.20 tokens each."
                ),
                published=True,
                discord_sent=False,
            )

            approved += 1

        except Exception as exc:
            messages.error(
                request,
                f"TOTW {totw.week_start}: {exc}",
            )

    if approved:
        messages.success(
            request,
            f"{approved} TOTW(s) approved.",
        )


@admin.action(description="Generate Manager of the Week")
def generate_selected_motw(modeladmin, request, queryset):

    generated = 0

    for manager_week in queryset:

        try:
            rows = generate_manager_of_week(
                manager_week.week_start
            )

            generated += len(rows)

        except Exception as exc:
            messages.error(
                request,
                f"Manager Week {manager_week.week_start}: {exc}",
            )

    if generated:
        messages.success(
            request,
            f"{generated} Manager of the Week row(s) generated.",
        )


@admin.action(description="Approve selected Manager of the Week")
def approve_selected_motw(modeladmin, request, queryset):

    approved = 0

    for manager_week in queryset.filter(
        approved=False
    ).order_by("-wins")[:1]:

        try:
            approve_manager_of_week(
                manager_week
            )

            manager_name = (
                manager_week.manager.display_name
            )
            club = None
            user = getattr(manager_week.manager, "user", None)
            if user is not None:
                from teams.models import Team

                club = Team.objects.filter(manager=user).first()

            create_news(
                NewsPost.REWARD,
                "MGL MANAGER OF THE WEEK",
                (
                    f"{manager_name} has been named "
                    f"MGL Manager of the Week.\n\n"
                    f"Wins this week: "
                    f"{manager_week.wins}\n\n"
                    f"Reward: 0.50 tokens."
                ),
                team=club,
            )

            approved += 1

        except Exception as exc:
            messages.error(
                request,
                f"{manager_week.week_start}: {exc}",
            )

    if approved:
        messages.success(
            request,
            f"{approved} Manager of the Week award(s) approved.",
        )


# Replace the existing registrations with enhanced admin classes.

try:
    admin.site.unregister(TeamOfTheWeek)
except admin.sites.NotRegistered:
    pass


@admin.register(TeamOfTheWeek)
class TeamOfTheWeekAdmin(admin.ModelAdmin):

    list_display = (
        "week_start",
        "formation",
        "approved",
        "created_at",
    )

    list_filter = (
        "approved",
        "formation",
    )

    ordering = (
        "-week_start",
    )

    actions = (
        generate_selected_totw,
        approve_selected_totw,
    )

    readonly_fields = (
        "created_at",
    )

    def get_urls(self):

        urls = super().get_urls()

        custom_urls = [
            path(
                "generate-week/",
                self.admin_site.admin_view(
                    self.generate_week_view
                ),
                name="mgl_generate_totw",
            ),
        ]

        return custom_urls + urls

    def generate_week_view(
        self,
        request,
    ):

        week_start = timezone.now().date()

        week_start -= timedelta(
            days=week_start.weekday()
        )

        try:
            totw = generate_totw(
                week_start
            )

            self.message_user(
                request,
                (
                    f"TOTW generated for "
                    f"{week_start}."
                ),
                messages.SUCCESS,
            )

        except Exception as exc:

            self.message_user(
                request,
                str(exc),
                messages.ERROR,
            )

        return HttpResponseRedirect(
            "../"
        )


try:
    admin.site.unregister(ManagerWeek)
except admin.sites.NotRegistered:
    pass


@admin.register(ManagerWeek)
class ManagerWeekAdmin(admin.ModelAdmin):

    list_display = (
        "week_start",
        "manager",
        "wins",
        "reward",
        "approved",
    )

    list_filter = (
        "approved",
        "week_start",
    )

    ordering = (
        "-week_start",
        "-wins",
    )

    actions = (
        generate_selected_motw,
        approve_selected_motw,
    )

    readonly_fields = (
        "wins",
        "reward",
    )


from .models import ClubApplication, MarketTransaction, PlayerListing


@admin.register(PlayerListing)
class PlayerListingAdmin(admin.ModelAdmin):
    list_display = ("player", "team", "seller", "asking_price", "status", "created_at")
    list_filter = ("status",)


@admin.register(MarketTransaction)
class MarketTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "transaction_type",
        "player",
        "seller",
        "buyer",
        "amount",
        "status",
    )
    list_filter = ("transaction_type", "status")
    readonly_fields = ("created_at", "completed_at")


@admin.register(ClubApplication)
class ClubApplicationAdmin(admin.ModelAdmin):
    list_display = ("manager", "team", "gamertag", "discord_username", "status", "created_at")
    list_filter = ("status",)


from .models import SiteChangeLog, SiteContent


@admin.register(SiteContent)
class SiteContentAdmin(admin.ModelAdmin):
    list_display = ("key", "section", "updated_at", "updated_by")
    list_filter = ("section",)
    search_fields = ("key", "value")
    readonly_fields = ("updated_at",)


from .models import ManagerNotification, MonthlyAwardBatch, RewardTransaction, WeeklyAwardBatch


@admin.register(RewardTransaction)
class RewardTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "manager",
        "amount",
        "category",
        "reason",
        "reference",
    )
    list_filter = ("category",)
    search_fields = (
        "reason",
        "reference",
        "manager__display_name",
        "manager__user__username",
    )
    readonly_fields = (
        "manager",
        "amount",
        "reason",
        "category",
        "fixture",
        "reference",
        "created_at",
    )


@admin.register(WeeklyAwardBatch)
class WeeklyAwardBatchAdmin(admin.ModelAdmin):
    list_display = ("week_start", "status", "completed", "has_ties", "created_at", "notes")
    list_filter = ("status", "completed", "has_ties")
    search_fields = ("notes",)
    readonly_fields = (
        "week_start",
        "notes",
        "completed",
        "status",
        "has_ties",
        "payload",
        "reviewed_by",
        "reviewed_at",
        "created_at",
    )


@admin.register(MonthlyAwardBatch)
class MonthlyAwardBatchAdmin(admin.ModelAdmin):
    list_display = ("month_start", "status", "completed", "has_ties", "created_at", "notes")
    list_filter = ("status", "completed", "has_ties")
    search_fields = ("notes",)
    readonly_fields = (
        "month_start",
        "notes",
        "completed",
        "status",
        "has_ties",
        "payload",
        "reviewed_by",
        "reviewed_at",
        "created_at",
    )


@admin.register(ManagerNotification)
class ManagerNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "recipient",
        "notification_type",
        "title",
        "read_at",
    )
    list_filter = ("notification_type",)
    search_fields = ("title", "message", "source_key", "recipient__username")
    readonly_fields = (
        "recipient",
        "source_key",
        "notification_type",
        "title",
        "message",
        "actor",
        "action_url",
        "action_label",
        "team",
        "player",
        "is_action",
        "created_at",
        "read_at",
    )


@admin.register(SiteChangeLog)
class SiteChangeLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "object_type", "summary")
    list_filter = ("object_type", "action")
    search_fields = ("summary", "object_label")
    readonly_fields = (
        "user",
        "action",
        "object_type",
        "object_id",
        "object_label",
        "old_value",
        "new_value",
        "summary",
        "created_at",
    )

