from datetime import timedelta

from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User, UserRole
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import BookingService
from apps.classes.models import FitnessClass
from apps.credits.models import CreditTransaction, CreditTransactionCause
from apps.credits.services import CreditService
from apps.studios.models import Studio
from apps.waitlist.models import WaitlistEntry
from apps.waitlist.services import (
    AlreadyBookedError,
    AlreadyOnWaitlistError,
    ClassNotFullError,
    WaitlistService,
)


class WaitlistServiceTests(TransactionTestCase):
    def setUp(self) -> None:
        self.studio = Studio.objects.create(
            name="Test Studio",
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

        self.member = User.objects.create_user(
            username="member",
            email="member@example.com",
            password="password123",
        )

        self.another_member = User.objects.create_user(
            username="another-member",
            email="another@example.com",
            password="password123",
        )

        self.third_member = User.objects.create_user(
            username="third-member",
            email="third@example.com",
            password="password123",
        )

    def grant_credits(self, member: User, credits: int = 10) -> None:
        CreditService.grant_pack(
            member=member,
            credits=credits,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

    def fill_class(self) -> Booking:
        self.grant_credits(self.member)

        return BookingService.book(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="initial-booking",
        )

    def test_member_can_join_full_class_waitlist(self) -> None:
        self.fill_class()

        entry = WaitlistService.join(
            member=self.another_member,
            fitness_class_id=self.fitness_class.id,
        )

        self.assertEqual(entry.member, self.another_member)
        self.assertEqual(entry.fitness_class, self.fitness_class)

    def test_member_cannot_join_waitlist_when_class_has_space(self) -> None:
        with self.assertRaises(ClassNotFullError):
            WaitlistService.join(
                member=self.member,
                fitness_class_id=self.fitness_class.id,
            )

    def test_member_cannot_join_waitlist_twice(self) -> None:
        self.fill_class()

        WaitlistService.join(
            member=self.another_member,
            fitness_class_id=self.fitness_class.id,
        )

        with self.assertRaises(AlreadyOnWaitlistError):
            WaitlistService.join(
                member=self.another_member,
                fitness_class_id=self.fitness_class.id,
            )

    def test_member_with_confirmed_booking_cannot_join_waitlist(self) -> None:
        self.fill_class()

        with self.assertRaises(AlreadyBookedError):
            WaitlistService.join(
                member=self.member,
                fitness_class_id=self.fitness_class.id,
            )

    def test_member_can_leave_waitlist(self) -> None:
        self.fill_class()

        WaitlistService.join(
            member=self.another_member,
            fitness_class_id=self.fitness_class.id,
        )

        WaitlistService.leave(
            member=self.another_member,
            fitness_class_id=self.fitness_class.id,
        )

        self.assertFalse(
            WaitlistEntry.objects.filter(
                member=self.another_member,
                fitness_class=self.fitness_class,
            ).exists()
        )

    def test_leave_waitlist_is_safe_when_entry_does_not_exist(self) -> None:
        WaitlistService.leave(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
        )

        self.assertFalse(
            WaitlistEntry.objects.filter(
                member=self.member,
                fitness_class=self.fitness_class,
            ).exists()
        )

    def test_member_can_list_own_waitlist_entries(self) -> None:
        self.fill_class()

        WaitlistService.join(
            member=self.another_member,
            fitness_class_id=self.fitness_class.id,
        )

        entries = list(
            WaitlistService.get_member_entries(
                member=self.another_member,
            )
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].member, self.another_member)
        self.assertEqual(
            entries[0].fitness_class,
            self.fitness_class,
        )

    def test_oldest_affordable_member_is_promoted(self) -> None:
        booking = self.fill_class()

        WaitlistService.join(
            member=self.another_member,
            fitness_class_id=self.fitness_class.id,
        )

        self.grant_credits(self.another_member)

        booking.status = BookingStatus.CANCELLED
        booking.save(update_fields=["status"])

        promoted_booking = WaitlistService.promote_next(
            fitness_class_id=self.fitness_class.id,
        )

        self.assertIsNotNone(promoted_booking)
        self.assertEqual(
            promoted_booking.member,
            self.another_member,
        )
        self.assertEqual(
            promoted_booking.status,
            BookingStatus.CONFIRMED,
        )

        self.assertFalse(
            WaitlistEntry.objects.filter(
                member=self.another_member,
                fitness_class=self.fitness_class,
            ).exists()
        )

    def test_member_without_enough_credits_stays_on_waitlist(self) -> None:
        booking = self.fill_class()

        WaitlistService.join(
            member=self.another_member,
            fitness_class_id=self.fitness_class.id,
        )

        booking.status = BookingStatus.CANCELLED
        booking.save(update_fields=["status"])

        promoted_booking = WaitlistService.promote_next(
            fitness_class_id=self.fitness_class.id,
        )

        self.assertIsNone(promoted_booking)

        self.assertTrue(
            WaitlistEntry.objects.filter(
                member=self.another_member,
                fitness_class=self.fitness_class,
            ).exists()
        )

        self.assertEqual(
            Booking.objects.filter(
                fitness_class=self.fitness_class,
                status=BookingStatus.CONFIRMED,
            ).count(),
            0,
        )

    def test_promotion_deducts_credits(self) -> None:
        booking = self.fill_class()

        WaitlistService.join(
            member=self.another_member,
            fitness_class_id=self.fitness_class.id,
        )

        self.grant_credits(self.another_member)

        booking.status = BookingStatus.CANCELLED
        booking.save(update_fields=["status"])

        WaitlistService.promote_next(
            fitness_class_id=self.fitness_class.id,
        )

        balance = CreditService.get_balance(
            member=self.another_member,
        )

        self.assertEqual(balance, 5)

        transaction = CreditTransaction.objects.get(
            member=self.another_member,
            cause=CreditTransactionCause.BOOKING,
        )

        self.assertEqual(transaction.amount, -5)

    def test_unaffordable_member_keeps_position_and_next_affordable_member_is_promoted(
        self,
    ) -> None:
        booking = self.fill_class()

        first_entry = WaitlistService.join(
            member=self.another_member,
            fitness_class_id=self.fitness_class.id,
        )

        second_entry = WaitlistService.join(
            member=self.third_member,
            fitness_class_id=self.fitness_class.id,
        )

        self.grant_credits(self.third_member)

        booking.status = BookingStatus.CANCELLED
        booking.save(update_fields=["status"])

        promoted_booking = WaitlistService.promote_next(
            fitness_class_id=self.fitness_class.id,
        )

        self.assertIsNotNone(promoted_booking)
        self.assertEqual(
            promoted_booking.member,
            self.third_member,
        )

        self.assertTrue(
            WaitlistEntry.objects.filter(
                pk=first_entry.pk,
            ).exists()
        )

        self.assertFalse(
            WaitlistEntry.objects.filter(
                pk=second_entry.pk,
            ).exists()
        )

    def test_no_promotion_when_class_is_full(self) -> None:
        self.fill_class()

        WaitlistService.join(
            member=self.another_member,
            fitness_class_id=self.fitness_class.id,
        )

        promoted_booking = WaitlistService.promote_next(
            fitness_class_id=self.fitness_class.id,
        )

        self.assertIsNone(promoted_booking)

        self.assertTrue(
            WaitlistEntry.objects.filter(
                member=self.another_member,
                fitness_class=self.fitness_class,
            ).exists()
        )

class WaitlistAPITests(APITestCase):
    def setUp(self):
        self.password = "StrongPassword123!"

        self.member = User.objects.create_user(
            username="waitlist_api_member",
            email="waitlist_api_member@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        self.other_member = User.objects.create_user(
            username="waitlist_api_other",
            email="waitlist_api_other@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        self.staff = User.objects.create_user(
            username="waitlist_api_staff",
            email="waitlist_api_staff@example.com",
            password=self.password,
            role=UserRole.STAFF,
        )

        self.studio = Studio.objects.create(
            name="Waitlist API Studio",
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

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def join_url(self):
        return f"/api/classes/{self.fitness_class.id}/waitlist/"

    def leave_url(self):
        return f"/api/classes/{self.fitness_class.id}/waitlist/"

    def list_url(self):
        return "/api/me/waitlist/"

    def create_full_class_booking(self):
        CreditService.grant_pack(
            member=self.other_member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

        return BookingService.book(
            member=self.other_member,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="waitlist-api-full-class",
        )

    def test_member_can_join_full_class_waitlist(self):
        self.create_full_class_booking()

        self.authenticate_as(self.member)

        response = self.client.post(
            self.join_url(),
            {},
            format="json",
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

        self.assertTrue(
            WaitlistEntry.objects.filter(
                member=self.member,
                fitness_class=self.fitness_class,
            ).exists()
        )

    def test_member_cannot_join_waitlist_when_class_has_space(self):
        self.authenticate_as(self.member)

        response = self.client.post(
            self.join_url(),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_member_cannot_join_waitlist_twice(self):
        self.create_full_class_booking()

        WaitlistService.join(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
        )

        self.authenticate_as(self.member)

        response = self.client.post(
            self.join_url(),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_member_with_confirmed_booking_cannot_join_waitlist(self):
        CreditService.grant_pack(
            member=self.member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

        BookingService.book(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
            idempotency_key="waitlist-api-already-booked",
        )

        self.authenticate_as(self.member)

        response = self.client.post(
            self.join_url(),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_member_can_leave_waitlist(self):
        self.create_full_class_booking()

        WaitlistService.join(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
        )

        self.authenticate_as(self.member)

        response = self.client.delete(
            self.leave_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_204_NO_CONTENT,
        )

        self.assertFalse(
            WaitlistEntry.objects.filter(
                member=self.member,
                fitness_class=self.fitness_class,
            ).exists()
        )

    def test_leave_waitlist_is_safe_when_entry_does_not_exist(self):
        self.authenticate_as(self.member)

        response = self.client.delete(
            self.leave_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_204_NO_CONTENT,
        )

    def test_member_can_list_own_waitlist_entries(self):
        self.create_full_class_booking()

        WaitlistService.join(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
        )

        self.authenticate_as(self.member)

        response = self.client.get(
            self.list_url(),
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
            response.data[0]["member"],
            self.member.id,
        )

        self.assertEqual(
            response.data[0]["fitness_class"],
            self.fitness_class.id,
        )

    def test_member_can_only_see_own_waitlist_entries(self):
        self.create_full_class_booking()

        WaitlistService.join(
            member=self.member,
            fitness_class_id=self.fitness_class.id,
        )

        another_class = FitnessClass.objects.create(
            studio=self.studio,
            start_time=timezone.now() + timedelta(days=2),
            duration_minutes=60,
            spots=1,
            credit_cost=5,
        )

        CreditService.grant_pack(
            member=self.other_member,
            credits=10,
            grant_date=timezone.now(),
            expiry_date=timezone.now() + timedelta(days=30),
        )

        BookingService.book(
            member=self.other_member,
            fitness_class_id=another_class.id,
            idempotency_key="waitlist-api-another-class",
        )

        WaitlistService.join(
            member=self.member,
            fitness_class_id=another_class.id,
        )

        self.authenticate_as(self.other_member)

        response = self.client.get(
            self.list_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            len(response.data),
            0,
        )
    def test_unauthenticated_user_cannot_join_waitlist(self):
        self.create_full_class_booking()

        response = self.client.post(
            self.join_url(),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_unauthenticated_user_cannot_list_waitlist(self):
        response = self.client.get(
            self.list_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_staff_cannot_join_waitlist(self):
        self.create_full_class_booking()

        self.authenticate_as(self.staff)

        response = self.client.post(
            self.join_url(),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_staff_cannot_list_waitlist(self):
        self.authenticate_as(self.staff)

        response = self.client.get(
            self.list_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )
