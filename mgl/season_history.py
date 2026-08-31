"""Season snapshots for /stats/history/. Live data is never rewritten into a locked season."""

from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from leagues.models import League
from leagues.services import active_league, ensure_premier_league
from mgl.league_stats import build_league_stats
from mgl.models import ApprovalStatus, Fixture, HistoricalSeason, SeasonTableRow, SeasonTotsPick
from mgl.site_cms import log_site_change
from mgl.standings import build_league_table
from players.display import player_age
from players.models import Player
from teams.models import Team


EMPTY_AWARD = "To be recorded"

AWARD_DEFS = (
    ("league_winner", "League Winner", "club"),
    ("cup_winner", "Cup Winner", "club"),
    ("manager", "Manager of the Season", "manager"),
    ("tots", "Team of the Season", "tots"),
    ("ballon_dor", "Ballon d'Or", "player"),
    ("top_assists", "Top Assists", "player"),
    ("young_player", "Young Player of the Season", "player"),
    ("top_goalkeeper", "Top Goalkeeper", "player"),
    ("fair_play", "Fair Play Award", "club"),
    ("biggest_win", "Biggest Win", "match"),
    ("unbeaten_run", "Unbeaten Run", "club"),
    ("top_scorer", "Top Scorer", "player"),
)

FORMATIONS = {
    "4-2-3-1": [
        ("GK", 50, 88),
        ("LB", 12, 70),
        ("CB1", 34, 74),
        ("CB2", 66, 74),
        ("RB", 88, 70),
        ("CDM1", 34, 52),
        ("CDM2", 66, 52),
        ("LM", 16, 30),
        ("CAM", 50, 32),
        ("RM", 84, 30),
        ("ST", 50, 12),
    ],
    "4-3-3": [
        ("GK", 50, 88),
        ("LB", 12, 70),
        ("CB1", 34, 74),
        ("CB2", 66, 74),
        ("RB", 88, 70),
        ("CM1", 28, 48),
        ("CM2", 50, 50),
        ("CM3", 72, 48),
        ("LW", 18, 22),
        ("ST", 50, 14),
        ("RW", 82, 22),
    ],
    "4-4-2": [
        ("GK", 50, 88),
        ("LB", 12, 70),
        ("CB1", 34, 74),
        ("CB2", 66, 74),
        ("RB", 88, 70),
        ("LM", 14, 42),
        ("CM1", 36, 46),
        ("CM2", 64, 46),
        ("RM", 86, 42),
        ("ST1", 38, 16),
        ("ST2", 62, 16),
    ],
    "3-5-2": [
        ("GK", 50, 88),
        ("CB1", 26, 72),
        ("CB2", 50, 76),
        ("CB3", 74, 72),
        ("LWB", 12, 48),
        ("CM1", 34, 46),
        ("CM2", 50, 50),
        ("CM3", 66, 46),
        ("RWB", 88, 48),
        ("ST1", 38, 16),
        ("ST2", 62, 16),
    ],
    "3-4-3": [
        ("GK", 50, 88),
        ("CB1", 26, 72),
        ("CB2", 50, 76),
        ("CB3", 74, 72),
        ("LM", 14, 46),
        ("CM1", 38, 48),
        ("CM2", 62, 48),
        ("RM", 86, 46),
        ("LW", 18, 18),
        ("ST", 50, 14),
        ("RW", 82, 18),
    ],
    "5-3-2": [
        ("GK", 50, 88),
        ("LWB", 10, 62),
        ("CB1", 30, 74),
        ("CB2", 50, 76),
        ("CB3", 70, 74),
        ("RWB", 90, 62),
        ("CM1", 30, 44),
        ("CM2", 50, 46),
        ("CM3", 70, 44),
        ("ST1", 38, 16),
        ("ST2", 62, 16),
    ],
}


def formation_slots(formation):
    return FORMATIONS.get(formation) or FORMATIONS["4-2-3-1"]


def current_season_number():
    active = HistoricalSeason.objects.filter(status=HistoricalSeason.ACTIVE).order_by("number").first()
    if active:
        return active.number
    latest = HistoricalSeason.objects.order_by("-number").first()
    if latest:
        return latest.number
    return 1


def _league_season_int():
    league = active_league()
    if league is None:
        return 1
    try:
        parsed = int(str(league.season).strip().split()[0])
    except (TypeError, ValueError):
        return 1
    return parsed if parsed > 0 else 1


