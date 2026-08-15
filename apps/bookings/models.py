from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class BookingStatus(models.TextChoices):
    CONFIRMED = "CONFIRMED", "Confirmed"
    CANCELLED = "CANCELLED", "Cancelled"


class Booking(models.Model):
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bookings",
    )

    fitness_class = models.ForeignKey(
        "classes.FitnessClass",
        on_delete=models.PROTECT,
        related_name="bookings",
    )

    credits_charged = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )

    status = models.CharField(
        max_length=20,
        choices=BookingStatus.choices,
        default=BookingStatus.CONFIRMED,
    )

    idempotency_key = models.CharField(
        max_length=255,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["member", "fitness_class"],
                condition=models.Q(status="CONFIRMED"),
                name="unique_active_member_class_booking",
            ),
            models.UniqueConstraint(
                fields=["idempotency_key"],
                name="unique_booking_idempotency_key",
            ),
        ]

        indexes = [
            models.Index(
                fields=["fitness_class", "status"],
                name="booking_class_status_idx",
            ),
            models.Index(
                fields=["member", "status"],
                name="booking_member_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.member.email} - "
            f"{self.fitness_class} - "
            f"{self.status}"
        )