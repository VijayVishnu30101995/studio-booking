from rest_framework import generics

from apps.accounts.permissions import IsStaff
from apps.credits.models import CreditPack
from apps.credits.serializers import CreditPackSerializer
from apps.credits.services import CreditService


class CreditPackCreateView(generics.CreateAPIView):
    queryset = CreditPack.objects.all()
    serializer_class = CreditPackSerializer
    permission_classes = [IsStaff]

    def perform_create(self, serializer):
        validated_data = serializer.validated_data

        pack = CreditService.grant_pack(
            member=validated_data["member"],
            credits=validated_data["credits"],
            grant_date=validated_data["grant_date"],
            expiry_date=validated_data["expiry_date"],
        )

        serializer.instance = pack