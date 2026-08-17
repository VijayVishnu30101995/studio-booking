from django.db import transaction

from apps.bookings.models import Booking, BookingStatus
from apps.classes.models import FitnessClass
from apps.credits.services import CreditService


class BookingService:
    @staticmethod
    @transaction.atomic
    def book(*, member, fitness_class_id: int, idempotency_key: str) -> Booking:
        if not idempotency_key:
            raise ValueError("Idempotency key is required.")

        fitness_class = (
            FitnessClass.objects
            .select_for_update()
            .get(pk=fitness_class_id)
        )

        existing_booking = Booking.objects.filter(
            idempotency_key=idempotency_key,
        ).first()

        if existing_booking:
            return existing_booking

        has_confirmed_booking = Booking.objects.filter(
            member=member,
            fitness_class=fitness_class,
            status=BookingStatus.CONFIRMED,
        ).exists()

        if has_confirmed_booking:
            raise ValueError(
                "Member already has a confirmed booking for this class."
            )

        confirmed_count = Booking.objects.filter(
            fitness_class=fitness_class,
            status=BookingStatus.CONFIRMED,
        ).count()

        if confirmed_count >= fitness_class.spots:
            raise ValueError("Class is full.")

        booking = Booking.objects.create(
            member=member,
            fitness_class=fitness_class,
            credits_charged=fitness_class.credit_cost,
            status=BookingStatus.CONFIRMED,
            idempotency_key=idempotency_key,
        )

        CreditService.consume_credits(
            member=member,
            amount=fitness_class.credit_cost,
            booking=booking,
        )

        return booking