from mgl.models import ApprovalStatus, Fixture


def build_league_table(league, season_number=None):
    """
    Super League / Premier League standings from approved, completed fixtures.
    Every club in the league is included even if it has not played.
    """

    if league is None:
        return []

    rows = {}
    form_events = {}
    for team in league.teams.select_related("manager").prefetch_related("players").order_by("name"):
        rows[team.id] = {
            "team": team,
            "manager": getattr(team, "manager", None),
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "gf": 0,
            "ga": 0,
            "gd": 0,
            "points": 0,
            "goals": sum((player.goals or 0) for player in team.players.all()),
            "assists": sum((player.assists or 0) for player in team.players.all()),
            "form": [],
        }
        form_events[team.id] = []

    fixtures = Fixture.objects.filter(
        league=league,
        status="COMPLETED",
        is_released=True,
        submission__status=ApprovalStatus.APPROVED,
    )
    if season_number is not None:
        fixtures = fixtures.filter(season_number=season_number)
    fixtures = (
        fixtures.select_related("submission")
        .prefetch_related("submission__team_stats")
        .order_by("season_number", "matchweek", "id")
    )

    for fixture in fixtures:
        if fixture.home_team_id == fixture.away_team_id:
            continue
        home = rows.get(fixture.home_team_id)
        away = rows.get(fixture.away_team_id)
        if not home or not away:
            continue
        try:
            stats = {
                row.team_id: row.goals
                for row in fixture.submission.team_stats.all()
            }
        except Exception:
            continue
        home_goals = stats.get(fixture.home_team_id)
        away_goals = stats.get(fixture.away_team_id)
        if home_goals is None or away_goals is None:
            continue

        home["played"] += 1
        away["played"] += 1
        home["gf"] += home_goals
        home["ga"] += away_goals
        away["gf"] += away_goals
        away["ga"] += home_goals

        if home_goals > away_goals:
            home["wins"] += 1
            away["losses"] += 1
            home["points"] += 3
            form_events[fixture.home_team_id].append("W")
            form_events[fixture.away_team_id].append("L")
        elif away_goals > home_goals:
            away["wins"] += 1
            home["losses"] += 1
            away["points"] += 3
            form_events[fixture.away_team_id].append("W")
            form_events[fixture.home_team_id].append("L")
        else:
            home["draws"] += 1
            away["draws"] += 1
            home["points"] += 1
            away["points"] += 1
            form_events[fixture.home_team_id].append("D")
            form_events[fixture.away_team_id].append("D")

    table = list(rows.values())
    for row in table:
        row["gd"] = row["gf"] - row["ga"]
        row["form"] = form_events.get(row["team"].id, [])[-5:]
    table.sort(
        key=lambda row: (
            -row["points"],
            -row["gd"],
            -row["gf"],
            row["team"].name.lower(),
        )
    )
    for index, row in enumerate(table, start=1):
        row["position"] = index
    return table


def build_live_league_table(league):
    from mgl.season_history import current_season_number

    return build_league_table(league, season_number=current_season_number())
