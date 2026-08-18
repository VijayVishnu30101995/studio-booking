from rest_framework import generics, status
from rest_framework.response import Response

from apps.accounts.permissions import IsMember
from apps.bookings.models import Booking
from apps.bookings.serializers import BookingSerializer
from apps.bookings.services import (
    BookingAlreadyCancelledError,
    BookingService,
    CancellationService,
    ClassFullError,
    DuplicateBookingError,
)
from apps.classes.models import FitnessClass
from apps.credits.services import InsufficientCreditsError


class BookingCreateView(generics.GenericAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsMember]

    def post(self, request, pk):
        idempotency_key = request.headers.get("Idempotency-Key")

        if not idempotency_key:
            return Response(
                {"detail": "Idempotency-Key header is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            fitness_class = FitnessClass.objects.get(pk=pk)
        except FitnessClass.DoesNotExist:
            return Response(
                {"detail": "Class not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        existing_booking = Booking.objects.filter(
            idempotency_key=idempotency_key,
        ).first()

        try:
            booking = BookingService.book(
                member=request.user,
                fitness_class_id=fitness_class.id,
                idempotency_key=idempotency_key,
            )
        except (ClassFullError, DuplicateBookingError, InsufficientCreditsError) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(booking)

        if existing_booking:
            return Response(
                serializer.data,
                status=status.HTTP_200_OK,
            )

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class MyBookingListView(generics.ListAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsMember]

    def get_queryset(self):
        return (
            Booking.objects
            .filter(member=self.request.user)
            .select_related("fitness_class")
            .order_by("-created_at")
        )

class CancellationView(generics.GenericAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsMember]

    def post(self, request, pk):
        try:
            booking = (
                Booking.objects
                .select_related("fitness_class")
                .get(pk=pk)
            )
        except Booking.DoesNotExist:
            return Response(
                {"detail": "Booking not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if booking.member_id != request.user.id:
            return Response(
                {"detail": "You can only cancel your own bookings."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            cancelled_booking = CancellationService.cancel(
                booking_id=booking.id,
            )
        except BookingAlreadyCancelledError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(cancelled_booking)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )