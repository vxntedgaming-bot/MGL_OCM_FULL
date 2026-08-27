from django.db import models


class League(models.Model):
    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=20)
    season = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.season}"
