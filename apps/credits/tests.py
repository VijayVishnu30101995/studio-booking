from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.classes.models import FitnessClass
from apps.studios.models import Studio
from apps.credits.models import (
    CreditTransaction,
    CreditTransactionCause,

)
from apps.credits.services import (
    CreditService, 
    InsufficientCreditsError,
    )
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.credits.models import CreditPack

class CreditServiceTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(
            username="member1",
            email="member@example.com",
            password="testpass123",
        )

    def test_grant_pack_creates_pack_and_transaction(self):
        grant_date = timezone.now()
        expiry_date = grant_date + timedelta(days=30)

        pack = CreditService.grant_pack(
            member=self.member,
            credits=10,
            grant_date=grant_date,
            expiry_date=expiry_date,
        )

        self.assertEqual(pack.member, self.member)
        self.assertEqual(pack.credits_granted, 10)
        self.assertEqual(pack.grant_date, grant_date)
        self.assertEqual(pack.expiry_date, expiry_date)

        transaction = CreditTransaction.objects.get(
            credit_pack=pack,
        )

        self.assertEqual(transaction.member, self.member)
        self.assertEqual(transaction.amount, 10)
        self.assertEqual(
            transaction.cause,
            CreditTransactionCause.GRANT,
        )

    def test_get_balance(self):
        grant_date = timezone.now()
        expiry_date = grant_date + timedelta(days=30)

        CreditService.grant_pack(
            member=self.member,
            credits=10,
            grant_date=grant_date,
            expiry_date=expiry_date,
        )

        CreditService.grant_pack(
            member=self.member,
            credits=20,
            grant_date=grant_date,
            expiry_date=expiry_date,
        )

        balance = CreditService.get_balance(
            member=self.member,
        )

        self.assertEqual(balance, 30)

    def test_get_balance_at(self):
        first_grant = timezone.now()
        first_expiry = first_grant + timedelta(days=30)

        CreditService.grant_pack(
            member=self.member,
            credits=10,
            grant_date=first_grant,
            expiry_date=first_expiry,
        )

        balance_date = timezone.now()

        second_grant = balance_date + timedelta(seconds=1)
        second_expiry = second_grant + timedelta(days=30)

        CreditService.grant_pack(
            member=self.member,
            credits=20,
            grant_date=second_grant,
            expiry_date=second_expiry,
        )

        balance = CreditService.get_balance_at(
            member=self.member,
            at=balance_date,
        )

        self.assertEqual(balance, 10)

    def test_get_transactions(self):
        grant_date = timezone.now()
        expiry_date = grant_date + timedelta(days=30)

        CreditService.grant_pack(
            member=self.member,
            credits=10,
            grant_date=grant_date,
            expiry_date=expiry_date,
        )

        CreditService.grant_pack(
            member=self.member,
            credits=20,
            grant_date=grant_date,
            expiry_date=expiry_date,
        )

        transactions = CreditService.get_transactions(
            member=self.member,
        )

        self.assertEqual(transactions.count(), 2)
        self.assertEqual(transactions[0].amount, 10)
        self.assertEqual(transactions[0].cause, CreditTransactionCause.GRANT)
        self.assertEqual(transactions[1].amount, 20)
        self.assertEqual(transactions[1].cause, CreditTransactionCause.GRANT)

    def test_consume_credits(self):
        now = timezone.now()

        studio = Studio.objects.create(
            name="Test Studio",
            timezone="Asia/Kolkata",
        )

        fitness_class = FitnessClass.objects.create(
            studio=studio,
            start_time=now + timedelta(days=1),
            duration_minutes=60,
            spots=10,
            credit_cost=4,
        )

        booking = Booking.objects.create(
            member=self.member,
            fitness_class=fitness_class,
            credits_charged=4,
            idempotency_key="test-booking-1",
        )

        CreditService.grant_pack(
            member=self.member,
            credits=10,
            grant_date=now,
            expiry_date=now + timedelta(days=30),
        )

        transactions = CreditService.consume_credits(
            member=self.member,
            amount=4,
            booking=booking,
        )

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].amount, -4)
        self.assertEqual(
            transactions[0].cause,
            CreditTransactionCause.BOOKING,
        )

        balance = CreditService.get_balance(
            member=self.member,
        )

        self.assertEqual(balance, 6)

    def test_consume_credits_uses_earliest_expiring_pack_first(self):
        now = timezone.now()

        studio = Studio.objects.create(
            name="Test Studio",
            timezone="Asia/Kolkata",
        )

        fitness_class = FitnessClass.objects.create(
            studio=studio,
            start_time=now + timedelta(days=1),
            duration_minutes=60,
            spots=10,
            credit_cost=8,
        )

        booking = Booking.objects.create(
            member=self.member,
            fitness_class=fitness_class,
            credits_charged=8,
            idempotency_key="test-booking-2",
        )

        first_pack = CreditService.grant_pack(
            member=self.member,
            credits=5,
            grant_date=now,
            expiry_date=now + timedelta(days=5),
        )

        second_pack = CreditService.grant_pack(
            member=self.member,
            credits=10,
            grant_date=now,
            expiry_date=now + timedelta(days=10),
        )

        transactions = CreditService.consume_credits(
            member=self.member,
            amount=8,
            booking=booking,
        )

        self.assertEqual(len(transactions), 2)

        self.assertEqual(transactions[0].credit_pack, first_pack)
        self.assertEqual(transactions[0].amount, -5)

        self.assertEqual(transactions[1].credit_pack, second_pack)
        self.assertEqual(transactions[1].amount, -3)


    def test_consume_credits_ignores_expired_packs(self):
        now = timezone.now()

        studio = Studio.objects.create(
            name="Test Studio",
            timezone="Asia/Kolkata",
        )

        fitness_class = FitnessClass.objects.create(
            studio=studio,
            start_time=now + timedelta(days=1),
            duration_minutes=60,
            spots=10,
            credit_cost=5,
        )

        booking = Booking.objects.create(
            member=self.member,
            fitness_class=fitness_class,
            credits_charged=5,
            idempotency_key="test-booking-3",
        )

        expired_pack = CreditService.grant_pack(
            member=self.member,
            credits=10,
            grant_date=now - timedelta(days=20),
            expiry_date=now - timedelta(days=1),
        )

        valid_pack = CreditService.grant_pack(
            member=self.member,
            credits=5,
            grant_date=now,
            expiry_date=now + timedelta(days=10),
        )

        transactions = CreditService.consume_credits(
            member=self.member,
            amount=5,
            booking=booking,
        )

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].credit_pack, valid_pack)
        self.assertEqual(transactions[0].amount, -5)

        expired_transactions = CreditTransaction.objects.filter(
            credit_pack=expired_pack,
            cause=CreditTransactionCause.BOOKING,
        )

        self.assertFalse(expired_transactions.exists())

    def test_consume_credits_raises_error_when_balance_is_insufficient(self):
        now = timezone.now()

        studio = Studio.objects.create(
            name="Test Studio",
            timezone="Asia/Kolkata",
        )

        fitness_class = FitnessClass.objects.create(
            studio=studio,
            start_time=now + timedelta(days=1),
            duration_minutes=60,
            spots=10,
            credit_cost=10,
        )

        booking = Booking.objects.create(
            member=self.member,
            fitness_class=fitness_class,
            credits_charged=10,
            idempotency_key="test-booking-4",
        )

        CreditService.grant_pack(
            member=self.member,
            credits=5,
            grant_date=now,
            expiry_date=now + timedelta(days=10),
        )

        CreditService.grant_pack(
            member=self.member,
            credits=2,
            grant_date=now,
            expiry_date=now + timedelta(days=20),
        )

        with self.assertRaises(InsufficientCreditsError):
            CreditService.consume_credits(
                member=self.member,
                amount=10,
                booking=booking,
            )

        balance = CreditService.get_balance(
            member=self.member,
        )

        self.assertEqual(balance, 7)

        booking_transactions = CreditTransaction.objects.filter(
            member=self.member,
            booking=booking,
            cause=CreditTransactionCause.BOOKING,
        )

        self.assertEqual(booking_transactions.count(), 0)

    def test_refund_credits_returns_credits_to_original_packs(self):
        now = timezone.now()

        studio = Studio.objects.create(
            name="Test Studio",
            timezone="Asia/Kolkata",
        )

        fitness_class = FitnessClass.objects.create(
            studio=studio,
            start_time=now + timedelta(days=1),
            duration_minutes=60,
            spots=10,
            credit_cost=8,
        )

        booking = Booking.objects.create(
            member=self.member,
            fitness_class=fitness_class,
            credits_charged=8,
            idempotency_key="test-booking-5",
        )

        first_pack = CreditService.grant_pack(
            member=self.member,
            credits=5,
            grant_date=now,
            expiry_date=now + timedelta(days=5),
        )

        second_pack = CreditService.grant_pack(
            member=self.member,
            credits=10,
            grant_date=now,
            expiry_date=now + timedelta(days=10),
        )

        CreditService.consume_credits(
            member=self.member,
            amount=8,
            booking=booking,
        )

        refunds = CreditService.refund_credits(
            member=self.member,
            booking=booking,
        )

        self.assertEqual(len(refunds), 2)

        self.assertEqual(refunds[0].credit_pack, first_pack)
        self.assertEqual(refunds[0].amount, 5)
        self.assertEqual(
            refunds[0].cause,
            CreditTransactionCause.REFUND,
        )

        self.assertEqual(refunds[1].credit_pack, second_pack)
        self.assertEqual(refunds[1].amount, 3)
        self.assertEqual(
            refunds[1].cause,
            CreditTransactionCause.REFUND,
        )

        balance = CreditService.get_balance(
            member=self.member,
        )

        self.assertEqual(balance, 15)

    def test_refund_credits_cannot_be_called_twice(self):
        now = timezone.now()

        studio = Studio.objects.create(
            name="Test Studio",
            timezone="Asia/Kolkata",
        )

        fitness_class = FitnessClass.objects.create(
            studio=studio,
            start_time=now + timedelta(days=1),
            duration_minutes=60,
            spots=10,
            credit_cost=5,
        )

        booking = Booking.objects.create(
            member=self.member,
            fitness_class=fitness_class,
            credits_charged=5,
            idempotency_key="test-booking-6",
        )

        CreditService.grant_pack(
            member=self.member,
            credits=10,
            grant_date=now,
            expiry_date=now + timedelta(days=10),
        )

        CreditService.consume_credits(
            member=self.member,
            amount=5,
            booking=booking,
        )

        CreditService.refund_credits(
            member=self.member,
            booking=booking,
        )

        with self.assertRaises(ValueError):
            CreditService.refund_credits(
                member=self.member,
                booking=booking,
            )

        refunds = CreditTransaction.objects.filter(
            member=self.member,
            booking=booking,
            cause=CreditTransactionCause.REFUND,
        )

        self.assertEqual(refunds.count(), 1)
        self.assertEqual(refunds[0].amount, 5)


