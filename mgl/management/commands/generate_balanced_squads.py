import random

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from players.models import Player
from teams.models import Team
from mgl.models import PlayerOwnershipHistory


POSITIONS = {
    "GK": 2,
    "CB": 4,
    "LB": 2,
    "RB": 2,
    "CDM": 2,
    "CM": 2,
    "CAM": 2,
    "LM": 2,
    "RM": 2,
    "LW": 2,
    "RW": 2,
    "ST": 2,
}

MIN_OVR = 63
MAX_OVR = 74
TARGET_TOTAL = 1781
PLAYERS_PER_TEAM = 26


class Command(BaseCommand):

    help = "Generate balanced 26-player MGL squads."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Check the allocation without changing players.",
        )

    def handle(self, *args, **options):

        dry_run = options["dry_run"]

        teams = list(
            Team.objects
            .order_by("id")
        )

        if not teams:
            raise CommandError("No MGL teams exist.")

        self.stdout.write(
            f"Preparing balanced squads for {len(teams)} clubs."
        )

        # --------------------------------------------------
        # CHECK EXISTING SQUADS
        # --------------------------------------------------

        for team in teams:

            count = team.players.count()

            if count:
                raise CommandError(
                    f"{team.name} already has {count} players. "
                    "No players were changed."
                )

        # --------------------------------------------------
        # BUILD AVAILABLE PLAYER POOLS
        # --------------------------------------------------

        pools = {}

        for position, amount in POSITIONS.items():

            required = len(teams) * amount

            players = list(
                Player.objects.filter(
                    position=position,
                    overall__gte=MIN_OVR,
                    overall__lte=MAX_OVR,
                    is_free_agent=True,
                    mgl_team__isnull=True,
                )
            )

            if len(players) < required:

                raise CommandError(
                    f"Not enough {position} players. "
                    f"Need {required}, have {len(players)}."
                )

            random.shuffle(players)
            pools[position] = players

        self.stdout.write("")
        self.stdout.write("Position availability check:")

        for position, amount in POSITIONS.items():

            required = len(teams) * amount

            self.stdout.write(
                f"  {position}: "
                f"{required} required / "
                f"{len(pools[position])} available"
            )

        # --------------------------------------------------
        # CREATE GLOBAL RATING POOL
        # --------------------------------------------------

        rating_pool = []

        for rating in range(MIN_OVR, MAX_OVR + 1):

            rating_pool.extend(
                [rating] * self.rating_weight(rating)
            )

        # We only need enough ratings for every player.
        total_required = len(teams) * PLAYERS_PER_TEAM

        while len(rating_pool) < total_required:
            rating_pool.append(68)

        random.shuffle(rating_pool)

        # --------------------------------------------------
        # CREATE EQUAL TEAM TARGETS
        # --------------------------------------------------

        team_targets = {}

        for team in teams:

            ratings = self.create_team_ratings()

            if sum(ratings) != TARGET_TOTAL:

                raise CommandError(
                    f"Could not create balanced rating "
                    f"distribution for {team.name}."
                )

            team_targets[team.id] = ratings

        # --------------------------------------------------
        # SAFETY CHECK
        # --------------------------------------------------

        for team in teams:

            ratings = team_targets[team.id]

            if len(ratings) != PLAYERS_PER_TEAM:
                raise CommandError(
                    f"{team.name} does not have 26 ratings."
                )

            if sum(ratings) != TARGET_TOTAL:
                raise CommandError(
                    f"{team.name} does not total 1781 OVR."
                )

            if min(ratings) < MIN_OVR:
                raise CommandError(
                    f"{team.name} contains a rating below 63."
                )

            if max(ratings) > MAX_OVR:
                raise CommandError(
                    f"{team.name} contains a rating above 74."
                )

        # --------------------------------------------------
        # POSITION/RATING ALLOCATION
        # --------------------------------------------------

        allocations = {}

        for team in teams:

            allocations[team.id] = []

            ratings = team_targets[team.id]

            # Randomise positions.
            positions = []

            for position, amount in POSITIONS.items():

                positions.extend(
                    [position] * amount
                )

            random.shuffle(positions)

            # Try to match ratings to available players.
            for position, rating in zip(
                positions,
                ratings
            ):

                candidates = [
                    player
                    for player in pools[position]
                    if player.overall == rating
                ]

                # If that exact rating does not exist,
                # choose the closest available rating.
                if not candidates:

                    candidates = sorted(
                        pools[position],
                        key=lambda p: abs(
                            p.overall - rating
                        )
                    )

                    if not candidates:

                        raise CommandError(
                            f"No {position} players available."
                        )

                player = random.choice(
                    candidates[:min(10, len(candidates))]
                )

                pools[position].remove(player)

                allocations[team.id].append(player)

        # --------------------------------------------------
        # FINAL TEAM VALIDATION
        # --------------------------------------------------

        for team in teams:

            players = allocations[team.id]

            if len(players) != 26:

                raise CommandError(
                    f"{team.name} received "
                    f"{len(players)} players."
                )

            total = sum(
                player.overall
                for player in players
            )

            if total != TARGET_TOTAL:

                raise CommandError(
                    f"{team.name} received "
                    f"{total} OVR instead of "
                    f"{TARGET_TOTAL}."
                )

            for position, amount in POSITIONS.items():

                actual = sum(
                    1
                    for player in players
                    if player.position == position
                )

                if actual != amount:

                    raise CommandError(
                        f"{team.name}: {position} "
                        f"requires {amount}, got {actual}."
                    )

        # --------------------------------------------------
        # SHOW PREVIEW
        # --------------------------------------------------

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "ALL 14 CLUBS PASSED VALIDATION"
            )
        )

        self.stdout.write("")

        for team in teams:

            players = allocations[team.id]

            total = sum(
                player.overall
                for player in players
            )

            average = total / 26

            self.stdout.write(
                f"{team.name}: "
                f"26 players | "
                f"{total} OVR | "
                f"{average:.2f} average"
            )

        # --------------------------------------------------
        # DRY RUN
        # --------------------------------------------------

        if dry_run:

            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN — no players were changed."
                )
            )

            return

        # --------------------------------------------------
        # REAL DATABASE UPDATE
        # --------------------------------------------------

        with transaction.atomic():

            for team in teams:

                for player in allocations[team.id]:

                    player.mgl_team = team
                    player.is_free_agent = False

                    player.save(
                        update_fields=[
                            "mgl_team",
                            "is_free_agent",
                        ]
                    )

                    PlayerOwnershipHistory.objects.create(
                        player=player,
                        team=team,
                        manager=team.manager,
                        source="INITIAL_SQUAD",
                        reference=f"MGL_INITIAL_{team.id}",
                    )

                team.roster_limit = 30

                team.save(
                    update_fields=[
                        "roster_limit"
                    ]
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "MGL SQUADS GENERATED SUCCESSFULLY."
            )
        )

        self.stdout.write(
            f"{len(teams)} clubs received "
            f"{PLAYERS_PER_TEAM} players each."
        )

        self.stdout.write(
            f"{len(teams) * PLAYERS_PER_TEAM} "
            "players allocated."
        )

    # ======================================================
    # RATING GENERATOR
    # ======================================================

    def create_team_ratings(self):

        ratings = []

        # Start every team with 68.
        ratings = [68] * PLAYERS_PER_TEAM

        difference = TARGET_TOTAL - sum(ratings)

        # We need +13 total to reach 1781.
        while difference > 0:

            index = random.randrange(
                PLAYERS_PER_TEAM
            )

            if ratings[index] < MAX_OVR:

                ratings[index] += 1
                difference -= 1

        # Randomly move some players down and compensate
        # elsewhere to create realistic variation.
        for _ in range(20):

            high = random.randrange(
                PLAYERS_PER_TEAM
            )

            low = random.randrange(
                PLAYERS_PER_TEAM
            )

            if high == low:
                continue

            if (
                ratings[high] > MIN_OVR
                and ratings[low] < MAX_OVR
            ):

                ratings[high] -= 1
                ratings[low] += 1

        random.shuffle(ratings)

        return ratings

    def rating_weight(self, rating):

        weights = {
            63: 1,
            64: 1,
            65: 2,
            66: 3,
            67: 4,
            68: 5,
            69: 5,
            70: 4,
            71: 3,
            72: 2,
            73: 1,
            74: 1,
        }

        return weights.get(rating, 1)
