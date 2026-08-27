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
)

from .services import credit_manager


@transaction.atomic
def approve_match_submission(sub, reviewer):
    """
    Approve one match exactly once.

    All official match updates and token rewards happen inside
    one database transaction.
    """

    sub = (
        MatchSubmission.objects
        .select_for_update()
        .select_related(
            "fixture",
            "fixture__home_team",
            "fixture__away_team",
        )
        .get(pk=sub.pk)
    )

    if sub.status != ApprovalStatus.PENDING:
        return False, "Match is no longer pending."

    fixture = sub.fixture

    stats = list(
        sub.team_stats
        .select_related("team")
        .prefetch_related(
            "goal_events__player",
            "assist_events__player",
            "defender_ratings__player",
            "gk_saves__player",
        )
    )

    home_stats = next(
        (x for x in stats if x.team_id == fixture.home_team_id),
        None,
    )

    away_stats = next(
        (x for x in stats if x.team_id == fixture.away_team_id),
        None,
    )

    if not home_stats or not away_stats:
        raise ValueError(
            "Both teams must have match statistics before approval."
        )

    if home_stats.goals == away_stats.goals:
        result = "DRAW"
    elif home_stats.goals > away_stats.goals:
        result = "HOME_WIN"
    else:
        result = "AWAY_WIN"

    # ---------------------------------------------------------
    # PLAYER STATISTICS
    # ---------------------------------------------------------

    touched_players = set()

    for team_stats in stats:

        for event in team_stats.goal_events.all():
            player = event.player
            player.goals = (player.goals or 0) + 1
            player.save(update_fields=["goals"])
            touched_players.add(player.pk)

        for event in team_stats.assist_events.all():
            player = event.player
            player.assists = (player.assists or 0) + 1
            player.save(update_fields=["assists"])
            touched_players.add(player.pk)

        for rating in team_stats.defender_ratings.all():
            touched_players.add(rating.player_id)

        for save in team_stats.gk_saves.all():
            touched_players.add(save.player_id)

    # A player who participated in the match gets one appearance.
    for player_id in touched_players:
        from players.models import Player

        player = Player.objects.get(pk=player_id)
        player.appearances = (player.appearances or 0) + 1
        player.save(update_fields=["appearances"])

    # ---------------------------------------------------------
    # MANAGER CAREER RECORDS
    # ---------------------------------------------------------

    from managers.models import ManagerApplication

    managers = []

    if fixture.home_team.manager_id:
        try:
            managers.append(
                ManagerApplication.objects.get(
                    user_id=fixture.home_team.manager_id
                )
            )
        except ManagerApplication.DoesNotExist:
            pass

    if (
        fixture.away_team.manager_id
        and fixture.away_team.manager_id != fixture.home_team.manager_id
    ):
        try:
            managers.append(
                ManagerApplication.objects.get(
                    user_id=fixture.away_team.manager_id
                )
            )
        except ManagerApplication.DoesNotExist:
            pass

    home_manager = None
    away_manager = None

    if fixture.home_team.manager_id:
        home_manager = next(
            (
                m for m in managers
                if m.user_id == fixture.home_team.manager_id
            ),
            None,
        )

    if fixture.away_team.manager_id:
        away_manager = next(
            (
                m for m in managers
                if m.user_id == fixture.away_team.manager_id
            ),
            None,
        )

    if home_manager:
        career, _ = ManagerCareerStat.objects.get_or_create(
            manager=home_manager
        )

        if result == "HOME_WIN":
            career.wins += 1
        elif result == "DRAW":
            career.draws += 1
        else:
            career.losses += 1

        career.save()

    if away_manager:
        career, _ = ManagerCareerStat.objects.get_or_create(
            manager=away_manager
        )

        if result == "AWAY_WIN":
            career.wins += 1
        elif result == "DRAW":
            career.draws += 1
        else:
            career.losses += 1

        career.save()

    # ---------------------------------------------------------
    # MATCH REWARD
    # ---------------------------------------------------------

    if home_manager:
        credit_manager(
            home_manager,
            Decimal("1.00"),
            "Approved league match",
            "MATCH",
            fixture,
        )

    if away_manager:
        credit_manager(
            away_manager,
            Decimal("1.00"),
            "Approved league match",
            "MATCH",
            fixture,
        )

    # ---------------------------------------------------------
    # MARK MATCH OFFICIAL
    # ---------------------------------------------------------

    sub.status = ApprovalStatus.APPROVED
    sub.reviewed_by = reviewer
    sub.reviewed_at = timezone.now()
    sub.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
        ]
    )

    fixture.status = "COMPLETED"
    fixture.save(update_fields=["status"])

    # ---------------------------------------------------------
    # NEWS
    # ---------------------------------------------------------

    NewsPost.objects.create(
        category=NewsPost.RESULTS,
        title=(
            f"{fixture.home_team.name} "
            f"{home_stats.goals} - {away_stats.goals} "
            f"{fixture.away_team.name}"
        ),
        body=(
            f"FULL TIME\n\n"
            f"{fixture.home_team.name} {home_stats.goals} - "
            f"{away_stats.goals} {fixture.away_team.name}\n\n"
            f"Shots: {home_stats.shots} - {away_stats.shots}\n"
            f"Possession: {home_stats.possession}% - "
            f"{away_stats.possession}%\n\n"
            f"The result has been officially approved by MGL Admin."
        ),
        published=True,
        discord_sent=False,
    )

    return True, "Match approved successfully."


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

    updated = queryset.filter(
        status=ApprovalStatus.PENDING
    ).update(
        status=ApprovalStatus.REJECTED,
        reviewed_by=request.user,
        reviewed_at=timezone.now(),
    )

    messages.success(
        request,
        f"{updated} match submission(s) rejected.",
    )


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
admin.site.register(RewardTransaction)
admin.site.register(TeamOfTheWeek)
admin.site.register(TOTWSelection)
admin.site.register(ManagerWeek)
admin.site.register(NewsPost)
admin.site.register(Pack)
admin.site.register(PackOpening)
admin.site.register(PackReward)
admin.site.register(ApprovalRequest)


@admin.action(
    description="Approve selected press conferences and award 0.20 tokens"
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
                Decimal("0.20"),
                "Approved post-match press conference",
                "PRESS",
                obj.fixture,
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
        "manager",
        "status",
        "reward",
        "created_at",
    )

    list_filter = (
        "status",
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

            NewsPost.objects.create(
                category=NewsPost.REWARD,
                title="MGL MANAGER OF THE WEEK",
                body=(
                    f"{manager_name} has been named "
                    f"MGL Manager of the Week.\n\n"
                    f"Wins this week: "
                    f"{manager_week.wins}\n\n"
                    f"Reward: 0.50 tokens."
                ),
                published=True,
                discord_sent=False,
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
