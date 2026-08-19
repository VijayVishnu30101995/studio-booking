from django.urls import path

from apps.classes.views import ClassDetailView, ClassListCreateView

urlpatterns = [
    path("", ClassListCreateView.as_view(), name="class-list-create"),
    path("<int:pk>/", ClassDetailView.as_view(), name="class-detail"),
]
