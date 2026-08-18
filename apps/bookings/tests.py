from datetime import timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
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

    def test_cancel_booking_promotes_waitlisted_member(self) -> None:
        from apps.waitlist.models import WaitlistEntry
        from apps.waitlist.services import WaitlistService

        full_class = FitnessClass.objects.create(
            studio=self.studio,
            start_time=timezone.now() + timedelta(days=1),
            duration_minutes=60,
            spots=1,
            credit_cost=5,
        )

        booking = BookingService.book(
            member=self.member,
            fitness_class_id=full_class.id,
            idempotency_key="cancel-waitlist-001",
        )

        waitlist_member = User.objects.create_user(
            username="waitlist-member",
            email="waitlist@example.com",
            password="password123",
        )

        CreditService.grant_pack(
            member=waitlist_member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

        WaitlistService.join(
            member=waitlist_member,
            fitness_class_id=full_class.id,
        )

        cancelled_booking = CancellationService.cancel(
            booking_id=booking.id,
        )

        promoted_booking = Booking.objects.get(
            member=waitlist_member,
            fitness_class=full_class,
            status=BookingStatus.CONFIRMED,
        )

        self.assertEqual(
            cancelled_booking.status,
            BookingStatus.CANCELLED,
        )

        self.assertEqual(
            promoted_booking.credits_charged,
            5,
        )

        self.assertFalse(
            WaitlistEntry.objects.filter(
                member=waitlist_member,
                fitness_class=full_class,
            ).exists()
        )

        balance = CreditService.get_balance(
            member=waitlist_member,
        )

        self.assertEqual(balance, 5)
    
    def test_cancel_booking_promotes_next_affordable_waitlist_member(self,) -> None:
        from apps.waitlist.models import WaitlistEntry
        from apps.waitlist.services import WaitlistService

        full_class = FitnessClass.objects.create(
            studio=self.studio,
            start_time=timezone.now() + timedelta(days=1),
            duration_minutes=60,
            spots=1,
            credit_cost=5,
        )

        booking = BookingService.book(
            member=self.member,
            fitness_class_id=full_class.id,
            idempotency_key="cancel-waitlist-002",
        )

        first_waitlist_member = User.objects.create_user(
            username="first-waitlist",
            email="first-waitlist@example.com",
            password="password123",
        )

        second_waitlist_member = User.objects.create_user(
            username="second-waitlist",
            email="second-waitlist@example.com",
            password="password123",
        )

        # First member has no credits.
        WaitlistService.join(
            member=first_waitlist_member,
            fitness_class_id=full_class.id,
        )

        # Second member can afford the class.
        CreditService.grant_pack(
            member=second_waitlist_member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

        WaitlistService.join(
            member=second_waitlist_member,
            fitness_class_id=full_class.id,
        )

        CancellationService.cancel(
            booking_id=booking.id,
        )

        promoted_booking = Booking.objects.get(
            member=second_waitlist_member,
            fitness_class=full_class,
            status=BookingStatus.CONFIRMED,
        )

        self.assertEqual(
            promoted_booking.credits_charged,
            5,
        )

        # The first member cannot afford the class,
        # so they remain at the front of the waitlist.
        self.assertTrue(
            WaitlistEntry.objects.filter(
                member=first_waitlist_member,
                fitness_class=full_class,
            ).exists()
        )

        # The promoted member leaves the waitlist.
        self.assertFalse(
            WaitlistEntry.objects.filter(
                member=second_waitlist_member,
                fitness_class=full_class,
            ).exists()
        )

        balance = CreditService.get_balance(
            member=second_waitlist_member,
        )

        self.assertEqual(balance, 5)

    def test_cancel_booking_without_waitlist_does_not_create_booking(self,) -> None:
        full_class = FitnessClass.objects.create(
            studio=self.studio,
            start_time=timezone.now() + timedelta(days=1),
            duration_minutes=60,
            spots=1,
            credit_cost=5,
        )

        booking = BookingService.book(
            member=self.member,
            fitness_class_id=full_class.id,
            idempotency_key="cancel-waitlist-003",
        )

        CancellationService.cancel(
            booking_id=booking.id,
        )

        confirmed_booking_count = Booking.objects.filter(
            fitness_class=full_class,
            status=BookingStatus.CONFIRMED,
        ).count()

        self.assertEqual(
            confirmed_booking_count,
            0,
        )
class BookingAPITests(APITestCase):
    def setUp(self):
        self.password = "StrongPassword123!"

        self.member = User.objects.create_user(
            username="booking_api_member",
            email="booking_api_member@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        self.other_member = User.objects.create_user(
            username="booking_api_other",
            email="booking_api_other@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        self.staff = User.objects.create_user(
            username="booking_api_staff",
            email="booking_api_staff@example.com",
            password=self.password,
            role=UserRole.STAFF,
        )

        self.studio = Studio.objects.create(
            name="Booking API Studio",
            timezone="Asia/Kolkata",
            cancellation_cutoff_hours=4,
        )

        self.fitness_class = FitnessClass.objects.create(
            studio=self.studio,
            start_time=timezone.now() + timedelta(days=1),
            duration_minutes=60,
            spots=2,
            credit_cost=5,
        )

        CreditService.grant_pack(
            member=self.member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

        CreditService.grant_pack(
            member=self.other_member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def book_url(self):
        return f"/api/classes/{self.fitness_class.id}/book/"

    def test_member_can_book_class(self):
        self.authenticate_as(self.member)

        response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-001",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertEqual(
            response.data["member"],
            self.member.id,
        )

        self.assertEqual(
            response.data["fitness_class"],
            self.fitness_class.id,
        )

        self.assertEqual(
            response.data["credits_charged"],
            5,
        )

        self.assertEqual(
            response.data["status"],
            BookingStatus.CONFIRMED,
        )

        self.assertEqual(
            response.data["idempotency_key"],
            "booking-api-001",
        )

        self.assertTrue(
            Booking.objects.filter(
                id=response.data["id"],
                member=self.member,
                fitness_class=self.fitness_class,
                status=BookingStatus.CONFIRMED,
            ).exists()
        )

    def test_booking_deducts_credits(self):
        self.authenticate_as(self.member)

        response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-002",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        balance = CreditService.get_balance(
            member=self.member,
        )

        self.assertEqual(balance, 5)

    def test_booking_requires_idempotency_key(self):
        self.authenticate_as(self.member)

        response = self.client.post(
            self.book_url(),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertFalse(
            Booking.objects.filter(
                member=self.member,
                fitness_class=self.fitness_class,
            ).exists()
        )

    def test_same_idempotency_key_returns_existing_booking(self):
        self.authenticate_as(self.member)

        first_response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-003",
        )

        second_response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-003",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            first_response.data["id"],
            second_response.data["id"],
        )

        self.assertEqual(
            Booking.objects.filter(
                member=self.member,
                fitness_class=self.fitness_class,
            ).count(),
            1,
        )

    def test_member_cannot_book_same_class_twice(self):
        self.authenticate_as(self.member)

        first_response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-004",
        )

        second_response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-005",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(
            Booking.objects.filter(
                member=self.member,
                fitness_class=self.fitness_class,
                status=BookingStatus.CONFIRMED,
            ).count(),
            1,
        )

    def test_booking_fails_when_class_is_full(self):
        self.authenticate_as(self.member)

        first_response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-006",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_201_CREATED,
        )

        self.authenticate_as(self.other_member)

        second_response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-007",
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_201_CREATED,
        )

        third_member = User.objects.create_user(
            username="booking_api_third",
            email="booking_api_third@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        CreditService.grant_pack(
            member=third_member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

        self.authenticate_as(third_member)

        response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-008",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_booking_fails_with_insufficient_credits(self):
        poor_member = User.objects.create_user(
            username="booking_api_poor",
            email="booking_api_poor@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        self.authenticate_as(poor_member)

        response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-009",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertFalse(
            Booking.objects.filter(
                member=poor_member,
                fitness_class=self.fitness_class,
            ).exists()
        )

    def test_unauthenticated_user_cannot_book(self):
        response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-010",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_staff_cannot_book_class(self):
        self.authenticate_as(self.staff)

        response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-011",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_member_can_list_own_bookings(self):
        self.authenticate_as(self.member)

        booking_response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-012",
        )

        self.assertEqual(
            booking_response.status_code,
            status.HTTP_201_CREATED,
        )

        response = self.client.get(
            "/api/me/bookings/",
        )

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
            booking_response.data["id"],
        )

        self.assertEqual(
            response.data[0]["member"],
            self.member.id,
        )

    def test_member_cannot_see_another_members_bookings(self):
        self.authenticate_as(self.other_member)

        other_booking_response = self.client.post(
            self.book_url(),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="booking-api-013",
        )

        self.assertEqual(
            other_booking_response.status_code,
            status.HTTP_201_CREATED,
        )

        self.authenticate_as(self.member)

        response = self.client.get(
            "/api/me/bookings/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            len(response.data),
            0,
        )

    def test_unauthenticated_user_cannot_list_bookings(self):
        response = self.client.get(
            "/api/me/bookings/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_staff_cannot_list_member_bookings(self):
        self.authenticate_as(self.staff)

        response = self.client.get(
            "/api/me/bookings/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

class CancellationAPITests(APITestCase):
    def setUp(self):
        self.password = "StrongPassword123!"

        self.member = User.objects.create_user(
            username="cancel_api_member",
            email="cancel_api_member@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        self.other_member = User.objects.create_user(
            username="cancel_api_other",
            email="cancel_api_other@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        CreditService.grant_pack(
            member=self.other_member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
)

        self.staff = User.objects.create_user(
            username="cancel_api_staff",
            email="cancel_api_staff@example.com",
            password=self.password,
            role=UserRole.STAFF,
        )

        self.studio = Studio.objects.create(
            name="Cancellation API Studio",
            timezone="Asia/Kolkata",
            cancellation_cutoff_hours=4,
        )

        self.fitness_class = FitnessClass.objects.create(
            studio=self.studio,
            start_time=timezone.now() + timedelta(days=1),
            duration_minutes=60,
            spots=2,
            credit_cost=5,
        )

        CreditService.grant_pack(
            member=self.member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def create_booking(self):
        return BookingService.book(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="cancel-api-booking",
        )

    def cancel_url(self, booking):
        return f"/api/bookings/{booking.id}/cancel/"

    def test_member_can_cancel_own_booking(self):
        booking = self.create_booking()

        self.authenticate_as(self.member)

        response = self.client.post(
            self.cancel_url(booking),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            response.data["id"],
            booking.id,
        )

        self.assertEqual(
            response.data["status"],
            BookingStatus.CANCELLED,
        )

        booking.refresh_from_db()

        self.assertEqual(
            booking.status,
            BookingStatus.CANCELLED,
        )

        self.assertIsNotNone(
            booking.cancelled_at,
        )

    def test_cancellation_before_cutoff_refunds_credits(self):
        booking = self.create_booking()

        self.assertEqual(
            CreditService.get_balance(member=self.member),
            5,
        )

        self.authenticate_as(self.member)

        response = self.client.post(
            self.cancel_url(booking),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            CreditService.get_balance(member=self.member),
            10,
        )

        refund = CreditTransaction.objects.get(
            member=self.member,
            booking=booking,
            cause=CreditTransactionCause.REFUND,
        )

        self.assertEqual(
            refund.amount,
            5,
        )

    def test_cancellation_after_cutoff_forfeits_credits(self):
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
            idempotency_key="cancel-api-late",
        )

        self.assertEqual(
            CreditService.get_balance(member=self.member),
            5,
        )

        self.authenticate_as(self.member)

        response = self.client.post(
            self.cancel_url(booking),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            CreditService.get_balance(member=self.member),
            5,
        )

        self.assertFalse(
            CreditTransaction.objects.filter(
                member=self.member,
                booking=booking,
                cause=CreditTransactionCause.REFUND,
            ).exists()
        )

    def test_member_cannot_cancel_another_members_booking(self):
        other_booking = BookingService.book(
            member=self.other_member,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="cancel-api-other",
        )

        self.authenticate_as(self.member)

        response = self.client.post(
            self.cancel_url(other_booking),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        other_booking.refresh_from_db()

        self.assertEqual(
            other_booking.status,
            BookingStatus.CONFIRMED,
        )

    def test_member_cannot_cancel_booking_twice(self):
        booking = self.create_booking()

        self.authenticate_as(self.member)

        first_response = self.client.post(
            self.cancel_url(booking),
            {},
            format="json",
        )

        second_response = self.client.post(
            self.cancel_url(booking),
            {},
            format="json",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        refund_count = CreditTransaction.objects.filter(
            member=self.member,
            booking=booking,
            cause=CreditTransactionCause.REFUND,
        ).count()

        self.assertEqual(
            refund_count,
            1,
        )

    def test_unauthenticated_user_cannot_cancel_booking(self):
        booking = self.create_booking()

        response = self.client.post(
            self.cancel_url(booking),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        booking.refresh_from_db()

        self.assertEqual(
            booking.status,
            BookingStatus.CONFIRMED,
        )

    def test_staff_cannot_cancel_booking(self):
        booking = self.create_booking()

        self.authenticate_as(self.staff)

        response = self.client.post(
            self.cancel_url(booking),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        booking.refresh_from_db()

        self.assertEqual(
            booking.status,
            BookingStatus.CONFIRMED,
        )

    def test_cancel_nonexistent_booking_returns_not_found(self):
        self.authenticate_as(self.member)

        response = self.client.post(
            "/api/bookings/999999/cancel/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_cancellation_promotes_waitlisted_member(self):
        from apps.waitlist.models import WaitlistEntry
        from apps.waitlist.services import WaitlistService

        full_class = FitnessClass.objects.create(
            studio=self.studio,
            start_time=timezone.now() + timedelta(days=1),
            duration_minutes=60,
            spots=1,
            credit_cost=5,
        )

        booking = BookingService.book(
            member=self.member,
            fitness_class_id=full_class.id,
            idempotency_key="cancel-api-waitlist-booking",
        )

        waitlist_member = User.objects.create_user(
            username="cancel_api_waitlist",
            email="cancel_api_waitlist@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        CreditService.grant_pack(
            member=waitlist_member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

        WaitlistService.join(
            member=waitlist_member,
            fitness_class_id=full_class.id,
        )

        self.authenticate_as(self.member)

        response = self.client.post(
            self.cancel_url(booking),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        promoted_booking = Booking.objects.get(
            member=waitlist_member,
            fitness_class=full_class,
            status=BookingStatus.CONFIRMED,
        )

        self.assertEqual(
            promoted_booking.credits_charged,
            5,
        )

        self.assertFalse(
            WaitlistEntry.objects.filter(
                member=waitlist_member,
                fitness_class=full_class,
            ).exists()
        )