def ensure_active_season():
    """Create Season 1 (or the current league season) as ACTIVE if none exists. No fake awards."""
    ensure_premier_league()
    active = HistoricalSeason.objects.filter(status=HistoricalSeason.ACTIVE).order_by("number").first()
    if active:
        return active
    if HistoricalSeason.objects.exists():
        return None
    number = _league_season_int()
    league = active_league()
    return HistoricalSeason.objects.create(
        number=number,
        status=HistoricalSeason.ACTIVE,
        league=league,
        clubs_count=Team.objects.filter(league=league).count() if league else 0,
    )


def all_seasons():
    ensure_active_season()
    return list(HistoricalSeason.objects.order_by("number"))


def finalized_seasons():
    return list(
        HistoricalSeason.objects.filter(status=HistoricalSeason.FINALIZED).order_by("number")
    )


def get_season(number):
    ensure_active_season()
    return HistoricalSeason.objects.filter(number=number).first()


def approved_fixtures(league, season_number):
    return (
        Fixture.objects.filter(
            league=league,
            season_number=season_number,
            status="COMPLETED",
            is_released=True,
            submission__status=ApprovalStatus.APPROVED,
        )
        .select_related("submission", "home_team", "away_team")
        .prefetch_related("submission__team_stats")
        .order_by("matchweek", "scheduled_at", "id")
    )


def _scoreline(fixture):
    try:
        stats = {row.team_id: row.goals for row in fixture.submission.team_stats.all()}
    except Exception:
        return None
    home = stats.get(fixture.home_team_id)
    away = stats.get(fixture.away_team_id)
    if home is None or away is None:
        return None
    return home, away


def compute_biggest_win(league, season_number):
    best = None
    for fixture in approved_fixtures(league, season_number):
        score = _scoreline(fixture)
        if score is None:
            continue
        home_goals, away_goals = score
        margin = abs(home_goals - away_goals)
        if margin == 0:
            continue
        total = home_goals + away_goals
        key = (margin, total)
        if best is None or key > best[0]:
            best = (key, fixture, home_goals, away_goals)
    if best is None:
        return None
    _key, fixture, home_goals, away_goals = best
    return {
        "home": fixture.home_team,
        "away": fixture.away_team,
        "home_goals": home_goals,
        "away_goals": away_goals,
    }


def compute_unbeaten_run(league, season_number):
    streaks = defaultdict(lambda: {"current": 0, "best": 0, "team": None})
    for fixture in approved_fixtures(league, season_number):
        score = _scoreline(fixture)
        if score is None:
            continue
        home_goals, away_goals = score
        results = {
            fixture.home_team_id: "W" if home_goals > away_goals else ("D" if home_goals == away_goals else "L"),
            fixture.away_team_id: "W" if away_goals > home_goals else ("D" if away_goals == home_goals else "L"),
        }
        teams = {fixture.home_team_id: fixture.home_team, fixture.away_team_id: fixture.away_team}
        for team_id, result in results.items():
            row = streaks[team_id]
            row["team"] = teams[team_id]
            if result == "L":
                row["current"] = 0
            else:
                row["current"] += 1
                if row["current"] > row["best"]:
                    row["best"] = row["current"]
    winner = None
    for row in streaks.values():
        if row["best"] <= 0:
            continue
        if winner is None or row["best"] > winner["best"]:
            winner = row
    if winner is None:
        return None
    return {"team": winner["team"], "games": winner["best"]}


def compute_fair_play(league, season_number):
    totals = defaultdict(lambda: {"yellow": 0, "red": 0, "team": None})
    played = False
    for fixture in approved_fixtures(league, season_number):
        try:
            rows = list(fixture.submission.team_stats.all())
        except Exception:
            continue
        if not rows:
            continue
        played = True
        for row in rows:
            item = totals[row.team_id]
            item["team"] = row.team
            item["yellow"] += int(row.yellow_cards or 0)
            item["red"] += int(row.red_cards or 0)
    if not played:
        return None
    ranked = sorted(
        totals.values(),
        key=lambda item: (item["red"], item["yellow"], (item["team"].name if item["team"] else "")),
    )
    if not ranked or ranked[0]["team"] is None:
        return None
    return ranked[0]["team"]


