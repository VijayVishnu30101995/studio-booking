from datetime import timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from concurrent.futures import ThreadPoolExecutor
from django.db import close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import (
    BookingAlreadyCancelledError,
    BookingService,
    CancellationService,
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

class BookingServiceTests(TransactionTestCase):
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

    def test_concurrent_booking_attempts_do_not_exceed_class_capacity(self) -> None:
        concurrent_class = FitnessClass.objects.create(
            studio=self.studio,
            start_time=timezone.now() + timedelta(days=4),
            duration_minutes=60,
            spots=1,
            credit_cost=5,
        )

        another_member = User.objects.create_user(
            username="concurrent-member",
            email="concurrent@example.com",
            password="password123",
        )

        CreditService.grant_pack(
            member=another_member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

        def attempt_booking(member: User, idempotency_key: str):
            close_old_connections()

            try:
                return BookingService.book(
                    member=member,
                    fitness_class_id=concurrent_class.id,
                    idempotency_key=idempotency_key,
                )
            except ClassFullError as exc:
                return exc
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    attempt_booking,
                    self.member,
                    "concurrent-booking-001",
                ),
                executor.submit(
                    attempt_booking,
                    another_member,
                    "concurrent-booking-002",
                ),
            ]

            results = [future.result() for future in futures]

        successful_bookings = [
            result
            for result in results
            if isinstance(result, Booking)
        ]

        failed_bookings = [
            result
            for result in results
            if isinstance(result, ClassFullError)
        ]

        self.assertEqual(len(successful_bookings), 1)
        self.assertEqual(len(failed_bookings), 1)

        confirmed_booking_count = Booking.objects.filter(
            fitness_class=concurrent_class,
            status=BookingStatus.CONFIRMED,
        ).count()

        self.assertEqual(confirmed_booking_count, 1)

    def test_cancel_booking_before_cutoff_refunds_credits(self) -> None:
        booking = BookingService.book(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="cancel-001",
        )

        balance_before_cancel = CreditService.get_balance(
            member=self.member,
        )
        self.assertEqual(balance_before_cancel, 5)

        cancelled_booking = CancellationService.cancel(
            booking_id=booking.id,
        )

        self.assertEqual(
            cancelled_booking.status,
            BookingStatus.CANCELLED,
        )
        self.assertIsNotNone(cancelled_booking.cancelled_at)

        balance_after_cancel = CreditService.get_balance(
            member=self.member,
        )
        self.assertEqual(balance_after_cancel, 10)

        refund_transaction = CreditTransaction.objects.get(
            member=self.member,
            booking=booking,
            cause=CreditTransactionCause.REFUND,
        )

        self.assertEqual(refund_transaction.amount, 5)

    def test_cancel_booking_after_cutoff_forfeits_credits(self) -> None:
        late_class = FitnessClass.objects.create(
            studio=self.studio,
            start_time=timezone.now() + timedelta(hours=2),
            duration_minutes=60,
            spots=10,
            credit_cost=5,
        )

        booking = BookingService.book(
            member=self.member,
            fitness_class_id=late_class.id,
            idempotency_key="cancel-002",
        )

        balance_before_cancel = CreditService.get_balance(
            member=self.member,
        )
        self.assertEqual(balance_before_cancel, 5)

        cancelled_booking = CancellationService.cancel(
            booking_id=booking.id,
        )

        self.assertEqual(
            cancelled_booking.status,
            BookingStatus.CANCELLED,
        )

        balance_after_cancel = CreditService.get_balance(
            member=self.member,
        )

        self.assertEqual(balance_after_cancel, 5)

        refund_exists = CreditTransaction.objects.filter(
            member=self.member,
            booking=booking,
            cause=CreditTransactionCause.REFUND,
        ).exists()

        self.assertFalse(refund_exists)

    def test_cancel_booking_twice_fails(self) -> None:
        booking = BookingService.book(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="cancel-003",
        )

        CancellationService.cancel(
            booking_id=booking.id,
        )

        with self.assertRaises(BookingAlreadyCancelledError):
            CancellationService.cancel(
                booking_id=booking.id,
            )

        refund_count = CreditTransaction.objects.filter(
            member=self.member,
            booking=booking,
            cause=CreditTransactionCause.REFUND,
        ).count()

        self.assertEqual(refund_count, 1)

    def test_cancel_booking_uses_studio_local_timezone(self) -> None:
        new_york_studio = Studio.objects.create(
            name="New York Studio",
            timezone="America/New_York",
            cancellation_cutoff_hours=4,
        )

        now_utc = timezone.now()

        class_start_local = now_utc.astimezone(
            ZoneInfo("America/New_York")
        ) + timedelta(hours=5)

        class_start_utc = class_start_local.astimezone(
            dt_timezone.utc
        )

        new_york_class = FitnessClass.objects.create(
            studio=new_york_studio,
            start_time=class_start_utc,
            duration_minutes=60,
            spots=10,
            credit_cost=5,
        )

        booking = BookingService.book(
            member=self.member,
            fitness_class_id=new_york_class.id,
            idempotency_key="cancel-timezone-001",
        )

        CancellationService.cancel(
            booking_id=booking.id,
        )

        balance = CreditService.get_balance(
            member=self.member,
        )

        self.assertEqual(balance, 10)

        refund_exists = CreditTransaction.objects.filter(
            member=self.member,
            booking=booking,
            cause=CreditTransactionCause.REFUND,
        ).exists()

        self.assertTrue(refund_exists)