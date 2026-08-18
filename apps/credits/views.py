from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response

from apps.accounts.permissions import IsMember, IsStaff
from apps.credits.models import CreditPack
from apps.credits.serializers import (
    CreditBalanceAtQuerySerializer,
    CreditBalanceAtSerializer,
    CreditBalanceSerializer,
    CreditBalancePackSerializer,
    CreditPackSerializer,
    CreditTransactionSerializer,
)
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


class CreditBalanceView(generics.GenericAPIView):
    permission_classes = [IsMember]

    def get(self, request):
        member = request.user

        balance = CreditService.get_balance(
            member=member,
        )

        packs = CreditPack.objects.filter(
            member=member,
            expiry_date__gt=timezone.now(),
        ).order_by(
            "expiry_date",
            "id",
        )

        serializer = CreditBalanceSerializer(
            {
                "balance": balance,
                "packs": packs,
            }
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class CreditTransactionListView(generics.GenericAPIView):
    permission_classes = [IsMember]

    def get(self, request):
        transactions = CreditService.get_transactions(
            member=request.user,
        )

        serializer = CreditTransactionSerializer(
            transactions,
            many=True,
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class CreditBalanceAtView(generics.GenericAPIView):
    permission_classes = [IsMember]

    def get(self, request):
        query_serializer = CreditBalanceAtQuerySerializer(
            data=request.query_params,
        )

        query_serializer.is_valid(raise_exception=True)

        at = query_serializer.validated_data["at"]

        balance = CreditService.get_balance_at(
            member=request.user,
            at=at,
        )

        serializer = CreditBalanceAtSerializer(
            {
                "balance": balance,
                "at": at,
            }
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )