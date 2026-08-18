from django.urls import path

from apps.waitlist.views import (
    MyWaitlistListView,
    WaitlistView,
)


urlpatterns = [
    path(
        "classes/<int:pk>/waitlist/",
        WaitlistView.as_view(),
        name="waitlist",
    ),
    path(
        "me/waitlist/",
        MyWaitlistListView.as_view(),
        name="my-waitlist",
    ),
]