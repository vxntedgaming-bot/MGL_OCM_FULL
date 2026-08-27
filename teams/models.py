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

    budget = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Legacy field. MGL economy uses manager tokens.",
    )

    roster_limit = models.PositiveSmallIntegerField(default=30)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
