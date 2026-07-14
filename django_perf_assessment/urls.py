from django.contrib import admin
from django.urls import path, include
from orders.views import DashboardView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/orders/', include('orders.urls')),
    path('silk/', include('silk.urls', namespace='silk')),
    path('', DashboardView.as_view(), name='dashboard'),
]
