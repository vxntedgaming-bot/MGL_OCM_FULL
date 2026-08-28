import random

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from mgl.models import PlayerOwnershipHistory
from players.models import Player
from teams.models import Team


# 26-player starter squads. Groups absorb FC26 position variants.
POSITION_GROUPS = [
    (["GK"], 2),
    (["CB"], 4),
    (["LB", "LWB"], 2),
    (["RB", "RWB"], 2),
    (["CDM", "CM"], 4),
    (["CAM"], 2),
    (["LM", "LW"], 3),
    (["RM", "RW"], 3),
    (["ST", "CF"], 4),
]

MIN_OVR = 64
MAX_OVR = 73
PLAYERS_PER_TEAM = 26


class Command(BaseCommand):
    help = "Give each empty MGL club a usable 26-player squad rated 64–73."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--team-id", type=int, default=None)
        parser.add_argument(
            "--official-sl1",
            action="store_true",
            help="Only fill the 14 official Super League 1 clubs.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        teams = Team.objects.order_by("id")
        if options["team_id"]:
            teams = teams.filter(pk=options["team_id"])
        if options["official_sl1"]:
            from teams.official_sl1 import OFFICIAL_SL1_SHORT_NAMES

            teams = teams.filter(short_name__in=OFFICIAL_SL1_SHORT_NAMES)
        teams = list(teams)
        if not teams:
            raise CommandError("No MGL teams exist.")

        targets = []
        for team in teams:
            if team.players.count():
                self.stdout.write(f"Skipping {team.name}: squad already exists.")
                continue
            targets.append(team)

        if not targets:
            raise CommandError("Every selected club already has a squad.")

        available = list(
            Player.objects.filter(
                is_free_agent=True,
                mgl_team__isnull=True,
                overall__gte=MIN_OVR,
                overall__lte=MAX_OVR,
            )
        )
        random.shuffle(available)
        if len(available) < PLAYERS_PER_TEAM * len(targets):
            raise CommandError(
                f"Need {PLAYERS_PER_TEAM * len(targets)} free agents rated "
                f"{MIN_OVR}–{MAX_OVR}, found {len(available)}."
            )

        used_ids = set()
        allocations = {}

        for team in targets:
            squad = []
            for positions, amount in POSITION_GROUPS:
                pool = [
                    player
                    for player in available
                    if player.id not in used_ids and player.position in positions
                ]
                take = min(amount, len(pool), PLAYERS_PER_TEAM - len(squad))
                chosen = pool[:take]
                squad.extend(chosen)
                used_ids.update(player.id for player in chosen)

            if len(squad) < PLAYERS_PER_TEAM:
                fillers = [
                    player
                    for player in available
                    if player.id not in used_ids
                ]
                needed = PLAYERS_PER_TEAM - len(squad)
                if len(fillers) < needed:
                    raise CommandError(
                        f"Not enough remaining 64–73 free agents for {team.name}."
                    )
                extra = fillers[:needed]
                squad.extend(extra)
                used_ids.update(player.id for player in extra)

            allocations[team.id] = squad[:PLAYERS_PER_TEAM]

        self.stdout.write(
            f"Ready to populate {len(targets)} club(s) with "
            f"{PLAYERS_PER_TEAM} players each (OVR {MIN_OVR}–{MAX_OVR})."
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no players were changed."))
            return

        with transaction.atomic():
            for team in targets:
                for player in allocations[team.id]:
                    player.mgl_team = team
                    player.is_free_agent = False
                    player.save(update_fields=["mgl_team", "is_free_agent"])
                    PlayerOwnershipHistory.objects.create(
                        player=player,
                        team=team,
                        manager=team.manager,
                        source="INITIAL_SQUAD",
                        reference=f"MGL_INITIAL_{team.id}",
                    )
                team.roster_limit = 30
                team.save(update_fields=["roster_limit"])

        self.stdout.write(self.style.SUCCESS("MGL squads generated."))
