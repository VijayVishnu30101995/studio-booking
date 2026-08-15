from django.conf import settings
from django.db import models


class WaitlistEntry(models.Model):
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="waitlist_entries",
    )

    fitness_class = models.ForeignKey(
        "classes.FitnessClass",
        on_delete=models.PROTECT,
        related_name="waitlist_entries",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

        constraints = [
            models.UniqueConstraint(
                fields=["member", "fitness_class"],
                name="unique_member_class_waitlist",
            ),
        ]

        indexes = [
            models.Index(
                fields=["fitness_class", "created_at"],
                name="waitlist_class_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.member.email} - "
            f"{self.fitness_class}"
        )