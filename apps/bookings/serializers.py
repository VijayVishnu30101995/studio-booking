from rest_framework import serializers

from apps.bookings.models import Booking


class BookingSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source="member.username", read_only=True)
    class Meta:
        model = Booking
        fields = [
            "id",
            "member",
            "member_name",
            "fitness_class",
            "credits_charged",
            "status",
            "idempotency_key",
            "created_at",
            "cancelled_at",
        ]
        read_only_fields = fields