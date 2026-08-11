from django.db import models

class NotificationSetting(models.Model):
    """
    Stores configurable settings for automated SMS notifications.
    Only one row should exist (singleton pattern enforced in code).
    """
    # --- Lease Expiry Reminder ---
    lease_expiry_enabled = models.BooleanField(
        default=True,
        help_text="Enable/disable automatic lease expiry SMS reminders",
    )
    lease_expiry_days_before = models.PositiveIntegerField(
        default=14,
        help_text="How many days before lease expiry to send the reminder",
    )
    lease_expiry_hour = models.PositiveIntegerField(
        default=9,
        help_text="Hour of day to send reminders (0-23, Africa/Dar_es_Salaam timezone)",
    )
    lease_expiry_minute = models.PositiveIntegerField(
        default=0,
        help_text="Minute of hour to send reminders (0-59)",
    )
    lease_expiry_message_template = models.TextField(
        default="Dear {tenant_name}, your lease for {unit_name} will expire in {days_left} day(s) on {end_date}. Please contact us to discuss renewal options.",
        help_text=(
            "SMS template for lease expiry reminders. Available placeholders: "
            "{tenant_name}, {unit_name}, {end_date}, {days_left}, {phone_number}"
        ),
    )

    # --- Rent Reminder ---
    rent_reminder_enabled = models.BooleanField(
        default=True,
        help_text="Enable/disable automatic rent reminders",
    )
    rent_reminder_days_before = models.PositiveIntegerField(
        default=3,
        help_text="How many days before rent due date to send reminders",
    )
    rent_reminder_hour = models.PositiveIntegerField(
        default=8,
        help_text="Hour of day to send rent reminders",
    )
    rent_reminder_minute = models.PositiveIntegerField(
        default=0,
        help_text="Minute of hour to send rent reminders",
    )
    rent_reminder_message_template = models.TextField(
        default="Dear {tenant_name}, this is a reminder that your rent of {currency} {amount} for {unit_name} is due on {due_date}. Please make payment to avoid late charges. Thank you.",
        help_text=(
            "SMS template for rent reminders. Available placeholders: "
            "{tenant_name}, {unit_name}, {amount}, {currency}, {due_date}, {phone_number}"
        ),
    )

    # --- Metadata ---
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Notification Setting"
        verbose_name_plural = "Notification Settings"

    def __str__(self):
        return f"Notification Settings (updated {self.updated_at})"
