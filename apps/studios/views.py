from rest_framework import generics

from apps.accounts.permissions import IsStaff
from apps.studios.models import Studio
from apps.studios.serializers import StudioSerializer


class StudioCreateView(generics.CreateAPIView):
    queryset = Studio.objects.all()
    serializer_class = StudioSerializer
    permission_classes = [IsStaff]


class StudioDetailView(generics.RetrieveUpdateAPIView):
    queryset = Studio.objects.all()
    serializer_class = StudioSerializer
    permission_classes = [IsStaff]