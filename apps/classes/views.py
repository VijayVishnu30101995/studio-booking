from datetime import datetime, time

from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from apps.accounts.permissions import IsStaff
from apps.classes.models import FitnessClass
from apps.classes.serializers import FitnessClassSerializer


class ClassListCreateView(generics.ListCreateAPIView):
    queryset = FitnessClass.objects.all()
    serializer_class = FitnessClassSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsStaff()]

        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = super().get_queryset()

        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if start_date:
            try:
                start = datetime.fromisoformat(start_date)
            except ValueError:
                return queryset.none()

            start_datetime = timezone.make_aware(
                datetime.combine(start.date(), time.min)
            )

            queryset = queryset.filter(
                start_time__gte=start_datetime
            )

        if end_date:
            try:
                end = datetime.fromisoformat(end_date)
            except ValueError:
                return queryset.none()

            end_datetime = timezone.make_aware(
                datetime.combine(end.date(), time.max)
            )

            queryset = queryset.filter(
                start_time__lte=end_datetime
            )

        return queryset


class ClassDetailView(generics.RetrieveAPIView):
    queryset = FitnessClass.objects.all()
    serializer_class = FitnessClassSerializer
    permission_classes = [IsAuthenticated]
