from django.conf import settings
from django.db import models


class Team(models.Model):
    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=20)

    league = models.ForeignKey(
        "leagues.League",
        on_delete=models.CASCADE,
        related_name="teams",
    )

    manager = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_team",
    )

    logo = models.ImageField(
        upload_to="teams/",
        blank=True,
        null=True,
    )

    badge_code = models.CharField(
        max_length=20,
        blank=True,
        help_text=(
            "Frozen official crest key. Display fallback only. "
            "Site Management never changes this when name or short_name is edited."
        ),
    )

    description = models.TextField(
        blank=True,
        help_text="Optional public club description. Display only; does not affect squads or fixtures.",
    )

    budget = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Legacy field. UFL economy uses manager tokens.",
    )

    roster_limit = models.PositiveSmallIntegerField(default=30)

    tokens = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=50,
        help_text="Club transfer budget in UFL tokens. Remains with the club if the manager leaves.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