def live_overview(league, season_number):
    table = build_league_table(league, season_number=season_number) if league else []
    games = approved_fixtures(league, season_number).count() if league else 0
    clubs = Team.objects.filter(league=league).count() if league else 0
    stats = build_league_stats(league, season_number=season_number) if league else {}
    top_scorers = list(stats.get("top_scorers") or [])
    top_assists = list(stats.get("top_assisters") or [])
    top_keepers = list(stats.get("top_keepers") or [])
    winner = table[0]["team"] if table and table[0]["played"] else None
    scorer = top_scorers[0] if top_scorers else None
    assister = top_assists[0] if top_assists else None
    keeper = top_keepers[0] if top_keepers else None
    return {
        "table": table,
        "clubs_count": clubs,
        "games_played": games,
        "league_winner": winner,
        "top_scorer": scorer,
        "top_scorer_goals": getattr(scorer, "stat_value", None) if scorer else None,
        "top_assists": assister,
        "top_assists_count": getattr(assister, "stat_value", None) if assister else None,
        "top_goalkeeper": keeper,
        "biggest_win": compute_biggest_win(league, season_number) if league else None,
        "unbeaten": compute_unbeaten_run(league, season_number) if league else None,
        "fair_play": compute_fair_play(league, season_number) if league else None,
    }


def _team_name(team):
    return (team.name if team else "") or ""


def _player_name(player):
    return (player.name if player else "") or ""


def _snapshot_table(season, table):
    season.table_rows.all().delete()
    rows = []
    for item in table:
        team = item["team"]
        rows.append(
            SeasonTableRow(
                season=season,
                position=item["position"],
                team=team,
                team_name=_team_name(team),
                played=item["played"],
                wins=item["wins"],
                draws=item["draws"],
                losses=item["losses"],
                gf=item["gf"],
                ga=item["ga"],
                gd=item["gd"],
                points=item["points"],
            )
        )
    if rows:
        SeasonTableRow.objects.bulk_create(rows)


def apply_computed_awards(season, overview, *, fill_empty_only=True):
    def take(current, incoming):
        if incoming is None:
            return current
        if fill_empty_only and current is not None:
            return current
        return incoming

    season.league_winner = take(season.league_winner, overview.get("league_winner"))
    if season.league_winner:
        season.league_winner_name = _team_name(season.league_winner)
    scorer = take(season.top_scorer, overview.get("top_scorer"))
    season.top_scorer = scorer
    if scorer:
        season.top_scorer_name = _player_name(scorer)
        season.top_scorer_goals = overview.get("top_scorer_goals")
    assister = take(season.top_assists_player, overview.get("top_assists"))
    season.top_assists_player = assister
    if assister:
        season.top_assists_name = _player_name(assister)
        season.top_assists_count = overview.get("top_assists_count")
    keeper = take(season.top_goalkeeper, overview.get("top_goalkeeper"))
    season.top_goalkeeper = keeper
    if keeper:
        season.top_goalkeeper_name = _player_name(keeper)
    biggest = overview.get("biggest_win")
    if biggest and (not fill_empty_only or season.biggest_win_home_id is None):
        season.biggest_win_home = biggest["home"]
        season.biggest_win_away = biggest["away"]
        season.biggest_win_home_name = _team_name(biggest["home"])
        season.biggest_win_away_name = _team_name(biggest["away"])
        season.biggest_win_home_goals = biggest["home_goals"]
        season.biggest_win_away_goals = biggest["away_goals"]
    unbeaten = overview.get("unbeaten")
    if unbeaten and (not fill_empty_only or season.unbeaten_team_id is None):
        season.unbeaten_team = unbeaten["team"]
        season.unbeaten_team_name = _team_name(unbeaten["team"])
        season.unbeaten_games = unbeaten["games"]
    fair = take(season.fair_play_team, overview.get("fair_play"))
    season.fair_play_team = fair
    if fair:
        season.fair_play_name = _team_name(fair)
    season.clubs_count = overview.get("clubs_count") or season.clubs_count
    season.games_played = overview.get("games_played") or season.games_played


