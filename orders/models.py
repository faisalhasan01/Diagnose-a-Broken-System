from django.db import models
from contextvars import ContextVar

# Security Note: ContextVar is thread-safe and async-safe.
# It isolates tenant context per request lifecycle (even in async views).
_tenant_context = ContextVar('current_tenant_id', default=None)

class Tenant(models.Model):
    name = models.CharField(max_length=255)
    subdomain = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class TenantContext:
    @staticmethod
    def get_current_tenant_id():
        return _tenant_context.get()

    @staticmethod
    def set_current_tenant_id(tenant_id):
        return _tenant_context.set(tenant_id)

    @staticmethod
    def clear():
        _tenant_context.set(None)

class TenantQuerySet(models.QuerySet):
    def for_tenant(self, tenant_id):
        if tenant_id is not None:
            return self.filter(tenant_id=tenant_id)
        # Fail-closed: If no tenant context is set, return empty queryset to prevent leaks
        return self.none()

class TenantManager(models.Manager):
    def get_queryset(self):
        tenant_id = TenantContext.get_current_tenant_id()
        return TenantQuerySet(self.model, using=self._db).for_tenant(tenant_id)

    def create(self, **kwargs):
        # Automatically bind current tenant context during record creation
        tenant_id = TenantContext.get_current_tenant_id()
        if tenant_id is not None and 'tenant_id' not in kwargs and 'tenant' not in kwargs:
            kwargs['tenant_id'] = tenant_id
        return super().create(**kwargs)


class Customer(models.Model):
    TIER_CHOICES = [
        ('REGULAR', 'Regular'),
        ('GOLD', 'Gold'),
        ('PLATINUM', 'Platinum'),
    ]
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    tier = models.CharField(max_length=20, choices=TIER_CHOICES, default='REGULAR')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    sku = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Order(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('SHIPPED', 'Shipped'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='orders')
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()

    def __str__(self):
        return f"Order #{self.id} for {self.customer.name}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)  # Snapshot of price at time of purchase

    def __str__(self):
        return f"{self.quantity} x {self.product.name} (Order #{self.order.id})"


class Payment(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='payment')
    method = models.CharField(max_length=50)  # CREDIT_CARD, PAYPAL, BANK_TRANSFER, etc.
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='PENDING')
    transaction_id = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment for Order #{self.order.id} - {self.status}"
