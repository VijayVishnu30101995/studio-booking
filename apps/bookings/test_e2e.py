from datetime import timedelta

from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import BookingService, CancellationService
from apps.classes.models import FitnessClass
from apps.credits.models import CreditTransaction, CreditTransactionCause
from apps.credits.services import CreditService
from apps.studios.models import Studio
from apps.waitlist.models import WaitlistEntry
from apps.waitlist.services import WaitlistService


class BookingCancellationWaitlistE2ETests(TransactionTestCase):
    def setUp(self) -> None:
        self.studio = Studio.objects.create(
            name="E2E Studio",
            timezone="Asia/Kolkata",
            cancellation_cutoff_hours=4,
        )

        self.fitness_class = FitnessClass.objects.create(
            studio=self.studio,
            start_time=timezone.now() + timedelta(days=1),
            duration_minutes=60,
            spots=1,
            credit_cost=5,
        )

        self.member_a = User.objects.create_user(
            username="e2e_member_a",
            email="e2e_member_a@example.com",
            password="password123",
            role=UserRole.MEMBER,
        )

        self.member_b = User.objects.create_user(
            username="e2e_member_b",
            email="e2e_member_b@example.com",
            password="password123",
            role=UserRole.MEMBER,
        )

        # Member A can book the class.
        CreditService.grant_pack(
            member=self.member_a,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

        # Member B can afford the class when promoted.
        CreditService.grant_pack(
            member=self.member_b,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

    def test_booking_cancellation_promotes_waitlisted_member(self) -> None:
        # ---------------------------------------------------------
        # 1. Member A books the only available spot.
        # ---------------------------------------------------------
        original_booking = BookingService.book(
            member=self.member_a,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="e2e-member-a-booking",
        )

        self.assertEqual(
            original_booking.status,
            BookingStatus.CONFIRMED,
        )

        self.assertEqual(
            CreditService.get_balance(member=self.member_a),
            5,
        )

        # ---------------------------------------------------------
        # 2. Member B joins the waitlist because the class is full.
        # ---------------------------------------------------------
        waitlist_entry = WaitlistService.join(
            member=self.member_b,
            fitness_class_id=self.fitness_class.id,
        )

        self.assertEqual(
            waitlist_entry.member,
            self.member_b,
        )

        self.assertEqual(
            waitlist_entry.fitness_class,
            self.fitness_class,
        )

        self.assertTrue(
            WaitlistEntry.objects.filter(
                id=waitlist_entry.id,
            ).exists()
        )

        # Member B has not been charged yet.
        self.assertEqual(
            CreditService.get_balance(member=self.member_b),
            10,
        )

        # ---------------------------------------------------------
        # 3. Member A cancels before the cutoff.
        # ---------------------------------------------------------
        cancelled_booking = CancellationService.cancel(
            booking_id=original_booking.id,
        )

        self.assertEqual(
            cancelled_booking.status,
            BookingStatus.CANCELLED,
        )

        self.assertIsNotNone(
            cancelled_booking.cancelled_at,
        )

        # Member A receives the 5 credits back.
        self.assertEqual(
            CreditService.get_balance(member=self.member_a),
            10,
        )

        # A refund transaction should exist.
        refund_transaction = CreditTransaction.objects.get(
            member=self.member_a,
            booking=original_booking,
            cause=CreditTransactionCause.REFUND,
        )

        self.assertEqual(
            refund_transaction.amount,
            5,
        )

        # ---------------------------------------------------------
        # 4. Member B should automatically be promoted.
        # ---------------------------------------------------------
        promoted_booking = Booking.objects.get(
            member=self.member_b,
            fitness_class=self.fitness_class,
            status=BookingStatus.CONFIRMED,
        )

        self.assertEqual(
            promoted_booking.credits_charged,
            5,
        )

        # ---------------------------------------------------------
        # 5. Member B's credits should be deducted.
        # ---------------------------------------------------------
        self.assertEqual(
            CreditService.get_balance(member=self.member_b),
            5,
        )

        booking_transaction = CreditTransaction.objects.get(
            member=self.member_b,
            booking=promoted_booking,
            cause=CreditTransactionCause.BOOKING,
        )

        self.assertEqual(
            booking_transaction.amount,
            -5,
        )

        # ---------------------------------------------------------
        # 6. Member B should no longer be on the waitlist.
        # ---------------------------------------------------------
        self.assertFalse(
            WaitlistEntry.objects.filter(
                member=self.member_b,
                fitness_class=self.fitness_class,
            ).exists()
        )

        # ---------------------------------------------------------
        # 7. The class should have exactly one confirmed booking.
        # ---------------------------------------------------------
        confirmed_booking_count = Booking.objects.filter(
            fitness_class=self.fitness_class,
            status=BookingStatus.CONFIRMED,
        ).count()

        self.assertEqual(
            confirmed_booking_count,
            1,
        )

        # The confirmed booking should belong to Member B.
        self.assertEqual(
            Booking.objects.get(
                fitness_class=self.fitness_class,
                status=BookingStatus.CONFIRMED,
            ).member,
            self.member_b,
        )
    def test_cancellation_skips_unaffordable_waitlisted_member(
        self,
    ) -> None:
        # ---------------------------------------------------------
        # 1. Create two additional waitlisted members.
        # ---------------------------------------------------------
        member_c = User.objects.create_user(
            username="e2e_member_c",
            email="e2e_member_c@example.com",
            password="password123",
            role=UserRole.MEMBER,
        )

        member_d = User.objects.create_user(
            username="e2e_member_d",
            email="e2e_member_d@example.com",
            password="password123",
            role=UserRole.MEMBER,
        )

        # Member C intentionally has 0 credits.
        self.assertEqual(
            CreditService.get_balance(member=member_c),
            0,
        )

        # Member D can afford the 5-credit class.
        CreditService.grant_pack(
            member=member_d,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

        # ---------------------------------------------------------
        # 2. Member A books the only available spot.
        # ---------------------------------------------------------
        original_booking = BookingService.book(
            member=self.member_a,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="e2e-unaffordable-member-a",
        )

        self.assertEqual(
            original_booking.status,
            BookingStatus.CONFIRMED,
        )

        self.assertEqual(
            CreditService.get_balance(member=self.member_a),
            5,
        )

        # ---------------------------------------------------------
        # 3. Member C joins the waitlist first.
        #    C is at the front but has no credits.
        # ---------------------------------------------------------
        first_waitlist_entry = WaitlistService.join(
            member=member_c,
            fitness_class_id=self.fitness_class.id,
        )

        self.assertEqual(
            first_waitlist_entry.member,
            member_c,
        )

        # ---------------------------------------------------------
        # 4. Member D joins the waitlist second.
        #    D has enough credits to be promoted.
        # ---------------------------------------------------------
        second_waitlist_entry = WaitlistService.join(
            member=member_d,
            fitness_class_id=self.fitness_class.id,
        )

        self.assertEqual(
            second_waitlist_entry.member,
            member_d,
        )

        # Verify both members are waiting.
        self.assertTrue(
            WaitlistEntry.objects.filter(
                member=member_c,
                fitness_class=self.fitness_class,
            ).exists()
        )

        self.assertTrue(
            WaitlistEntry.objects.filter(
                member=member_d,
                fitness_class=self.fitness_class,
            ).exists()
        )

        # Neither member has been charged yet.
        self.assertEqual(
            CreditService.get_balance(member=member_c),
            0,
        )

        self.assertEqual(
            CreditService.get_balance(member=member_d),
            10,
        )

        # ---------------------------------------------------------
        # 5. Member A cancels before the cutoff.
        # ---------------------------------------------------------
        cancelled_booking = CancellationService.cancel(
            booking_id=original_booking.id,
        )

        self.assertEqual(
            cancelled_booking.status,
            BookingStatus.CANCELLED,
        )

        # Member A receives the refund.
        self.assertEqual(
            CreditService.get_balance(member=self.member_a),
            10,
        )

        refund_transaction = CreditTransaction.objects.get(
            member=self.member_a,
            booking=original_booking,
            cause=CreditTransactionCause.REFUND,
        )

        self.assertEqual(
            refund_transaction.amount,
            5,
        )

        # ---------------------------------------------------------
        # 6. Member C cannot afford the class.
        #    C must remain on the waitlist.
        # ---------------------------------------------------------
        self.assertTrue(
            WaitlistEntry.objects.filter(
                member=member_c,
                fitness_class=self.fitness_class,
            ).exists()
        )

        self.assertEqual(
            CreditService.get_balance(member=member_c),
            0,
        )

        self.assertFalse(
            Booking.objects.filter(
                member=member_c,
                fitness_class=self.fitness_class,
                status=BookingStatus.CONFIRMED,
            ).exists()
        )

        # ---------------------------------------------------------
        # 7. Member D should be promoted.
        # ---------------------------------------------------------
        promoted_booking = Booking.objects.get(
            member=member_d,
            fitness_class=self.fitness_class,
            status=BookingStatus.CONFIRMED,
        )

        self.assertEqual(
            promoted_booking.credits_charged,
            5,
        )

        # ---------------------------------------------------------
        # 8. Member D should be charged 5 credits.
        # ---------------------------------------------------------
        self.assertEqual(
            CreditService.get_balance(member=member_d),
            5,
        )

        booking_transaction = CreditTransaction.objects.get(
            member=member_d,
            booking=promoted_booking,
            cause=CreditTransactionCause.BOOKING,
        )

        self.assertEqual(
            booking_transaction.amount,
            -5,
        )

        # ---------------------------------------------------------
        # 9. Member D should leave the waitlist.
        # ---------------------------------------------------------
        self.assertFalse(
            WaitlistEntry.objects.filter(
                member=member_d,
                fitness_class=self.fitness_class,
            ).exists()
        )

        # Member C must remain at the front of the waitlist.
        remaining_entry = WaitlistEntry.objects.get(
            fitness_class=self.fitness_class,
        )

        self.assertEqual(
            remaining_entry.member,
            member_c,
        )

        # ---------------------------------------------------------
        # 10. The class should have exactly one confirmed booking.
        # ---------------------------------------------------------
        confirmed_booking_count = Booking.objects.filter(
            fitness_class=self.fitness_class,
            status=BookingStatus.CONFIRMED,
        ).count()

        self.assertEqual(
            confirmed_booking_count,
            1,
        )

        self.assertEqual(
            Booking.objects.get(
                fitness_class=self.fitness_class,
                status=BookingStatus.CONFIRMED,
            ).member,
            member_d,
        )