@transaction.atomic
def finalise_season(season, user, *, metadata=None, awards=None, tots=None):
    if season.status == HistoricalSeason.FINALIZED and season.is_locked:
        raise PermissionError("This season is locked.")
    metadata = metadata or {}
    awards = awards or {}
    league = season.league or active_league()
    overview = live_overview(league, season.number)
    apply_computed_awards(season, overview, fill_empty_only=False)
    if metadata.get("year_label") is not None:
        season.year_label = (metadata.get("year_label") or "").strip()
    if "start_date" in metadata:
        season.start_date = metadata.get("start_date") or None
    if "end_date" in metadata:
        season.end_date = metadata.get("end_date") or None
    _apply_award_overrides(season, awards)
    if metadata.get("tots_formation"):
        season.tots_formation = metadata["tots_formation"]
    _snapshot_table(season, overview["table"])
    if tots is not None:
        _save_tots(season, tots)
    season.league = league
    season.status = HistoricalSeason.FINALIZED
    season.is_locked = True
    season.finalized_at = timezone.now()
    season.finalized_by = user if getattr(user, "is_authenticated", False) else None
    season.save()
    log_site_change(
        user,
        action="season.finalise",
        object_type="HistoricalSeason",
        object_id=season.pk,
        object_label=f"Season {season.number}",
        summary=f"Finalised Season {season.number} historical snapshot.",
    )
    return season


def _apply_award_overrides(season, awards):
    mapping = {
        "cup_winner": ("cup_winner", "cup_winner_name", _team_name),
        "manager_of_season": ("manager_of_season", "manager_of_season_name", lambda obj: getattr(obj, "display_name", "") if obj else ""),
        "ballon_dor": ("ballon_dor", "ballon_dor_name", _player_name),
        "young_player": ("young_player", "young_player_name", _player_name),
        "league_winner": ("league_winner", "league_winner_name", _team_name),
        "top_scorer": ("top_scorer", "top_scorer_name", _player_name),
        "top_assists_player": ("top_assists_player", "top_assists_name", _player_name),
        "top_goalkeeper": ("top_goalkeeper", "top_goalkeeper_name", _player_name),
        "fair_play_team": ("fair_play_team", "fair_play_name", _team_name),
        "unbeaten_team": ("unbeaten_team", "unbeaten_team_name", _team_name),
    }
    for key, (field, name_field, namer) in mapping.items():
        if key not in awards:
            continue
        obj = awards.get(key)
        if obj is None:
            continue
        setattr(season, field, obj)
        setattr(season, name_field, namer(obj) if obj else "")
        if key == "manager_of_season":
            club = ""
            if obj and getattr(obj, "user_id", None):
                team = Team.objects.filter(manager_id=obj.user_id).first()
                club = _team_name(team)
            season.manager_of_season_club = club
    if "top_scorer_goals" in awards and awards.get("top_scorer_goals") is not None:
        season.top_scorer_goals = awards.get("top_scorer_goals")
    if "top_assists_count" in awards and awards.get("top_assists_count") is not None:
        season.top_assists_count = awards.get("top_assists_count")
    if "unbeaten_games" in awards and awards.get("unbeaten_games") is not None:
        season.unbeaten_games = awards.get("unbeaten_games")
    home = awards.get("biggest_win_home")
    away = awards.get("biggest_win_away")
    if home or away:
        season.biggest_win_home = home
        season.biggest_win_away = away
        season.biggest_win_home_name = _team_name(home)
        season.biggest_win_away_name = _team_name(away)
        if awards.get("biggest_win_home_goals") is not None:
            season.biggest_win_home_goals = awards.get("biggest_win_home_goals")
        if awards.get("biggest_win_away_goals") is not None:
            season.biggest_win_away_goals = awards.get("biggest_win_away_goals")


def _save_tots(season, picks):
    season.tots_picks.all().delete()
    rows = []
    for index, item in enumerate(picks):
        player = item.get("player")
        rows.append(
            SeasonTotsPick(
                season=season,
                slot=item.get("slot") or f"P{index}",
                sort_order=index,
                player=player,
                player_name=_player_name(player),
            )
        )
    if rows:
        SeasonTotsPick.objects.bulk_create(rows)


