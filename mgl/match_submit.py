"""Parse and validate a match result on the existing submission models."""

from decimal import Decimal, InvalidOperation

from mgl.models import (
    AssistEvent,
    DefenderRating,
    GKSave,
    GoalEvent,
    MatchSubmission,
    TeamMatchStats,
)
from players.models import Player

MAX_GOALS = 30
MAX_SHOTS = 100
MAX_CARDS = 11
DEFENDER_POSITIONS = ("CB", "LB", "RB", "LWB", "RWB")


class MatchSubmitError(ValueError):
    pass


def _int(post, key, default=0, minimum=0, maximum=100):
    raw = post.get(key, default)
    if raw in (None, ""):
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise MatchSubmitError(f"Invalid number for {key}.") from exc
    if value < minimum or value > maximum:
        raise MatchSubmitError(f"{key} must be between {minimum} and {maximum}.")
    return value


def _decimal_rating(raw):
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MatchSubmitError("Defender ratings must be a number between 0.0 and 10.0.") from exc
    if value < Decimal("0.0") or value > Decimal("10.0"):
        raise MatchSubmitError("Defender ratings must be between 0.0 and 10.0.")
    return value.quantize(Decimal("0.1"))


def _player_id(post, key):
    raw = (post.get(key) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise MatchSubmitError("Invalid player selection.") from exc


def _club_player(player_id, team):
    if not player_id:
        return None
    player = Player.objects.filter(pk=player_id, mgl_team=team).first()
    if player is None:
        raise MatchSubmitError(f"Selected player is not on {team.name}.")
    return player


def parse_side(post, prefix, team):
    goals = _int(post, prefix + "goals", 0, 0, MAX_GOALS)
    shots = _int(post, prefix + "shots", 0, 0, MAX_SHOTS)
    possession = _int(post, prefix + "possession", 50, 0, 100)
    yellow = _int(post, prefix + "yellow_cards", 0, 0, MAX_CARDS)
    red = _int(post, prefix + "red_cards", 0, 0, MAX_CARDS)
    scorers = []
    assists = []
    for index in range(1, goals + 1):
        scorer_id = _player_id(post, f"{prefix}goal_{index}")
        if not scorer_id:
            raise MatchSubmitError(f"Select a scorer for {team.name} goal {index}.")
        scorer = _club_player(scorer_id, team)
        scorers.append(scorer)
        assist_id = _player_id(post, f"{prefix}assist_{index}")
        assist = _club_player(assist_id, team) if assist_id else None
        if assist and assist.id == scorer.id:
            raise MatchSubmitError("A player cannot assist their own goal.")
        assists.append(assist)
    for index in range(goals + 1, MAX_GOALS + 1):
        if _player_id(post, f"{prefix}goal_{index}"):
            raise MatchSubmitError("Too many goalscorers for the number of goals.")
    ratings = []
    for player in Player.objects.filter(mgl_team=team, position__in=DEFENDER_POSITIONS):
        value = _decimal_rating(post.get(f"{prefix}def_{player.id}"))
        if value is not None:
            ratings.append((player, value))
    saves = []
    for player in Player.objects.filter(mgl_team=team, position="GK"):
        raw = post.get(f"{prefix}save_{player.id}")
        if raw in (None, ""):
            continue
        count = _int(post, f"{prefix}save_{player.id}", 0, 0, 20)
        if count:
            saves.append((player, count))
    return {
        "team": team,
        "goals": goals,
        "shots": shots,
        "possession": possession,
        "yellow_cards": yellow,
        "red_cards": red,
        "scorers": scorers,
        "assists": assists,
        "ratings": ratings,
        "saves": saves,
    }


def save_match_submission(fixture, user, post):
    if MatchSubmission.objects.filter(fixture=fixture).exists():
        raise MatchSubmitError("This match has already been submitted.")
    home = parse_side(post, "home_", fixture.home_team)
    away = parse_side(post, "away_", fixture.away_team)
    if home["possession"] + away["possession"] != 100:
        raise MatchSubmitError("Home and away possession must add up to 100%.")
    submission = MatchSubmission.objects.create(
        fixture=fixture,
        submitted_by=user,
        status="PENDING",
    )
    for side in (home, away):
        stats = TeamMatchStats.objects.create(
            submission=submission,
            team=side["team"],
            goals=side["goals"],
            shots=side["shots"],
            possession=side["possession"],
            yellow_cards=side["yellow_cards"],
            red_cards=side["red_cards"],
        )
        for player in side["scorers"]:
            GoalEvent.objects.create(team_stats=stats, player=player)
        for player in side["assists"]:
            if player is not None:
                AssistEvent.objects.create(team_stats=stats, player=player)
        for player, rating in side["ratings"]:
            DefenderRating.objects.create(
                team_stats=stats, player=player, rating=rating
            )
        for player, count in side["saves"]:
            GKSave.objects.create(team_stats=stats, player=player, saves=count)
    return submission
