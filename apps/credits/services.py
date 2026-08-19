from datetime import datetime

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.bookings.models import Booking
from apps.credits.models import (
    CreditPack,
    CreditTransaction,
    CreditTransactionCause,
)


class InsufficientCreditsError(Exception):
    """Raised when a member does not have enough valid credits."""


class CreditService:
    @staticmethod
    @transaction.atomic
    def grant_pack(*,member,credits: int,grant_date: datetime,expiry_date: datetime) -> CreditPack:
        if credits <= 0:
            raise ValueError("Credits must be greater than zero.")

        if expiry_date <= grant_date:
            raise ValueError("Expiry date must be after grant date.")

        pack = CreditPack.objects.create(
            member=member,
            credits_granted=credits,
            grant_date=grant_date,
            expiry_date=expiry_date,
        )

        CreditTransaction.objects.create(
            member=member,
            credit_pack=pack,
            amount=credits,
            cause=CreditTransactionCause.GRANT,
        )

        return pack

    @staticmethod
    def get_balance(*, member, at: datetime | None = None) -> int:
        transactions = CreditTransaction.objects.filter(
            member=member,
        )

        if at is not None:
            transactions = transactions.filter(created_at__lte=at)

        return sum(
            transaction.amount
            for transaction in transactions.iterator()
        )

    @staticmethod
    def get_balance_at(*, member, at: datetime) -> int:
        return CreditService.get_balance(
            member=member,
            at=at,
        )

    @staticmethod
    def get_transactions(*,member,at: datetime | None = None,) -> QuerySet[CreditTransaction]:
        queryset = CreditTransaction.objects.filter(
            member=member,
        ).select_related(
            "credit_pack",
            "booking",
        )

        if at is not None:
            queryset = queryset.filter(created_at__lte=at)

        return queryset.order_by("created_at", "id")

    @staticmethod
    @transaction.atomic
    def consume_credits(*,member,amount: int,booking: Booking,) -> list[CreditTransaction]:
        if amount <= 0:
            raise ValueError("Amount must be greater than zero.")

        packs = (
            CreditPack.objects
            .select_for_update()
            .filter(
                member=member,
                expiry_date__gt=timezone.now(),
            )
            .order_by("expiry_date", "id")
        )

        remaining = amount
        transactions = []

        for pack in packs:
            used = CreditService._pack_balance(pack)

            if used <= 0:
                continue

            consumed = min(used, remaining)

            credit_transaction = CreditTransaction.objects.create(
                member=member,
                credit_pack=pack,
                booking=booking,
                amount=-consumed,
                cause=CreditTransactionCause.BOOKING,
            )

            transactions.append(credit_transaction)
            remaining -= consumed

            if remaining == 0:
                return transactions

        raise InsufficientCreditsError(
            f"Member does not have enough credits for this booking. "
            f"Required: {amount}."
        )

    @staticmethod
    @transaction.atomic
    def refund_credits(*,member,booking: Booking,) -> list[CreditTransaction]:
        booking_transactions = list(
            CreditTransaction.objects
            .select_for_update()
            .filter(
                member=member,
                booking=booking,
                cause=CreditTransactionCause.BOOKING,
                amount__lt=0,
            )
            .order_by("id")
        )

        if not booking_transactions:
            raise ValueError("No booking credit transactions found.")

        existing_refund = CreditTransaction.objects.filter(
            member=member,
            booking=booking,
            cause=CreditTransactionCause.REFUND,
        ).exists()

        if existing_refund:
            raise ValueError("Credits have already been refunded.")

        refunds = []

        for booking_transaction in booking_transactions:
            refund = CreditTransaction.objects.create(
                member=member,
                credit_pack=booking_transaction.credit_pack,
                booking=booking,
                amount=-booking_transaction.amount,
                cause=CreditTransactionCause.REFUND,
            )
            refunds.append(refund)

        return refunds

    @staticmethod
    def _pack_balance(pack: CreditPack) -> int:
        total = CreditTransaction.objects.filter(
            credit_pack=pack,
        ).values_list("amount", flat=True)

        return sum(total)


