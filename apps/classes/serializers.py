from rest_framework import serializers

from apps.bookings.models import Booking, BookingStatus
from apps.classes.models import FitnessClass


class FitnessClassSerializer(serializers.ModelSerializer):
    available_spots = serializers.SerializerMethodField()
    studio_name = serializers.CharField(source="studio.name", read_only=True)

    class Meta:
        model = FitnessClass
        fields = [
            "id",
            "studio",
            "studio_name",
            "start_time",
            "duration_minutes",
            "spots",
            "credit_cost",
            "available_spots",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "available_spots",
            "created_at",
        ]

    def get_available_spots(self, obj: FitnessClass) -> int:
        confirmed_bookings = Booking.objects.filter(
            fitness_class=obj,
            status=BookingStatus.CONFIRMED,
        ).count()

        return obj.spots - confirmed_bookings
