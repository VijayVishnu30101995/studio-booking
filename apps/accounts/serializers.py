from django.contrib.auth import authenticate
from rest_framework import serializers

from apps.accounts.models import User


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate(self, attrs):
        identifier = attrs["identifier"]
        password = attrs["password"]

        user = User.objects.filter(username=identifier).first()

        if user is None:
            user = User.objects.filter(email__iexact=identifier).first()

        if user is None:
            raise serializers.ValidationError(
                "Invalid username/email or password."
            )

        user = authenticate(
            username=user.username,
            password=password,
        )

        if user is None:
            raise serializers.ValidationError(
                "Invalid username/email or password."
            )

        if not user.is_active:
            raise serializers.ValidationError(
                "User account is inactive."
            )

        attrs["user"] = user
        return attrs


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
        ]
        read_only_fields = [
            "id",
            "role",
        ]