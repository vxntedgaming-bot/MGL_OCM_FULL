from django.db import models


class League(models.Model):
    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=20)
    season = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    display_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Public label. Canonical name/short_name stay unchanged so league structure is not rewritten.",
    )
    description = models.TextField(blank=True)
    logo = models.ImageField(
        upload_to="leagues/",
        blank=True,
        null=True,
    )
    display_order = models.PositiveSmallIntegerField(default=0)

    @property
    def public_name(self):
        return (self.display_name or "").strip() or self.name

    def __str__(self):
        return f"{self.public_name} - {self.season}"
