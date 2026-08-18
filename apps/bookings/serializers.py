from rest_framework import serializers

from apps.bookings.models import Booking


class BookingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = [
            "id",
            "member",
            "fitness_class",
            "credits_charged",
            "status",
            "idempotency_key",
            "created_at",
            "cancelled_at",
        ]
        read_only_fields = fields