@transaction.atomic
def start_next_season(user):
    ensure_active_season()
    if HistoricalSeason.objects.filter(status=HistoricalSeason.ACTIVE).exists():
        raise ValueError("Finalise the active season before starting the next one.")
    latest = HistoricalSeason.objects.order_by("-number").first()
    number = (latest.number if latest else 0) + 1
    league = active_league()
    season = HistoricalSeason.objects.create(
        number=number,
        status=HistoricalSeason.ACTIVE,
        league=league,
        clubs_count=Team.objects.filter(league=league).count() if league else 0,
    )
    League.objects.filter(is_active=True).update(season=str(number))
    log_site_change(
        user,
        action="season.start",
        object_type="HistoricalSeason",
        object_id=season.pk,
        object_label=f"Season {season.number}",
        summary=f"Started Season {season.number}.",
    )
    return season


@transaction.atomic
def save_season_draft(season, user, *, metadata=None, awards=None, tots=None):
    if season.is_locked and getattr(user, "role", None) != "OWNER":
        raise PermissionError("Only the Owner can edit a locked historical season.")
    metadata = metadata or {}
    awards = awards or {}
    if metadata.get("year_label") is not None:
        season.year_label = (metadata.get("year_label") or "").strip()
    if "start_date" in metadata:
        season.start_date = metadata.get("start_date") or None
    if "end_date" in metadata:
        season.end_date = metadata.get("end_date") or None
    if metadata.get("tots_formation"):
        season.tots_formation = metadata["tots_formation"]
    _apply_award_overrides(season, awards)
    if tots is not None:
        _save_tots(season, tots)
    if not season.is_finalized:
        league = season.league or active_league()
        overview = live_overview(league, season.number)
        season.clubs_count = overview["clubs_count"]
        season.games_played = overview["games_played"]
    season.save()
    log_site_change(
        user,
        action="season.draft",
        object_type="HistoricalSeason",
        object_id=season.pk,
        object_label=f"Season {season.number}",
        summary=f"Updated Season {season.number} details.",
    )
    return season


def unlock_season(season, user):
    if getattr(user, "role", None) != "OWNER":
        raise PermissionError("Only the Owner can unlock a historical season.")
    season.is_locked = False
    season.save(update_fields=["is_locked"])
    log_site_change(
        user,
        action="season.unlock",
        object_type="HistoricalSeason",
        object_id=season.pk,
        object_label=f"Season {season.number}",
        summary=f"Unlocked Season {season.number} for correction.",
    )
    return season


def lock_season(season, user):
    if getattr(user, "role", None) not in ("OWNER", "ADMIN"):
        raise PermissionError("Owner or Admin can lock a historical season.")
    season.is_locked = True
    season.save(update_fields=["is_locked"])
    return season


def table_from_snapshot(season):
    rows = []
    for row in season.table_rows.select_related("team").all():
        rows.append(
            {
                "position": row.position,
                "team": row.team,
                "team_name": row.team_name,
                "played": row.played,
                "wins": row.wins,
                "draws": row.draws,
                "losses": row.losses,
                "gf": row.gf,
                "ga": row.ga,
                "gd": row.gd,
                "points": row.points,
            }
        )
    return rows


def tots_display(season):
    slots = formation_slots(season.tots_formation or "4-2-3-1")
    picks = {pick.slot: pick for pick in season.tots_picks.select_related("player").all()}
    dots = []
    filled = 0
    for index, (slot, x, y) in enumerate(slots):
        pick = picks.get(slot)
        name = (pick.player_name if pick else "") or (pick.player.name if pick and pick.player else "")
        if name:
            filled += 1
        dots.append(
            {
                "slot": slot,
                "x": x,
                "y": y,
                "player": pick.player if pick else None,
                "player_name": name,
                "sort_order": index,
            }
        )
    return {"formation": season.tots_formation or "4-2-3-1", "dots": dots, "filled": filled}


def _club_card(team, name):
    if team or name:
        return {"kind": "club", "team": team, "name": name, "empty": False}
    return {"kind": "club", "team": None, "name": "", "empty": True, "value": EMPTY_AWARD}


def _player_card(player, name, detail=""):
    if player or name:
        return {
            "kind": "player",
            "player": player,
            "name": name,
            "detail": detail,
            "empty": False,
        }
    return {"kind": "player", "player": None, "name": "", "detail": "", "empty": True, "value": EMPTY_AWARD}


