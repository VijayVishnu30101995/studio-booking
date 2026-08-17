from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import (
    BookingService,
    ClassFullError,
    DuplicateBookingError,
)
from apps.classes.models import FitnessClass
from apps.credits.models import CreditTransaction, CreditTransactionCause
from apps.credits.services import (
    CreditService,
    InsufficientCreditsError,
)
from apps.studios.models import Studio

class BookingServiceTests(TestCase):
    def setUp(self) -> None:
        self.member = User.objects.create_user(
            username="member",
            email="member@example.com",
            password="password123",
        )

        self.studio = Studio.objects.create(
            name="Test Studio",
            timezone="Asia/Kolkata",
            cancellation_cutoff_hours=4,
        )

        self.fitness_class = FitnessClass.objects.create(
            studio=self.studio,
            start_time=timezone.now() + timedelta(days=1),
            duration_minutes=60,
            spots=10,
            credit_cost=5,
        )

        CreditService.grant_pack(
            member=self.member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

    def test_book_class_successfully(self) -> None:
        booking = BookingService.book(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="booking-001",
        )

        self.assertEqual(booking.member, self.member)
        self.assertEqual(booking.fitness_class, self.fitness_class)
        self.assertEqual(booking.credits_charged, 5)
        self.assertEqual(booking.status, BookingStatus.CONFIRMED)
        self.assertEqual(booking.idempotency_key, "booking-001")

    def test_book_class_deducts_credits(self) -> None:
        BookingService.book(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="booking-002",
        )

        balance = CreditService.get_balance(
            member=self.member,
        )

        self.assertEqual(balance, 5)

        transaction = CreditTransaction.objects.get(
            member=self.member,
            cause=CreditTransactionCause.BOOKING,
        )

        self.assertEqual(transaction.amount, -5)

    def test_book_class_fails_with_insufficient_credits(self) -> None:
        expensive_class = FitnessClass.objects.create(
            studio=self.studio,
            start_time=timezone.now() + timedelta(days=2),
            duration_minutes=60,
            spots=10,
            credit_cost=20,
        )

        with self.assertRaises(InsufficientCreditsError):
            BookingService.book(
                member=self.member,
                fitness_class_id=expensive_class.id,
                idempotency_key="booking-003",
            )

        self.assertFalse(
            Booking.objects.filter(
                member=self.member,
                fitness_class=expensive_class,
            ).exists()
        )

    def test_book_class_fails_when_class_is_full(self) -> None:
        full_class = FitnessClass.objects.create(
            studio=self.studio,
            start_time=timezone.now() + timedelta(days=3),
            duration_minutes=60,
            spots=1,
            credit_cost=5,
        )

        BookingService.book(
            member=self.member,
            fitness_class_id=full_class.id,
            idempotency_key="booking-004",
        )

        another_member = User.objects.create_user(
            username="another-member",
            email="another@example.com",
            password="password123",
        )

        CreditService.grant_pack(
            member=another_member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

        with self.assertRaises(ClassFullError):
            BookingService.book(
                member=another_member,
                fitness_class_id=full_class.id,
                idempotency_key="booking-005",
            )

    def test_member_cannot_book_same_class_twice(self) -> None:
        BookingService.book(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="booking-006",
        )

        with self.assertRaises(DuplicateBookingError):
            BookingService.book(
                member=self.member,
                fitness_class_id=self.fitness_class.id,
                idempotency_key="booking-007",
            )

        booking_count = Booking.objects.filter(
            member=self.member,
            fitness_class=self.fitness_class,
            status=BookingStatus.CONFIRMED,
        ).count()

        self.assertEqual(booking_count, 1)

    def test_same_idempotency_key_returns_existing_booking(self) -> None:
        first_booking = BookingService.book(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="booking-008",
        )

        second_booking = BookingService.book(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="booking-008",
        )

        self.assertEqual(first_booking.id, second_booking.id)

        booking_count = Booking.objects.filter(
            member=self.member,
            fitness_class=self.fitness_class,
        ).count()

        self.assertEqual(booking_count, 1)

        balance = CreditService.get_balance(
            member=self.member,
        )

        self.assertEqual(balance, 5)