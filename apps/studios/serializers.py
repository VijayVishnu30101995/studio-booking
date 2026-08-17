from rest_framework import serializers

from apps.studios.models import Studio


class StudioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Studio
        fields = [
            "id",
            "name",
            "timezone",
            "cancellation_cutoff_hours",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]