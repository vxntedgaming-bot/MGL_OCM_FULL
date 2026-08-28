from django.conf import settings
from django.db import models


class ManagerApplication(models.Model):

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="manager_application",
    )

    display_name = models.CharField(max_length=100)

    gamertag = models.CharField(max_length=100)

    preferred_team = models.CharField(
        max_length=100,
        blank=True,
    )

    tokens = models.DecimalField(max_digits=8, decimal_places=2, default=20)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=PENDING,
    )

    submitted_at = models.DateTimeField(auto_now_add=True)

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manager_applications_reviewed",
    )

    def __str__(self):
        return f"{self.display_name} - {self.status}"
