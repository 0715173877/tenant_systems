from django.contrib import admin
from .models import Guest, Booking


class BookingInline(admin.TabularInline):
    model = Booking
    extra = 0
    fields = [
        "unit", "check_in", "check_out", "total_amount",
        "amount_paid", "status",
    ]
    readonly_fields = ["total_amount"]


@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    list_display = ["full_name", "phone_number", "email", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["full_name", "phone_number", "email", "id_number"]
    inlines = [BookingInline]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = [
        "guest", "unit", "check_in", "check_out",
        "number_of_guests", "total_amount", "amount_paid", "status",
    ]
    list_filter = ["status", "check_in", "unit__block"]
    search_fields = ["guest__full_name", "unit__unit_number"]
    date_hierarchy = "check_in"
