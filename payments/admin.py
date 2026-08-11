from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "tenant_name", "payment_type", "payment_method",
        "amount", "payment_date", "status",
    ]
    list_filter = ["payment_type", "payment_method", "status"]
    search_fields = ["tenant_name", "transaction_reference"]
    date_hierarchy = "payment_date"
