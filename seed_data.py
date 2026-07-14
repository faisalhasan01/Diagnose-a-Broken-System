import os
import django
import random
from datetime import timedelta
from django.utils import timezone

# Configure settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_perf_assessment.settings')
django.setup()

from orders.models import Customer, Product, Order, OrderItem, Payment, Tenant, TenantContext

def seed_db():
    print("Clearing existing data...")
    Tenant.objects.all().delete()  # Cascades to clear Orders, Payments, and OrderItems
    Customer.objects.all().delete()
    Product.objects.all().delete()

    print("Creating default tenant...")
    tenant = Tenant.objects.create(
        name="Artikate Studio Client A",
        subdomain="tenant-a"
    )
    # Set the tenant context for the current process/thread
    TenantContext.set_current_tenant_id(tenant.id)

    print("Seeding customer...")
    customer = Customer.objects.create(
        name="Alice Smith",
        email="alice@example.com",
        tier="PLATINUM"
    )

    print("Seeding products...")
    products = [
        Product.objects.create(name="Gaming  Mouse", price=49.99, sku="PROD-001"),
        Product.objects.create(name="Mechanical Keyboard", price=99.99, sku="PROD-002"),
        Product.objects.create(name="USB-C Hub", price=49.99, sku="PROD-003"),
        Product.objects.create(name="4K Monitor", price=349.99, sku="PROD-004"),
    ]

    print("Seeding 250 orders for Alice...")
    from django.db import transaction

    with transaction.atomic():
        now = timezone.now()
        for i in range(1, 251):
            order = Order.objects.create(
                customer=customer,
                status=random.choice(['PENDING', 'PROCESSING', 'SHIPPED', 'DELIVERED']),
            )
            # Spread orders in time
            order.created_at = now - timedelta(hours=i)
            order.save()

            # Create payment
            Payment.objects.create(
                order=order,
                method=random.choice(['CREDIT_CARD', 'PAYPAL', 'BANK_TRANSFER']),
                status='COMPLETED',
                transaction_id=f"TXN-{100000 + i}"
            )

            # Create 1 to 3 items per order
            num_items = random.randint(1, 3)
            selected_products = random.sample(products, num_items)
            for product in selected_products:
                qty = random.randint(1, 3)
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=qty,
                    price=product.price
                )

    TenantContext.clear()
    print("Seeding completed successfully!")
    print(f"Created: 1 Customer, {len(products)} Products, 250 Orders, 250 Payments.")

if __name__ == '__main__':
    seed_db()
