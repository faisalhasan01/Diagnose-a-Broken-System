from django.db.models import Prefetch
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Order, OrderItem
from .serializers import OrderSummarySerializer

class SlowOrderSummaryView(APIView):
    """
    Demonstrates the performance regression.
    Fetches orders without optimizing database queries for related fields.
    Triggers N+1 queries on customer, payment, items, and products.
    """
    def get(self, request):
        customer_id = request.query_params.get('customer_id')
        if not customer_id:
            return Response({"error": "customer_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        orders = Order.objects.filter(customer_id=customer_id)
        serializer = OrderSummarySerializer(orders, many=True)
        return Response(serializer.data)


class FastOrderSummaryView(APIView):
    """
    The fixed version.
    Uses select_related for One-to-One and Foreign Key relations (payment, customer).
    Uses prefetch_related with an inner select_related to fetch the OrderItems and 
    their related Products in a single optimized query.
    """
    def get(self, request):
        customer_id = request.query_params.get('customer_id')
        if not customer_id:
            return Response({"error": "customer_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Fix: Fetch the orders, customers, and payments in one JOINed query,
        # and prefetch order items + products in another JOINed query.
        orders = Order.objects.filter(customer_id=customer_id).select_related(
            'customer',
            'payment'
        ).prefetch_related(
            Prefetch(
                'items',
                queryset=OrderItem.objects.select_related('product')
            )
        )
        serializer = OrderSummarySerializer(orders, many=True)
        return Response(serializer.data)


from django.views.generic import TemplateView
from .models import Customer

class DashboardView(TemplateView):
    template_name = 'orders/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['customers'] = Customer.objects.all()
        return context
