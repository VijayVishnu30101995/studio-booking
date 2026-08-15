from django.core.validators import MinValueValidator
from django.db import models

from apps.studios.models import Studio


class FitnessClass(models.Model):
    studio = models.ForeignKey(
        Studio,
        on_delete=models.CASCADE,
        related_name="classes",
    )

    start_time = models.DateTimeField()

    duration_minutes = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )

    spots = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )

    credit_cost = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_time"]
        indexes = [
            models.Index(
                fields=["studio", "start_time"],
                name="class_studio_start_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.studio.name} - {self.start_time}"