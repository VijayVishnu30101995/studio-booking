from django.contrib.auth.models import AbstractUser
from django.db import models


class UserRole(models.TextChoices):
    STAFF = "STAFF", "Staff"
    MEMBER = "MEMBER", "Member"


class User(AbstractUser):
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.MEMBER,
    )

    def __str__(self) -> str:
        return self.email or self.username