def award_cards(season, *, live=None):
    tots = tots_display(season)
    cards = []
    for key, label, kind in AWARD_DEFS:
        card = {"key": key, "label": label, "kind": kind, "empty": True, "value": EMPTY_AWARD}
        if key == "league_winner":
            card.update(_club_card(season.league_winner, season.league_winner_name))
        elif key == "cup_winner":
            card.update(_club_card(season.cup_winner, season.cup_winner_name))
        elif key == "manager":
            if season.manager_of_season_name or season.manager_of_season:
                card.update(
                    {
                        "kind": "manager",
                        "name": season.manager_of_season_name
                        or (season.manager_of_season.display_name if season.manager_of_season else ""),
                        "detail": season.manager_of_season_club,
                        "empty": False,
                    }
                )
        elif key == "tots":
            card.update(
                {
                    "kind": "tots",
                    "formation": tots["formation"],
                    "dots": tots["dots"],
                    "empty": tots["filled"] == 0,
                    "value": EMPTY_AWARD if tots["filled"] == 0 else tots["formation"],
                }
            )
        elif key == "ballon_dor":
            card.update(_player_card(season.ballon_dor, season.ballon_dor_name))
        elif key == "top_assists":
            detail = f"{season.top_assists_count} ASSISTS" if season.top_assists_count else ""
            card.update(_player_card(season.top_assists_player, season.top_assists_name, detail))
        elif key == "young_player":
            card.update(_player_card(season.young_player, season.young_player_name))
        elif key == "top_goalkeeper":
            card.update(_player_card(season.top_goalkeeper, season.top_goalkeeper_name))
        elif key == "fair_play":
            card.update(_club_card(season.fair_play_team, season.fair_play_name))
        elif key == "biggest_win":
            if season.biggest_win_home_name or season.biggest_win_away_name:
                card.update(
                    {
                        "kind": "match",
                        "home": season.biggest_win_home,
                        "away": season.biggest_win_away,
                        "home_name": season.biggest_win_home_name,
                        "away_name": season.biggest_win_away_name,
                        "home_goals": season.biggest_win_home_goals,
                        "away_goals": season.biggest_win_away_goals,
                        "empty": False,
                    }
                )
        elif key == "unbeaten_run":
            if season.unbeaten_team_name or season.unbeaten_team:
                card.update(
                    {
                        "kind": "club",
                        "team": season.unbeaten_team,
                        "name": season.unbeaten_team_name,
                        "detail": f"{season.unbeaten_games} GAMES" if season.unbeaten_games else "",
                        "empty": False,
                    }
                )
        elif key == "top_scorer":
            detail = f"{season.top_scorer_goals} GOALS" if season.top_scorer_goals else ""
            extra = _player_card(season.top_scorer, season.top_scorer_name, detail)
            extra["kicker"] = "Golden Boot"
            card.update(extra)
        card["label"] = label
        card["key"] = key
        cards.append(card)
    return cards


def page_context(selected_number=None, *, show_full_table=False):
    seasons = all_seasons()
    if not seasons:
        return {
            "seasons": [],
            "selected": None,
            "awards": [],
            "table": [],
            "past_seasons": [],
            "show_full_table": show_full_table,
        }
    selected = None
    if selected_number:
        selected = next((item for item in seasons if item.number == int(selected_number)), None)
    if selected is None:
        selected = next((item for item in reversed(seasons) if item.is_active), None) or seasons[-1]
    league = selected.league or active_league()
    live = None
    if selected.is_active:
        live = live_overview(league, selected.number)
        selected.clubs_count = live["clubs_count"]
        selected.games_played = live["games_played"]
        table = live["table"]
    else:
        table = table_from_snapshot(selected)
        if not table and league:
            table = []
    awards = award_cards(selected, live=live)
    past = [item for item in seasons if item.is_finalized and item.pk != selected.pk]
    return {
        "seasons": seasons,
        "selected": selected,
        "awards": awards,
        "table": table,
        "table_preview": table[:5],
        "past_seasons": past,
        "show_full_table": show_full_table,
        "active_league": league,
        "live_overview": live,
        "tots": tots_display(selected),
    }


def eligible_season_players(league, season_number):
    qs = Player.objects.select_related("mgl_team").order_by("name")
    if league:
        squad = list(qs.filter(mgl_team__league=league)[:500])
        if squad:
            return squad
    return list(qs[:400])


def young_player_suggestions(league, season_number, limit=8):
    players = eligible_season_players(league, season_number)
    ranked = []
    for player in players:
        age = player_age(player)
        if age is None or age > 23:
            continue
        ranked.append((age, player.name, player))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked[:limit]]
