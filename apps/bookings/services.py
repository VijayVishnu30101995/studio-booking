import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus
from apps.classes.models import FitnessClass
from apps.credits.services import CreditService

logger = logging.getLogger(__name__)


class ClassFullError(Exception):
    """Raised when a fitness class has no available spots."""


class DuplicateBookingError(Exception):
    """Raised when a member already has a confirmed booking."""


class BookingAlreadyCancelledError(Exception):
    """Raised when an already cancelled booking is cancelled again."""

class BookingService:
    @staticmethod
    @transaction.atomic
    def book(*,member,fitness_class_id: int,idempotency_key: str,) -> Booking:
        logger.info(
            "Booking request started: member_id=%s, class_id=%s",
            member.id,
            fitness_class_id,
        )

        if not idempotency_key:
            logger.warning(
                "Booking rejected: missing idempotency key, member_id=%s",
                member.id,
            )
            raise ValueError("Idempotency key is required.")

        fitness_class = (
            FitnessClass.objects
            .select_for_update()
            .get(pk=fitness_class_id)
        )

        logger.info(
            "Fitness class locked: class_id=%s",
            fitness_class.id,
        )

        existing_booking = Booking.objects.filter(
            idempotency_key=idempotency_key,
        ).first()

        if existing_booking:
            logger.info(
                "Returning existing booking: booking_id=%s, idempotency_key=%s",
                existing_booking.id,
                idempotency_key,
            )
            return existing_booking

        existing_confirmed_booking = Booking.objects.filter(
            member=member,
            fitness_class=fitness_class,
            status=BookingStatus.CONFIRMED,
        ).exists()

        if existing_confirmed_booking:
            logger.warning(
                "Duplicate booking rejected: member_id=%s, class_id=%s",
                member.id,
                fitness_class.id,
            )
            raise DuplicateBookingError(
                "Member already has a confirmed booking for this class."
            )

        confirmed_bookings = Booking.objects.filter(
            fitness_class=fitness_class,
            status=BookingStatus.CONFIRMED,
        ).count()

        if confirmed_bookings >= fitness_class.spots:
            logger.warning(
                "Booking rejected: class is full, class_id=%s",
                fitness_class.id,
            )
            raise ClassFullError("Class is full.")

        booking = Booking.objects.create(
            member=member,
            fitness_class=fitness_class,
            credits_charged=fitness_class.credit_cost,
            status=BookingStatus.CONFIRMED,
            idempotency_key=idempotency_key,
        )

        logger.info(
            "Booking created: booking_id=%s, member_id=%s, class_id=%s",
            booking.id,
            member.id,
            fitness_class.id,
        )

        CreditService.consume_credits(
            member=member,
            amount=fitness_class.credit_cost,
            booking=booking,
        )

        logger.info(
            "Credits consumed: booking_id=%s, credits=%s",
            booking.id,
            fitness_class.credit_cost,
        )

        logger.info(
            "Booking completed successfully: booking_id=%s",
            booking.id,
        )

        return booking


class CancellationService:
    @staticmethod
    @transaction.atomic
    def cancel(*, booking_id: int) -> Booking:
        logger.info(
            "Cancellation request started: booking_id=%s",
            booking_id,
        )

        booking = (
            Booking.objects
            .select_for_update()
            .select_related("fitness_class__studio")
            .get(pk=booking_id)
        )

        logger.info(
            "Booking locked for cancellation: booking_id=%s",
            booking.id,
        )

        if booking.status == BookingStatus.CANCELLED:
            logger.warning(
                "Cancellation rejected: booking already cancelled, "
                "booking_id=%s",
                booking.id,
            )
            raise BookingAlreadyCancelledError(
                "Booking has already been cancelled."
            )

        fitness_class = booking.fitness_class
        studio = fitness_class.studio

        studio_timezone = ZoneInfo(studio.timezone)

        class_start_local = fitness_class.start_time.astimezone(
            studio_timezone
        )

        cutoff = class_start_local - timedelta(
            hours=studio.cancellation_cutoff_hours
        )

        now = timezone.now()
        now_local = now.astimezone(studio_timezone)

        logger.info(
            "Cancellation cutoff calculated: "
            "booking_id=%s, class_start=%s, cutoff=%s, now=%s, timezone=%s",
            booking.id,
            class_start_local,
            cutoff,
            now_local,
            studio.timezone,
        )

        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = now
        booking.save(
            update_fields=["status", "cancelled_at"],
        )

        if now_local <= cutoff:
            CreditService.refund_credits(
                member=booking.member,
                booking=booking,
            )

            logger.info(
                "Booking cancelled and credits refunded: "
                "booking_id=%s, member_id=%s, credits=%s",
                booking.id,
                booking.member.id,
                booking.credits_charged,
            )
        else:
            logger.info(
                "Booking cancelled after cutoff: "
                "credits forfeited, booking_id=%s, member_id=%s, credits=%s",
                booking.id,
                booking.member.id,
                booking.credits_charged,
            )

        logger.info(
            "Cancellation completed successfully: booking_id=%s",
            booking.id,
        )

        return booking