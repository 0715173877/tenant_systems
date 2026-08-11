from django.contrib import admin
from .models import Property, Block, Unit, UnitAmenity, PropertyStaff, MaintenanceRequest, OwnerProfile


class BlockInline(admin.TabularInline):
    model = Block
    extra = 1
    fields = ["name", "location", "is_active"]


class StaffInline(admin.TabularInline):
    model = PropertyStaff
    extra = 1
    fields = ["user", "role", "is_active"]


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "location", "total_blocks", "total_units", "is_active"]
    list_filter = ["is_active", "owner"]
    search_fields = ["name", "location", "owner__username"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [BlockInline, StaffInline]


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ["name", "property", "location", "is_active"]
    list_filter = ["is_active", "property"]
    search_fields = ["name", "property__name", "location"]


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = [
        "unit_number", "block", "unit_property", "rental_type", "unit_type",
        "monthly_rent", "nightly_rate", "unit_currency", "is_available",
    ]
    list_filter = ["block__property", "block", "rental_type", "is_available", "unit_type"]
    search_fields = ["unit_number", "block__name", "block__property__name"]
    filter_horizontal = ["amenities"]

    def unit_property(self, obj):
        return obj.block.property
    unit_property.short_description = "Property"
    unit_property.admin_order_field = "block__property"

    def unit_currency(self, obj):
        return obj.effective_currency
    unit_currency.short_description = "Currency"


@admin.register(UnitAmenity)
class UnitAmenityAdmin(admin.ModelAdmin):
    list_display = ["name", "icon"]


@admin.register(PropertyStaff)
class PropertyStaffAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "property", "is_active"]
    list_filter = ["role", "is_active", "property"]
    search_fields = ["user__username", "user__email", "property__name"]


@admin.register(MaintenanceRequest)
class MaintenanceRequestAdmin(admin.ModelAdmin):
    list_display = ["title", "property", "unit", "priority", "status", "assigned_to", "created_at"]
    list_filter = ["status", "priority", "property"]
    search_fields = ["title", "description", "property__name"]
    date_hierarchy = "created_at"
    readonly_fields = ["created_at", "updated_at", "completed_at", "reported_by"]
    fieldsets = (
        ("Details", {
            "fields": ("property", "unit", "title", "description", "priority", "status")
        }),
        ("Assignment", {
            "fields": ("reported_by", "assigned_to", "assigned_at")
        }),
        ("Resolution", {
            "fields": ("resolution_notes", "cost", "completed_at")
        }),
        ("Work Log", {
            "fields": ("notes",),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


@admin.register(OwnerProfile)
class OwnerProfileAdmin(admin.ModelAdmin):
    list_display = ["owner", "has_bank_account", "has_mobile_money", "updated_at"]
    search_fields = ["owner__username", "bank_name", "bank_account_number", "mpesa_number"]
    fieldsets = (
        ("Owner Info", {
            "fields": ("owner", "phone", "email")
        }),
        ("Bank Account", {
            "fields": ("bank_name", "bank_account_name", "bank_account_number",
                       "bank_branch", "bank_currency"),
            "classes": ("collapse",),
        }),
        ("Mobile Money", {
            "fields": ("mpesa_number", "mpesa_account_name",
                       "tigo_pesa_number", "airtel_money_number"),
            "classes": ("collapse",),
        }),
        ("Payment Instructions", {
            "fields": ("payment_instructions",),
        }),
    )
