from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.studios.models import Studio
from apps.studios.validators import validate_iana_timezone

User = get_user_model()

class IANATimezoneValidatorTests(SimpleTestCase):
    def test_accepts_valid_iana_timezones(self) -> None:
        valid_timezones = [
            "Asia/Kolkata",
            "America/New_York",
            "Europe/London",
        ]

        for timezone in valid_timezones:
            with self.subTest(timezone=timezone):
                validate_iana_timezone(timezone)

    def test_rejects_invalid_timezone(self) -> None:
        invalid_timezones = [
            "hello",
            "IST",
            "invalid/timezone",
        ]

        for timezone in invalid_timezones:
            with self.subTest(timezone=timezone), self.assertRaises(ValidationError):
                validate_iana_timezone(timezone)


class StudioAPITests(APITestCase):
    def setUp(self):
        self.password = "StrongPassword123!"

        self.staff = User.objects.create_user(
            username="studio_staff",
            email="staff@example.com",
            password=self.password,
            role=UserRole.STAFF,
        )

        self.member = User.objects.create_user(
            username="studio_member",
            email="member@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        self.create_url = "/api/studios/"

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def test_staff_can_create_studio(self):
        self.authenticate_as(self.staff)

        response = self.client.post(
            self.create_url,
            {
                "name": "Kochi Fitness Studio",
                "timezone": "Asia/Kolkata",
                "cancellation_cutoff_hours": 4,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertEqual(
            response.data["name"],
            "Kochi Fitness Studio",
        )
        self.assertEqual(
            response.data["timezone"],
            "Asia/Kolkata",
        )
        self.assertEqual(
            response.data["cancellation_cutoff_hours"],
            4,
        )

        self.assertTrue(
            Studio.objects.filter(
                name="Kochi Fitness Studio"
            ).exists()
        )

    def test_member_cannot_create_studio(self):
        self.authenticate_as(self.member)

        response = self.client.post(
            self.create_url,
            {
                "name": "Member Studio",
                "timezone": "Asia/Kolkata",
                "cancellation_cutoff_hours": 4,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertFalse(
            Studio.objects.filter(
                name="Member Studio"
            ).exists()
        )

    def test_unauthenticated_user_cannot_create_studio(self):
        response = self.client.post(
            self.create_url,
            {
                "name": "Unauthenticated Studio",
                "timezone": "Asia/Kolkata",
                "cancellation_cutoff_hours": 4,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_invalid_timezone_is_rejected(self):
        self.authenticate_as(self.staff)

        response = self.client.post(
            self.create_url,
            {
                "name": "Invalid Timezone Studio",
                "timezone": "IST",
                "cancellation_cutoff_hours": 4,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_negative_cancellation_cutoff_is_rejected(self):
        self.authenticate_as(self.staff)

        response = self.client.post(
            self.create_url,
            {
                "name": "Invalid Cutoff Studio",
                "timezone": "Asia/Kolkata",
                "cancellation_cutoff_hours": -1,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_staff_can_retrieve_studio(self):
        studio = Studio.objects.create(
            name="Existing Studio",
            timezone="Asia/Kolkata",
            cancellation_cutoff_hours=4,
        )

        self.authenticate_as(self.staff)

        response = self.client.get(
            f"/api/studios/{studio.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            response.data["name"],
            "Existing Studio",
        )

    def test_staff_can_update_studio(self):
        studio = Studio.objects.create(
            name="Original Studio",
            timezone="Asia/Kolkata",
            cancellation_cutoff_hours=4,
        )

        self.authenticate_as(self.staff)

        response = self.client.patch(
            f"/api/studios/{studio.id}/",
            {
                "name": "Updated Studio",
                "cancellation_cutoff_hours": 6,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        studio.refresh_from_db()

        self.assertEqual(
            studio.name,
            "Updated Studio",
        )
        self.assertEqual(
            studio.cancellation_cutoff_hours,
            6,
        )
        self.assertEqual(
            studio.timezone,
            "Asia/Kolkata",
        )

    def test_member_cannot_update_studio(self):
        studio = Studio.objects.create(
            name="Protected Studio",
            timezone="Asia/Kolkata",
            cancellation_cutoff_hours=4,
        )

        self.authenticate_as(self.member)

        response = self.client.patch(
            f"/api/studios/{studio.id}/",
            {
                "name": "Changed By Member",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        studio.refresh_from_db()

        self.assertEqual(
            studio.name,
            "Protected Studio",
        )
