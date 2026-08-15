from django.core.validators import MinValueValidator
from django.db import models
from apps.studios.validators import validate_iana_timezone


class Studio(models.Model):
    name = models.CharField(max_length=255)

    timezone = models.CharField(
        max_length=64,
        help_text="e.g. Asia/Kolkata",
        validators=[validate_iana_timezone],
    )

    cancellation_cutoff_hours = models.PositiveIntegerField(
        default=4,
        validators=[MinValueValidator(0)],
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name