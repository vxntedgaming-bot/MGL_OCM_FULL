from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):

    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"

    ROLE_CHOICES = [
        (OWNER, "Owner"),
        (ADMIN, "Admin"),
        (MANAGER, "Manager"),
    ]

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=MANAGER,
    )

    discord_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        unique=True,
    )

    def __str__(self):
        return self.username
