from mgl.models import ApprovalStatus, Fixture


def build_league_table(league):
    """
    Super League / Premier League standings from approved, completed fixtures.
    Every club in the league is included even if it has not played.
    """

    if league is None:
        return []

    rows = {}
    for team in league.teams.select_related("manager").order_by("name"):
        rows[team.id] = {
            "team": team,
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "gf": 0,
            "ga": 0,
            "gd": 0,
            "points": 0,
        }

    fixtures = (
        Fixture.objects.filter(
            league=league,
            status="COMPLETED",
            is_released=True,
            submission__status=ApprovalStatus.APPROVED,
        )
        .select_related("submission")
        .prefetch_related("submission__team_stats")
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
        elif away_goals > home_goals:
            away["wins"] += 1
            home["losses"] += 1
            away["points"] += 3
        else:
            home["draws"] += 1
            away["draws"] += 1
            home["points"] += 1
            away["points"] += 1

    table = list(rows.values())
    for row in table:
        row["gd"] = row["gf"] - row["ga"]
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
