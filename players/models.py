from django.db import models


class Player(models.Model):
    POSITION_CHOICES = [
        ("GK", "Goalkeeper"),
        ("CB", "Centre Back"),
        ("LB", "Left Back"),
        ("RB", "Right Back"),
        ("LWB", "Left Wing Back"),
        ("RWB", "Right Wing Back"),
        ("CDM", "Defensive Midfielder"),
        ("CM", "Central Midfielder"),
        ("CAM", "Attacking Midfielder"),
        ("LM", "Left Midfielder"),
        ("RM", "Right Midfielder"),
        ("LW", "Left Winger"),
        ("RW", "Right Winger"),
        ("ST", "Striker"),
        ("CF", "Centre Forward"),
    ]

    name = models.CharField(max_length=100)

    fc27_id = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
    )

    fc27_club = models.CharField(
        max_length=100,
        blank=True,
    )

    image_url = models.URLField(
        blank=True,
    )

    player_face_url = models.URLField(
        blank=True,
    )

    preferred_foot = models.CharField(
        max_length=20,
        blank=True,
    )

    weak_foot = models.PositiveSmallIntegerField(
        default=0,
    )

    skill_moves = models.PositiveSmallIntegerField(
        default=0,
    )

    height_cm = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    weight_kg = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    age = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    card_tier = models.CharField(max_length=10, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    nationality = models.CharField(max_length=100, blank=True)

    position = models.CharField(
        max_length=10,
        choices=POSITION_CHOICES,
        blank=True,
    )

    overall = models.PositiveIntegerField(default=0)
    pace = models.PositiveIntegerField(default=0)
    shooting = models.PositiveIntegerField(default=0)
    passing = models.PositiveIntegerField(default=0)
    dribbling = models.PositiveIntegerField(default=0)
    defending = models.PositiveIntegerField(default=0)
    physical = models.PositiveIntegerField(default=0)

    # FC26 individual attributes. Null means the source cell was empty.
    # These are separate from the six card ratings above and from MGL stats.
    fc_work_rate = models.CharField(max_length=32, blank=True)
    fc_sprint_speed = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_acceleration = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_positioning = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_finishing = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_shot_power = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_long_shots = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_volleys = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_penalties = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_vision = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_crossing = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_fk_accuracy = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_short_passing = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_long_passing = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_curve = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_dribbling = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_agility = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_balance = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_reactions = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_ball_control = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_composure = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_interceptions = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_heading = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_marking = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_standing_tackle = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_sliding_tackle = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_jumping = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_stamina = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_strength = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_aggression = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_gk_diving = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_gk_handling = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_gk_kicking = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_gk_positioning = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_gk_reflexes = models.PositiveSmallIntegerField(null=True, blank=True)
    fc_gk_speed = models.PositiveSmallIntegerField(null=True, blank=True)

    # MGL information
    mgl_team = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="players",
    )

    is_free_agent = models.BooleanField(
        default=False,
        help_text=(
            "True only for Free Agents (no-bid auction or club release). "
            "Unused FC26 pool players are unassigned, not free agents."
        ),
    )

    # MGL statistics
    appearances = models.PositiveIntegerField(default=0)
    goals = models.PositiveIntegerField(default=0)
    assists = models.PositiveIntegerField(default=0)

    average_rating = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=0,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def calculated_tier(self):
        if self.overall >= 75: return "GOLD"
        if self.overall >= 65: return "SILVER"
        return "BRONZE"

    def __str__(self):
        if self.mgl_team:
            return f"{self.name} - {self.mgl_team.name}"
        return self.name
