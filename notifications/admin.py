from django.contrib import admin
from .models import NotificationSetting


@admin.register(NotificationSetting)
class NotificationSettingAdmin(admin.ModelAdmin):
    list_display = [
        "lease_expiry_enabled",
        "lease_expiry_days_before",
        "lease_expiry_hour",
        "lease_expiry_minute",
        "rent_reminder_enabled",
        "rent_reminder_days_before",
        "updated_at",
    ]
    fieldsets = (
        ("Lease Expiry Reminder", {
            "fields": (
                "lease_expiry_enabled",
                "lease_expiry_days_before",
                ("lease_expiry_hour", "lease_expiry_minute"),
                "lease_expiry_message_template",
            ),
        }),
        ("Rent Reminder", {
            "fields": (
                "rent_reminder_enabled",
                "rent_reminder_days_before",
                ("rent_reminder_hour", "rent_reminder_minute"),
            ),
        }),
        ("Metadata", {
            "fields": ("updated_at",),
        }),
    )
    readonly_fields = ("updated_at",)
