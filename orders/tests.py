from django.test import TestCase
from django.urls import reverse
from django.db import connection
from django.db.models import Prefetch
from rest_framework import status
from orders.models import Customer, Product, Order, OrderItem, Payment
from orders.serializers import OrderSummarySerializer


class OrderSummaryPerformanceTest(TestCase):
    def setUp(self):
        # Set up customer and products
        self.customer = Customer.objects.create(
            name="Test Customer", 
            email="test@example.com", 
            tier="PLATINUM"
        )
        self.products = [
            Product.objects.create(name=f"Product {i}", price=10.0 * i, sku=f"SKU-{i}")
            for i in range(1, 4)
        ]
        
        # Create 5 orders for testing.
        # Even with 5 orders, the N+1 problem is highly pronounced.
        for i in range(5):
            order = Order.objects.create(customer=self.customer, status="PENDING")
            Payment.objects.create(
                order=order, 
                method="CREDIT_CARD", 
                status="COMPLETED", 
                transaction_id=f"TXN-{i}"
            )
            for product in self.products:
                OrderItem.objects.create(
                    order=order, 
                    product=product, 
                    quantity=2, 
                    price=product.price
                )

    def test_endpoints_return_same_data(self):
        slow_url = f"{reverse('orders-summary-slow')}?customer_id={self.customer.id}"
        fast_url = f"{reverse('orders-summary-fast')}?customer_id={self.customer.id}"

        response_slow = self.client.get(slow_url)
        response_fast = self.client.get(fast_url)

        self.assertEqual(response_slow.status_code, status.HTTP_200_OK)
        self.assertEqual(response_fast.status_code, status.HTTP_200_OK)
        self.assertEqual(response_slow.json(), response_fast.json())

    def test_query_count_difference(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        # Measure queries for slow (buggy) queryset + serialization
        with CaptureQueriesContext(connection) as slow_ctx:
            orders = list(Order.objects.filter(customer_id=self.customer.id))
            serializer = OrderSummarySerializer(orders, many=True)
            _ = serializer.data
        
        # Filter out EXPLAIN queries executed by Silk for profiling
        slow_queries_count = sum(1 for q in slow_ctx.captured_queries if not q['sql'].strip().upper().startswith('EXPLAIN'))
        
        # Measure queries for fast (optimized) queryset + serialization
        with CaptureQueriesContext(connection) as fast_ctx:
            orders = list(Order.objects.filter(customer_id=self.customer.id).select_related(
                'customer',
                'payment'
            ).prefetch_related(
                Prefetch(
                    'items',
                    queryset=OrderItem.objects.select_related('product')
                )
            ))
            serializer = OrderSummarySerializer(orders, many=True)
            _ = serializer.data
        
        # Filter out EXPLAIN queries executed by Silk for profiling
        fast_queries_count = sum(1 for q in fast_ctx.captured_queries if not q['sql'].strip().upper().startswith('EXPLAIN'))
        
        print(f"\n[PERFORMANCE REPORT]")
        print(f"Number of orders in test: 5")
        print(f"Buggy Endpoint Query Count: {slow_queries_count} SQL queries")
        print(f"Optimized Endpoint Query Count: {fast_queries_count} SQL queries")
        print(f"Query reduction: {slow_queries_count - fast_queries_count} queries saved! "
              f"({((slow_queries_count - fast_queries_count)/slow_queries_count)*100:.1f}% reduction)")
        
        # The optimized query should take exactly 2 queries:
        # 1. Fetch Orders joined with Customer and Payment (select_related).
        # 2. Fetch OrderItems joined with Product (prefetch_related + select_related product).
        self.assertEqual(fast_queries_count, 2, "Fast endpoint must execute exactly 2 queries.")
        self.assertGreater(slow_queries_count, 25, "Slow endpoint should trigger high query volume.")
