from django.urls import path

from apps.studios.views import StudioCreateView, StudioDetailView


urlpatterns = [
    path("", StudioCreateView.as_view(), name="studio-create"),
    path(
        "<int:pk>/",
        StudioDetailView.as_view(),
        name="studio-detail",
    ),
]