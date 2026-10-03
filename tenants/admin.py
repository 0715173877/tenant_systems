from django.contrib import admin
from .models import Tenant, Lease, RentInvoice


class LeaseInline(admin.TabularInline):
    model = Lease
    extra = 0
    fields = ["unit", "start_date", "end_date", "monthly_rent", "status"]
    readonly_fields = ["status"]


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = [
        "full_name", "phone_number", "email", "is_active",
    ]
    list_filter = ["is_active"]
    search_fields = ["full_name", "phone_number", "email", "id_number"]
    inlines = [LeaseInline]


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = [
        "tenant", "unit", "start_date", "end_date",
        "monthly_rent", "deposit_paid", "status",
    ]
    list_filter = ["status", "deposit_paid"]
    search_fields = ["tenant__full_name", "unit__unit_number"]
    date_hierarchy = "start_date"


@admin.register(RentInvoice)
class RentInvoiceAdmin(admin.ModelAdmin):
    list_display = [
        "lease", "period_start", "due_date", "amount", "amount_paid",
        "balance", "effective_status",
    ]
    list_filter = ["due_date"]
    search_fields = ["lease__tenant__full_name", "lease__unit__unit_number"]
    date_hierarchy = "period_start"
    readonly_fields = ["effective_status", "balance"]
