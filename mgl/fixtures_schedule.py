"""Single round-robin fixtures on the existing Fixture model.

Does not delete or rewrite existing valid fixtures. Does not invent clubs.
lineup_deadline stays empty so a deadline can be added later.
"""

from mgl.models import Fixture
from mgl.season_history import current_season_number
from teams.models import Team


TEAMS_PER_LEAGUE = 14
GAMES_PER_TEAM = 13
FIXTURES_PER_LEAGUE = 91


def pair_key(home_id, away_id):
    return frozenset((home_id, away_id))


def existing_pair_keys(league):
    keys = set()
    for row in Fixture.objects.filter(league=league).values_list(
        "home_team_id", "away_team_id"
    ):
        keys.add(pair_key(*row))
    return keys


def round_robin_pairings(teams):
    """Circle method. Each team plays every other team once."""
    clubs = list(teams)
    count = len(clubs)
    if count < 2:
        return []
    rotation = clubs[:]
    if count % 2:
        rotation.append(None)
        count += 1
    pairings = []
    rounds = count - 1
    for matchweek in range(1, rounds + 1):
        for index in range(count // 2):
            home = rotation[index]
            away = rotation[count - 1 - index]
            if home is None or away is None:
                continue
            if matchweek % 2 == 0:
                home, away = away, home
            pairings.append((matchweek, home, away))
        rotation = [rotation[0]] + [rotation[-1]] + rotation[1:-1]
    return pairings


def ensure_round_robin_fixtures(league, *, release=True):
    """
    Create missing single round-robin fixtures for a 14-team league.

    Returns a dict with created/skipped counts. Existing pairings are left alone.
    """
    teams = list(Team.objects.filter(league=league).order_by("id"))
    if len(teams) != TEAMS_PER_LEAGUE:
        return {
            "created": 0,
            "skipped_existing": 0,
            "reason": f"{league.short_name} has {len(teams)} clubs, need {TEAMS_PER_LEAGUE}.",
        }
    existing = existing_pair_keys(league)
    created = 0
    skipped = 0
    for matchweek, home, away in round_robin_pairings(teams):
        key = pair_key(home.id, away.id)
        if key in existing:
            skipped += 1
            continue
        Fixture.objects.create(
            league=league,
            home_team=home,
            away_team=away,
            matchweek=matchweek,
            is_released=release,
            status="SCHEDULED",
            season_number=current_season_number(),
        )
        existing.add(key)
        created += 1
    return {
        "created": created,
        "skipped_existing": skipped,
        "reason": "",
        "total": Fixture.objects.filter(league=league).count(),
    }
