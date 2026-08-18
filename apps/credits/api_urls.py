from django.urls import path

from apps.credits.views import (
    CreditBalanceAtView,
    CreditBalanceView,
    CreditTransactionListView,
)


urlpatterns = [
    path(
        "",
        CreditBalanceView.as_view(),
        name="credit-balance",
    ),
    path(
        "transactions/",
        CreditTransactionListView.as_view(),
        name="credit-transactions",
    ),
    path(
        "balance-at/",
        CreditBalanceAtView.as_view(),
        name="credit-balance-at",
    ),
]