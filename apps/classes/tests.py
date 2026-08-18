from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.bookings.models import Booking, BookingStatus
from apps.classes.models import FitnessClass
from apps.studios.models import Studio

from django.contrib.auth import get_user_model


User = get_user_model()


class ClassAPITests(APITestCase):
    def setUp(self):
        self.password = "StrongPassword123!"

        self.staff = User.objects.create_user(
            username="class_staff",
            email="class_staff@example.com",
            password=self.password,
            role=UserRole.STAFF,
        )

        self.member = User.objects.create_user(
            username="class_member",
            email="class_member@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        self.studio = Studio.objects.create(
            name="Kochi Fitness Studio",
            timezone="Asia/Kolkata",
            cancellation_cutoff_hours=4,
        )

        self.create_url = "/api/classes/"
        self.list_url = "/api/classes/"

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def create_class(self, **overrides):
        defaults = {
            "studio": self.studio,
            "start_time": timezone.now() + timedelta(days=1),
            "duration_minutes": 60,
            "spots": 10,
            "credit_cost": 2,
        }
        defaults.update(overrides)
        return FitnessClass.objects.create(**defaults)

    def test_staff_can_create_class(self):
        self.authenticate_as(self.staff)

        start_time = timezone.now() + timedelta(days=1)

        response = self.client.post(
            self.create_url,
            {
                "studio": self.studio.id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
                "spots": 10,
                "credit_cost": 2,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertEqual(
            response.data["studio"],
            self.studio.id,
        )
        self.assertEqual(
            response.data["duration_minutes"],
            60,
        )
        self.assertEqual(
            response.data["spots"],
            10,
        )
        self.assertEqual(
            response.data["credit_cost"],
            2,
        )

        self.assertTrue(
            FitnessClass.objects.filter(
                studio=self.studio,
                duration_minutes=60,
                spots=10,
                credit_cost=2,
            ).exists()
        )

    def test_member_cannot_create_class(self):
        self.authenticate_as(self.member)

        response = self.client.post(
            self.create_url,
            {
                "studio": self.studio.id,
                "start_time": (
                    timezone.now() + timedelta(days=1)
                ).isoformat(),
                "duration_minutes": 60,
                "spots": 10,
                "credit_cost": 2,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_unauthenticated_user_cannot_create_class(self):
        response = self.client.post(
            self.create_url,
            {
                "studio": self.studio.id,
                "start_time": (
                    timezone.now() + timedelta(days=1)
                ).isoformat(),
                "duration_minutes": 60,
                "spots": 10,
                "credit_cost": 2,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_authenticated_member_can_list_classes(self):
        fitness_class = self.create_class()

        self.authenticate_as(self.member)

        response = self.client.get(self.list_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            len(response.data),
            1,
        )
        self.assertEqual(
            response.data[0]["id"],
            fitness_class.id,
        )

    def test_authenticated_staff_can_list_classes(self):
        fitness_class = self.create_class()

        self.authenticate_as(self.staff)

        response = self.client.get(self.list_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            len(response.data),
            1,
        )
        self.assertEqual(
            response.data[0]["id"],
            fitness_class.id,
        )

    def test_unauthenticated_user_cannot_list_classes(self):
        response = self.client.get(self.list_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_can_retrieve_class(self):
        fitness_class = self.create_class()

        self.authenticate_as(self.member)

        response = self.client.get(
            f"/api/classes/{fitness_class.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            response.data["id"],
            fitness_class.id,
        )
        self.assertEqual(
            response.data["studio"],
            self.studio.id,
        )

    def test_available_spots_are_based_on_confirmed_bookings(self):
        fitness_class = self.create_class(spots=3)

        confirmed_member = User.objects.create_user(
            username="confirmed_member",
            email="confirmed@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        cancelled_member = User.objects.create_user(
            username="cancelled_member",
            email="cancelled@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        Booking.objects.create(
            member=confirmed_member,
            fitness_class=fitness_class,
            credits_charged=2,
            status=BookingStatus.CONFIRMED,
            idempotency_key="confirmed-booking-key",
        )

        Booking.objects.create(
            member=cancelled_member,
            fitness_class=fitness_class,
            credits_charged=2,
            status=BookingStatus.CANCELLED,
            idempotency_key="cancelled-booking-key",
        )

        self.authenticate_as(self.member)

        response = self.client.get(
            f"/api/classes/{fitness_class.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            response.data["available_spots"],
            2,
        )

    def test_invalid_duration_is_rejected(self):
        self.authenticate_as(self.staff)

        response = self.client.post(
            self.create_url,
            {
                "studio": self.studio.id,
                "start_time": (
                    timezone.now() + timedelta(days=1)
                ).isoformat(),
                "duration_minutes": 0,
                "spots": 10,
                "credit_cost": 2,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_invalid_spots_are_rejected(self):
        self.authenticate_as(self.staff)

        response = self.client.post(
            self.create_url,
            {
                "studio": self.studio.id,
                "start_time": (
                    timezone.now() + timedelta(days=1)
                ).isoformat(),
                "duration_minutes": 60,
                "spots": 0,
                "credit_cost": 2,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_invalid_credit_cost_is_rejected(self):
        self.authenticate_as(self.staff)

        response = self.client.post(
            self.create_url,
            {
                "studio": self.studio.id,
                "start_time": (
                    timezone.now() + timedelta(days=1)
                ).isoformat(),
                "duration_minutes": 60,
                "spots": 10,
                "credit_cost": 0,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_class_list_can_filter_by_start_date_range(self):
        now = timezone.now()

        before_range = self.create_class(
            start_time=now + timedelta(days=1),
        )
        in_range_one = self.create_class(
            start_time=now + timedelta(days=3),
        )
        in_range_two = self.create_class(
            start_time=now + timedelta(days=5),
        )
        after_range = self.create_class(
            start_time=now + timedelta(days=10),
        )

        self.authenticate_as(self.member)

        response = self.client.get(
            self.list_url,
            {
                "start_date": (
                    (now + timedelta(days=2)).date().isoformat()
                ),
                "end_date": (
                    (now + timedelta(days=6)).date().isoformat()
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        returned_ids = {
            item["id"]
            for item in response.data
        }

        self.assertIn(in_range_one.id, returned_ids)
        self.assertIn(in_range_two.id, returned_ids)

        self.assertNotIn(before_range.id, returned_ids)
        self.assertNotIn(after_range.id, returned_ids)

    def test_class_list_returns_classes_in_start_time_order(self):
        now = timezone.now()

        later_class = self.create_class(
            start_time=now + timedelta(days=5),
        )
        earlier_class = self.create_class(
            start_time=now + timedelta(days=2),
        )

        self.authenticate_as(self.member)

        response = self.client.get(self.list_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        returned_ids = [
            item["id"]
            for item in response.data
        ]

        self.assertEqual(
            returned_ids,
            [
                earlier_class.id,
                later_class.id,
            ],
        )
