from rest_framework import serializers
from .models import Order, OrderItem, Payment, Customer

class OrderSummarySerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name')
    customer_tier = serializers.CharField(source='customer.tier')
    payment_method = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()
    total_price = serializers.SerializerMethodField()
    items_summary = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 
            'status', 
            'created_at', 
            'customer_name', 
            'customer_tier', 
            'payment_method', 
            'payment_status', 
            'total_price', 
            'items_summary'
        ]

    def get_payment_method(self, obj):
        try:
            return obj.payment.method
        except Payment.DoesNotExist:
            return 'N/A'

    def get_payment_status(self, obj):
        try:
            return obj.payment.status
        except Payment.DoesNotExist:
            return 'N/A'

    def get_total_price(self, obj):
        # In a naive queryset, accessing items.all() executes a SQL query per order
        return sum(item.price * item.quantity for item in obj.items.all())

    def get_items_summary(self, obj):
        # In a naive queryset, accessing items.all() executes a SQL query,
        # and accessing item.product executes a SQL query per item (N+1 nested)
        items = obj.items.all()
        summary = []
        for item in items:
            summary.append(f"{item.quantity} x {item.product.name}")
        return ", ".join(summary)