class CreditPackAPITests(APITestCase):
    def setUp(self):
        self.password = "StrongPassword123!"

        self.staff = User.objects.create_user(
            username="credit_staff",
            email="credit_staff@example.com",
            password=self.password,
            role=UserRole.STAFF,
        )

        self.member = User.objects.create_user(
            username="credit_member",
            email="credit_member@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        self.create_url = "/api/credit-packs/"

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def test_staff_can_grant_credit_pack(self):
        self.authenticate_as(self.staff)

        grant_date = timezone.now()
        expiry_date = grant_date + timedelta(days=30)

        response = self.client.post(
            self.create_url,
            {
                "member": self.member.id,
                "credits": 10,
                "grant_date": grant_date.isoformat(),
                "expiry_date": expiry_date.isoformat(),
            },
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
            response.data["credits_granted"],
            10,
        )

        self.assertTrue(
            CreditPack.objects.filter(
                member=self.member,
                credits_granted=10,
            ).exists()
        )

    def test_member_cannot_grant_credit_pack(self):
        self.authenticate_as(self.member)

        grant_date = timezone.now()
        expiry_date = grant_date + timedelta(days=30)

        response = self.client.post(
            self.create_url,
            {
                "member": self.member.id,
                "credits": 10,
                "grant_date": grant_date.isoformat(),
                "expiry_date": expiry_date.isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertFalse(
            CreditPack.objects.filter(
                member=self.member,
            ).exists()
        )

    def test_unauthenticated_user_cannot_grant_credit_pack(self):
        grant_date = timezone.now()
        expiry_date = grant_date + timedelta(days=30)

        response = self.client.post(
            self.create_url,
            {
                "member": self.member.id,
                "credits": 10,
                "grant_date": grant_date.isoformat(),
                "expiry_date": expiry_date.isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_grant_creates_credit_transaction(self):
        self.authenticate_as(self.staff)

        grant_date = timezone.now()
        expiry_date = grant_date + timedelta(days=30)

        response = self.client.post(
            self.create_url,
            {
                "member": self.member.id,
                "credits": 10,
                "grant_date": grant_date.isoformat(),
                "expiry_date": expiry_date.isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        pack = CreditPack.objects.get(
            id=response.data["id"]
        )

        transaction = pack.transactions.get()

        self.assertEqual(
            transaction.amount,
            10,
        )
        self.assertEqual(
            transaction.cause,
            CreditTransactionCause.GRANT,
        )

    def test_zero_credits_are_rejected(self):
        self.authenticate_as(self.staff)

        grant_date = timezone.now()
        expiry_date = grant_date + timedelta(days=30)

        response = self.client.post(
            self.create_url,
            {
                "member": self.member.id,
                "credits": 0,
                "grant_date": grant_date.isoformat(),
                "expiry_date": expiry_date.isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_negative_credits_are_rejected(self):
        self.authenticate_as(self.staff)

        grant_date = timezone.now()
        expiry_date = grant_date + timedelta(days=30)

        response = self.client.post(
            self.create_url,
            {
                "member": self.member.id,
                "credits": -5,
                "grant_date": grant_date.isoformat(),
                "expiry_date": expiry_date.isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_expiry_date_before_grant_date_is_rejected(self):
        self.authenticate_as(self.staff)

        grant_date = timezone.now()
        expiry_date = grant_date - timedelta(days=1)

        response = self.client.post(
            self.create_url,
            {
                "member": self.member.id,
                "credits": 10,
                "grant_date": grant_date.isoformat(),
                "expiry_date": expiry_date.isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_expiry_date_equal_to_grant_date_is_rejected(self):
        self.authenticate_as(self.staff)

        grant_date = timezone.now()

        response = self.client.post(
            self.create_url,
            {
                "member": self.member.id,
                "credits": 10,
                "grant_date": grant_date.isoformat(),
                "expiry_date": grant_date.isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_nonexistent_member_is_rejected(self):
        self.authenticate_as(self.staff)

        grant_date = timezone.now()
        expiry_date = grant_date + timedelta(days=30)

        response = self.client.post(
            self.create_url,
            {
                "member": 999999,
                "credits": 10,
                "grant_date": grant_date.isoformat(),
                "expiry_date": expiry_date.isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )