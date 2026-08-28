from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from leagues.models import League
from mgl.models import Fixture, MarketTransaction
from players.models import Player
from teams.models import Team
from teams.official_sl1 import (
    OFFICIAL_SL1_SHORT_NAMES,
    ensure_official_sl1_clubs,
)


CSV_NAME = "fc26_players_mgl.csv"


class Command(BaseCommand):
    help = (
        "Idempotently create the 14 official Premier League clubs and import "
        "the FC26 player pool as unassigned players. Does not assign "
        "players to MGL clubs. Starting squads are a dry-run auction pool."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-import",
            action="store_true",
            help="Do not import fc26_players_mgl.csv.",
        )
        parser.add_argument(
            "--skip-squads",
            action="store_true",
            help="Deprecated. Squad fill is off by default.",
        )
        parser.add_argument(
            "--fill-squads",
            action="store_true",
            help=(
                "Assign 26-player 64–73 OVR squads to empty official clubs. "
                "Off by default so every club starts equal with 0 players."
            ),
        )

    def handle(self, *args, **options):
        league, created, reused = ensure_official_sl1_clubs()
        self.stdout.write(
            f"Super League 1 clubs: {len(created)} created, "
            f"{len(reused)} already present."
        )

        if not options["skip_import"]:
            csv_path = Path(settings.BASE_DIR) / CSV_NAME
            if not csv_path.exists():
                raise CommandError(f"Missing player CSV: {csv_path}")
            existing = (
                Player.objects.exclude(fc27_id__isnull=True)
                .exclude(fc27_id="")
                .count()
            )
            expected = self._csv_row_count(csv_path)
            if existing >= expected:
                self.stdout.write(
                    f"Player pool already has {existing} FC26 ids; skipping import."
                )
            else:
                self.stdout.write(f"Importing {csv_path.name} as unassigned players...")
                call_command("import_fc27", str(csv_path))

        fill_squads = options["fill_squads"] and not options["skip_squads"]
        if fill_squads:
            raise CommandError(
                "Squad auto-fill is disabled. Use propose_starting_auction_pool "
                "for a dry-run starting auction pool. Do not auto-assign players."
            )
        else:
            self.stdout.write(
                "Skipping squad fill. Imported players remain UNASSIGNED, not Free Agents."
            )

        self._report(league)

    @staticmethod
    def _csv_row_count(csv_path):
        import csv

        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            return sum(1 for row in csv.DictReader(handle) if (row.get("fc27_id") or "").strip())

    def _report(self, league):
        from mgl.player_state import market_counts

        official = Team.objects.filter(short_name__in=OFFICIAL_SL1_SHORT_NAMES).order_by("name")
        counts = market_counts()
        sl2 = League.objects.filter(short_name__iexact="SL2").count()
        fixtures = Fixture.objects.count()
        history = MarketTransaction.objects.count()

        self.stdout.write("")
        self.stdout.write(f"Active league: {league.name} ({league.short_name})")
        self.stdout.write(f"Official clubs: {official.count()}")
        for team in official:
            self.stdout.write(
                f"  {team.short_name} {team.name}: "
                f"{team.players.count()} players, {team.tokens} TKN, "
                f"manager={'none' if team.manager_id is None else team.manager.username}"
            )
        self.stdout.write(f"Players: {counts['players']}")
        self.stdout.write(f"Unassigned: {counts['unassigned']}")
        self.stdout.write(f"Free agents: {counts['free_agents']}")
        self.stdout.write(f"Live auctions: {counts['auctions']}")
        self.stdout.write(f"Club players: {counts['club_players']}")
        self.stdout.write(f"Super League 2 rows: {sl2}")
        self.stdout.write(f"Fixtures: {fixtures}")
        self.stdout.write(f"Market transactions: {history}")
        self.stdout.write(self.style.SUCCESS("populate_super_league_1 complete."))
