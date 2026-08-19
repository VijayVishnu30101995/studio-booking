from rest_framework import generics, status
from rest_framework.response import Response

from apps.accounts.permissions import IsMember
from apps.waitlist.serializers import WaitlistEntrySerializer
from apps.waitlist.services import (
    AlreadyBookedError,
    AlreadyOnWaitlistError,
    ClassNotFullError,
    WaitlistService,
)


class WaitlistView(generics.GenericAPIView):
    serializer_class = WaitlistEntrySerializer
    permission_classes = [IsMember]

    def post(self, request, pk):
        try:
            entry = WaitlistService.join(
                member=request.user,
                fitness_class_id=pk,
            )
        except (
            ClassNotFullError,
            AlreadyBookedError,
            AlreadyOnWaitlistError,
        ) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(entry)

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request, pk):
        WaitlistService.leave(
            member=request.user,
            fitness_class_id=pk,
        )

        return Response(
            status=status.HTTP_204_NO_CONTENT,
        )


class MyWaitlistListView(generics.ListAPIView):
    serializer_class = WaitlistEntrySerializer
    permission_classes = [IsMember]

    def get_queryset(self):
        return WaitlistService.get_member_entries(
            member=self.request.user,
        )