from django.urls import path

from apps.credits.views import CreditPackCreateView


urlpatterns = [
    path(
        "",
        CreditPackCreateView.as_view(),
        name="credit-pack-create",
    ),
]
