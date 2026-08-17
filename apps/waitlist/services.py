import logging

from django.db import transaction

from apps.bookings.models import Booking, BookingStatus
from apps.classes.models import FitnessClass
from apps.credits.services import CreditService, InsufficientCreditsError
from apps.waitlist.models import WaitlistEntry

logger = logging.getLogger(__name__)


class ClassNotFullError(Exception):
    """Raised when a member tries to join a waitlist for a class with space."""


class AlreadyOnWaitlistError(Exception):
    """Raised when a member is already waiting for a class."""


class AlreadyBookedError(Exception):
    """Raised when a member already has a confirmed booking."""


class WaitlistService:
    @staticmethod
    @transaction.atomic
    def join(*, member, fitness_class_id: int) -> WaitlistEntry:
        logger.info(
            "Waitlist join request started: member_id=%s, class_id=%s",
            member.id,
            fitness_class_id,
        )

        fitness_class = (
            FitnessClass.objects
            .select_for_update()
            .get(pk=fitness_class_id)
        )

        logger.info(
            "Fitness class locked for waitlist join: class_id=%s",
            fitness_class.id,
        )

        confirmed_bookings = Booking.objects.filter(
            fitness_class=fitness_class,
            status=BookingStatus.CONFIRMED,
        ).count()

        logger.info(
            "Confirmed booking count checked: class_id=%s, confirmed=%s, spots=%s",
            fitness_class.id,
            confirmed_bookings,
            fitness_class.spots,
        )

        if confirmed_bookings < fitness_class.spots:
            logger.warning(
                "Waitlist join rejected: class has available spots, "
                "member_id=%s, class_id=%s",
                member.id,
                fitness_class.id,
            )
            raise ClassNotFullError(
                "Cannot join waitlist because the class has available spots."
            )

        already_booked = Booking.objects.filter(
            member=member,
            fitness_class=fitness_class,
            status=BookingStatus.CONFIRMED,
        ).exists()

        if already_booked:
            logger.warning(
                "Waitlist join rejected: member already booked, "
                "member_id=%s, class_id=%s",
                member.id,
                fitness_class.id,
            )
            raise AlreadyBookedError(
                "Member already has a confirmed booking for this class."
            )

        existing_entry = WaitlistEntry.objects.filter(
            member=member,
            fitness_class=fitness_class,
        ).first()

        if existing_entry:
            logger.warning(
                "Waitlist join rejected: member already on waitlist, "
                "member_id=%s, class_id=%s, entry_id=%s",
                member.id,
                fitness_class.id,
                existing_entry.id,
            )
            raise AlreadyOnWaitlistError(
                "Member is already on the waitlist for this class."
            )

        entry = WaitlistEntry.objects.create(
            member=member,
            fitness_class=fitness_class,
        )

        logger.info(
            "Member joined waitlist successfully: "
            "member_id=%s, class_id=%s, entry_id=%s",
            member.id,
            fitness_class.id,
            entry.id,
        )

        return entry

    @staticmethod
    @transaction.atomic
    def leave(*, member, fitness_class_id: int) -> None:
        logger.info(
            "Waitlist leave request started: member_id=%s, class_id=%s",
            member.id,
            fitness_class_id,
        )

        entry = WaitlistEntry.objects.filter(
            member=member,
            fitness_class_id=fitness_class_id,
        ).first()

        if entry is None:
            logger.info(
                "Waitlist leave: no entry found, "
                "member_id=%s, class_id=%s",
                member.id,
                fitness_class_id,
            )
            return

        entry_id = entry.id
        entry.delete()

        logger.info(
            "Member left waitlist successfully: "
            "member_id=%s, class_id=%s, entry_id=%s",
            member.id,
            fitness_class_id,
            entry_id,
        )

    @staticmethod
    def get_member_entries(*, member):
        logger.info(
            "Fetching member waitlist entries: member_id=%s",
            member.id,
        )

        return (
            WaitlistEntry.objects
            .filter(member=member)
            .select_related(
                "fitness_class",
                "fitness_class__studio",
            )
            .order_by("created_at", "id")
        )

    @staticmethod
    @transaction.atomic
    def promote_next(*, fitness_class_id: int) -> Booking | None:
        logger.info(
            "Waitlist promotion started: class_id=%s",
            fitness_class_id,
        )

        fitness_class = (
            FitnessClass.objects
            .select_for_update()
            .get(pk=fitness_class_id)
        )

        logger.info(
            "Fitness class locked for waitlist promotion: class_id=%s",
            fitness_class.id,
        )

        confirmed_bookings = Booking.objects.filter(
            fitness_class=fitness_class,
            status=BookingStatus.CONFIRMED,
        ).count()

        logger.info(
            "Promotion capacity check: "
            "class_id=%s, confirmed=%s, spots=%s",
            fitness_class.id,
            confirmed_bookings,
            fitness_class.spots,
        )

        if confirmed_bookings >= fitness_class.spots:
            logger.info(
                "Waitlist promotion skipped: class is full, class_id=%s",
                fitness_class.id,
            )
            return None

        waitlist_entries = (
            WaitlistEntry.objects
            .select_related("member")
            .filter(fitness_class=fitness_class)
            .order_by("created_at", "id")
        )

        logger.info(
            "Waitlist candidates loaded: class_id=%s",
            fitness_class.id,
        )

        for entry in waitlist_entries:
            logger.info(
                "Checking waitlist candidate: "
                "entry_id=%s, member_id=%s, class_id=%s",
                entry.id,
                entry.member.id,
                fitness_class.id,
            )

            try:
                with transaction.atomic():
                    booking = Booking.objects.create(
                        member=entry.member,
                        fitness_class=fitness_class,
                        credits_charged=fitness_class.credit_cost,
                        status=BookingStatus.CONFIRMED,
                        idempotency_key=f"waitlist-{entry.id}",
                    )

                    logger.info(
                        "Temporary booking created for waitlist promotion: "
                        "booking_id=%s, entry_id=%s",
                        booking.id,
                        entry.id,
                    )

                    CreditService.consume_credits(
                        member=entry.member,
                        amount=fitness_class.credit_cost,
                        booking=booking,
                    )

                    logger.info(
                        "Credits consumed for waitlist promotion: "
                        "booking_id=%s, member_id=%s, credits=%s",
                        booking.id,
                        entry.member.id,
                        fitness_class.credit_cost,
                    )

            except InsufficientCreditsError:
                logger.info(
                    "Waitlist candidate cannot afford class: "
                    "entry_id=%s, member_id=%s, required_credits=%s",
                    entry.id,
                    entry.member.id,
                    fitness_class.credit_cost,
                )
                continue

            entry_id = entry.id
            entry.delete()

            logger.info(
                "Waitlist candidate promoted successfully: "
                "entry_id=%s, member_id=%s, class_id=%s, booking_id=%s",
                entry_id,
                entry.member.id,
                fitness_class.id,
                booking.id,
            )

            return booking

        logger.info(
            "No eligible waitlist member found: class_id=%s",
            fitness_class.id,
        )

        return None