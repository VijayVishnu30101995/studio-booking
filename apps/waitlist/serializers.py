from rest_framework import serializers

from apps.waitlist.models import WaitlistEntry


class WaitlistEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = WaitlistEntry
        fields = [
            "id",
            "member",
            "fitness_class",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "member",
            "created_at",
        ]