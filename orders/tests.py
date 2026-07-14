import json
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.db import connection
from django.db.models import Prefetch
from rest_framework import status
import redis

from orders.models import Customer, Product, Order, OrderItem, Payment, Tenant, TenantContext
from orders.serializers import OrderSummarySerializer
from orders.tasks import send_transactional_email, check_rate_limit, ThrottledException, redis_client
from celery.exceptions import Retry


class OrderSummaryPerformanceTest(TestCase):
    """Section 1: Performance Investigation and Query Count Verification"""
    def setUp(self):
        # Create a test tenant and set it in context
        self.tenant = Tenant.objects.create(name="Test Tenant", subdomain="test-tenant")
        TenantContext.set_current_tenant_id(self.tenant.id)

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

    def tearDown(self):
        TenantContext.clear()

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
        
        # The optimized query should take exactly 2 queries
        self.assertEqual(fast_queries_count, 2, "Fast endpoint must execute exactly 2 queries.")
        self.assertGreater(slow_queries_count, 25, "Slow endpoint should trigger high query volume.")


class EmailQueueTests(TestCase):
    """Section 2: Rate-Limited Async Job Queue & DLQ Verification"""
    def setUp(self):
        # Clear testing keys in Redis
        redis_client.delete("email_rate_limit")
        redis_client.delete("email_dlq")

    def tearDown(self):
        redis_client.delete("email_rate_limit")
        redis_client.delete("email_dlq")

    def test_rate_limiter_never_exceeds_limit(self):
        """Submit 500 rate-limit checks and assert exactly 200 succeed and 300 fail"""
        success_count = 0
        denied_count = 0
        
        for _ in range(500):
            if check_rate_limit(rate_limit_key="email_rate_limit", limit=200, window=60):
                success_count += 1
            else:
                denied_count += 1
                
        self.assertEqual(success_count, 200, "Exactly 200 requests must be allowed.")
        self.assertEqual(denied_count, 300, "Exactly 300 requests must be blocked/throttled.")

    def test_task_retries_on_rate_limit(self):
        """Assert that if rate limit is hit, task attempts to retry"""
        # Exhaust rate limit first
        for _ in range(200):
            check_rate_limit(rate_limit_key="email_rate_limit", limit=200, window=60)
            
        # The 201st call should trigger a Retry exception
        email_data = {"to": "user@example.com", "subject": "Test Task", "body": "Throttled retry test"}
        with self.assertRaises((Retry, ThrottledException)):
            send_transactional_email.run(send_transactional_email, email_data)

    def test_failed_task_retries_and_goes_to_dlq(self):
        """Assert that a failing task retries up to max_retries and is routed to Redis DLQ"""
        email_data = {"to": "user@example.com", "subject": "Crash Alert", "body": "This email will fail"}
        
        # We invoke the task with is_test_fail=True to trigger simulated exception
        # Running through Celery's .apply() executes it synchronously on the test runner.
        result = send_transactional_email.apply(args=[email_data], kwargs={"is_test_fail": True})
        
        # Verify the execution status
        self.assertTrue(result.failed())
        
        # Verify that DLQ contains the failed job details
        dlq_length = redis_client.llen("email_dlq")
        self.assertEqual(dlq_length, 1, "Exactly one failed task must be sent to the DLQ.")
        
        # Verify DLQ payload attributes
        dlq_entry_raw = redis_client.lindex("email_dlq", 0)
        dlq_entry = json.loads(dlq_entry_raw)
        
        self.assertEqual(dlq_entry["email_data"]["subject"], "Crash Alert")
        self.assertIn("Simulated connection error", dlq_entry["error"])
        self.assertIsNotNone(dlq_entry["task_id"])


class TenantDataIsolationTests(TestCase):
    """Section 3: Multi-Tenant Data Isolation ORM Scoping Verification"""
    def setUp(self):
        # Create Tenants
        self.tenant_a = Tenant.objects.create(name="Tenant A", subdomain="tenant-a")
        self.tenant_b = Tenant.objects.create(name="Tenant B", subdomain="tenant-b")
        
        # Create a Customer and Product
        # Note: Customer is shared across database, but Orders are scoped.
        self.customer = Customer.objects.create(name="Tenant Customer", email="tenant@example.com")
        self.product = Product.objects.create(name="SaaS Subscription", price=99.0, sku="SKU-SAAS")

    def tearDown(self):
        TenantContext.clear()

    def test_tenant_isolation_enforced(self):
        """Verify that Tenant A queries cannot see Tenant B data and vice-versa"""
        # Create Order for Tenant A
        TenantContext.set_current_tenant_id(self.tenant_a.id)
        order_a = Order.objects.create(customer=self.customer, status="PENDING")
        self.assertEqual(order_a.tenant_id, self.tenant_a.id)

        # Create Order for Tenant B
        TenantContext.set_current_tenant_id(self.tenant_b.id)
        order_b = Order.objects.create(customer=self.customer, status="PENDING")
        self.assertEqual(order_b.tenant_id, self.tenant_b.id)

        # Scope context to Tenant A and query
        TenantContext.set_current_tenant_id(self.tenant_a.id)
        orders_a = list(Order.objects.all())
        self.assertIn(order_a, orders_a)
        self.assertNotIn(order_b, orders_a)
        self.assertEqual(len(orders_a), 1)

        # Scope context to Tenant B and query
        TenantContext.set_current_tenant_id(self.tenant_b.id)
        orders_b = list(Order.objects.all())
        self.assertIn(order_b, orders_b)
        self.assertNotIn(order_a, orders_b)
        self.assertEqual(len(orders_b), 1)

    def test_query_all_does_not_bypass_isolation(self):
        """Verify that calling Order.objects.all() is automatically scoped and does not leak"""
        # Create orders under Tenant A
        TenantContext.set_current_tenant_id(self.tenant_a.id)
        Order.objects.create(customer=self.customer, status="PROCESSING")
        Order.objects.create(customer=self.customer, status="SHIPPED")

        # Create order under Tenant B
        TenantContext.set_current_tenant_id(self.tenant_b.id)
        Order.objects.create(customer=self.customer, status="DELIVERED")

        # Set context to Tenant A and assert count is 2 (excluding Tenant B's order)
        TenantContext.set_current_tenant_id(self.tenant_a.id)
        self.assertEqual(Order.objects.all().count(), 2)

    def test_fail_closed_without_tenant_context(self):
        """Verify that if no tenant context is bound, ORM returns empty queryset (fails closed)"""
        # Create an order under Tenant A
        TenantContext.set_current_tenant_id(self.tenant_a.id)
        Order.objects.create(customer=self.customer, status="PENDING")

        # Clear context (simulating missing tenant identifier in middleware)
        TenantContext.clear()
        
        # Order.objects.all() must return an empty queryset to fail closed safely
        orders = Order.objects.all()
        self.assertEqual(orders.count(), 0)
        self.assertEqual(list(orders), [])
