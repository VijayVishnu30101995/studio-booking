from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.credits.models import CreditPack

User = get_user_model()


class CreditPackSerializer(serializers.ModelSerializer):
    credits = serializers.IntegerField(
        write_only=True,
        min_value=1,
    )

    class Meta:
        model = CreditPack
        fields = [
            "id",
            "member",
            "credits",
            "credits_granted",
            "grant_date",
            "expiry_date",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "credits_granted",
            "created_at",
        ]

    def validate_member(self, member):
        if member.role != "MEMBER":
            raise serializers.ValidationError(
                "Credit packs can only be granted to members."
            )

        return member

    def validate(self, attrs):
        if attrs["expiry_date"] <= attrs["grant_date"]:
            raise serializers.ValidationError(
                {
                    "expiry_date": (
                        "Expiry date must be after grant date."
                    )
                }
            )

        return attrs
