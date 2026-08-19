from django.urls import path

from apps.bookings.views import BookingCreateView, CancellationView, MyBookingListView

urlpatterns = [
    path(
        "classes/<int:pk>/book/",
        BookingCreateView.as_view(),
        name="booking-create",
    ),
    path(
        "me/bookings/",
        MyBookingListView.as_view(),
        name="my-bookings",
    ),
    path(
        "bookings/<int:pk>/cancel/",
        CancellationView.as_view(),
        name="booking-cancel",
    ),
]