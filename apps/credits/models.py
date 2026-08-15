from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class CreditPack(models.Model):
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="credit_packs",
    )

    credits_granted = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )

    grant_date = models.DateTimeField()

    expiry_date = models.DateTimeField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["expiry_date", "id"]

        indexes = [
            models.Index(
                fields=["member", "expiry_date"],
                name="credit_member_expiry_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.member.email} - "
            f"{self.credits_granted} credits"
        )

class CreditTransactionCause(models.TextChoices):
    GRANT = "GRANT", "Credit grant"
    BOOKING = "BOOKING", "Booking"
    REFUND = "REFUND", "Cancellation refund"

class CreditTransaction(models.Model):
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="credit_transactions",
    )

    credit_pack = models.ForeignKey(
        CreditPack,
        on_delete=models.PROTECT,
        related_name="transactions",
    )

    booking = models.ForeignKey(
        "bookings.Booking",
        on_delete=models.PROTECT,
        related_name="credit_transactions",
        null=True,
        blank=True,
    )

    amount = models.IntegerField()

    cause = models.CharField(
        max_length=20,
        choices=CreditTransactionCause.choices,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

        indexes = [
            models.Index(
                fields=["member", "created_at"],
                name="credit_tx_member_time_idx",
            ),
            models.Index(
                fields=["credit_pack", "created_at"],
                name="credit_tx_pack_time_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.member.email}: "
            f"{self.amount} ({self.cause})"
        )