from django.db import models
from django.conf import settings


class Club(models.Model):
    name = models.CharField(max_length=100, unique=True)

    logo = models.ImageField(
        upload_to="club_logos/",
        blank=True,
        null=True
    )

    manager = models.OneToOneField(
    settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="managed_club"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
