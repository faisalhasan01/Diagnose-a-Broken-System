from django.urls import path
from .views import SlowOrderSummaryView, FastOrderSummaryView

urlpatterns = [
    path('summary/', SlowOrderSummaryView.as_view(), name='orders-summary-slow'),
    path('summary-fixed/', FastOrderSummaryView.as_view(), name='orders-summary-fast'),
]
