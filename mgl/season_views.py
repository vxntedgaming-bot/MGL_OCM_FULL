"""Owner/Admin season finalisation and historical award management."""

from datetime import datetime

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.models import User
from leagues.services import active_league
from managers.models import ManagerApplication
from mgl.models import HistoricalSeason
from mgl.permissions import site_manage_required
from mgl.season_history import (
    FORMATIONS,
    eligible_season_players,
    ensure_active_season,
    finalise_season,
    formation_slots,
    live_overview,
    lock_season,
    save_season_draft,
    start_next_season,
    tots_display,
    unlock_season,
    young_player_suggestions,
)
from players.models import Player
from teams.models import Team


def _parse_date(value):
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _int_or_none(value):
    text = (value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _team(pk):
    if not pk:
        return None
    return Team.objects.filter(pk=pk).first()


def _player(pk):
    if not pk:
        return None
    return Player.objects.filter(pk=pk).first()


def _manager(pk):
    if not pk:
        return None
    return ManagerApplication.objects.filter(pk=pk, status=ManagerApplication.APPROVED).first()


def _awards_from_post(post):
    return {
        "cup_winner": _team(post.get("cup_winner")),
        "manager_of_season": _manager(post.get("manager_of_season")),
        "ballon_dor": _player(post.get("ballon_dor")),
        "young_player": _player(post.get("young_player")),
        "league_winner": _team(post.get("league_winner")),
        "top_scorer": _player(post.get("top_scorer")),
        "top_scorer_goals": _int_or_none(post.get("top_scorer_goals")),
        "top_assists_player": _player(post.get("top_assists_player")),
        "top_assists_count": _int_or_none(post.get("top_assists_count")),
        "top_goalkeeper": _player(post.get("top_goalkeeper")),
        "fair_play_team": _team(post.get("fair_play_team")),
        "unbeaten_team": _team(post.get("unbeaten_team")),
        "unbeaten_games": _int_or_none(post.get("unbeaten_games")),
        "biggest_win_home": _team(post.get("biggest_win_home")),
        "biggest_win_away": _team(post.get("biggest_win_away")),
        "biggest_win_home_goals": _int_or_none(post.get("biggest_win_home_goals")),
        "biggest_win_away_goals": _int_or_none(post.get("biggest_win_away_goals")),
    }


def _tots_from_post(post, formation):
    picks = []
    for index, (slot, _x, _y) in enumerate(formation_slots(formation)):
        player = _player(post.get(f"tots_{slot}") or post.get(f"tots_{index}"))
        picks.append({"slot": slot, "player": player})
    return picks


def _metadata_from_post(post):
    formation = (post.get("tots_formation") or "4-2-3-1").strip()
    if formation not in FORMATIONS:
        formation = "4-2-3-1"
    return {
        "year_label": post.get("year_label", ""),
        "start_date": _parse_date(post.get("start_date")),
        "end_date": _parse_date(post.get("end_date")),
        "tots_formation": formation,
    }


@site_manage_required
@require_http_methods(["GET", "POST"])
def season_management(request):
    ensure_active_season()
    seasons = list(HistoricalSeason.objects.order_by("number"))
    selected = None
    requested = request.GET.get("season") or request.POST.get("season_id")
    if requested:
        selected = HistoricalSeason.objects.filter(number=requested).first()
    if selected is None:
        selected = (
            HistoricalSeason.objects.filter(status=HistoricalSeason.ACTIVE).order_by("number").first()
            or HistoricalSeason.objects.order_by("-number").first()
        )
    if selected is None:
        from mgl.control_desk import merge_control_shell

        return render(
            request,
            "mgl/site_manage/seasons.html",
            merge_control_shell(request, "season_settings", {"seasons": [], "season": None}),
        )

    league = selected.league or active_league()
    overview = live_overview(league, selected.number) if selected.is_active else None
    is_owner = request.user.role == User.OWNER
    can_edit = (not selected.is_locked) or is_owner

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "unlock":
                unlock_season(selected, request.user)
                messages.success(request, f"Season {selected.number} is unlocked for correction.")
            elif action == "lock":
                lock_season(selected, request.user)
                messages.success(request, f"Season {selected.number} is locked.")
            elif action == "start_next":
                next_season = start_next_season(request.user)
                messages.success(request, f"Season {next_season.number} is now the active season.")
                return redirect("season_management")
            elif can_edit and action in {"save", "finalise"}:
                metadata = _metadata_from_post(request.POST)
                awards = _awards_from_post(request.POST)
                tots = _tots_from_post(request.POST, metadata["tots_formation"])
                if action == "finalise":
                    if not selected.is_active:
                        messages.error(request, "Only the active season can be finalised.")
                    else:
                        finalise_season(
                            selected,
                            request.user,
                            metadata=metadata,
                            awards=awards,
                            tots=tots,
                        )
                        messages.success(
                            request,
                            f"Season {selected.number} is finalised. Historical records are locked.",
                        )
                else:
                    save_season_draft(
                        selected,
                        request.user,
                        metadata=metadata,
                        awards=awards,
                        tots=tots,
                    )
                    messages.success(request, f"Season {selected.number} details saved.")
            else:
                messages.error(request, "You do not have permission to change this season.")
        except (PermissionError, ValueError) as exc:
            messages.error(request, str(exc))
        return redirect(f"{request.path}?season={selected.number}")

    clubs = list(Team.objects.filter(league=league).order_by("name")) if league else list(Team.objects.order_by("name")[:200])
    players = eligible_season_players(league, selected.number)
    managers = list(
        ManagerApplication.objects.filter(status=ManagerApplication.APPROVED)
        .select_related("user")
        .order_by("display_name")
    )
    from mgl.control_desk import merge_control_shell

    return render(
        request,
        "mgl/site_manage/seasons.html",
        merge_control_shell(
            request,
            "season_settings",
            {
                "seasons": seasons,
                "season": selected,
                "overview": overview,
                "clubs": clubs,
                "players": players,
                "managers": managers,
                "formations": list(FORMATIONS.keys()),
                "tots": tots_display(selected),
                "young_suggestions": young_player_suggestions(league, selected.number),
                "is_owner": is_owner,
                "can_edit": can_edit,
                "can_start_next": selected.is_finalized
                and not HistoricalSeason.objects.filter(status=HistoricalSeason.ACTIVE).exists(),
            },
        ),
    )
