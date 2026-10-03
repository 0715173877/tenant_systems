from django.conf import settings
from django.db import models


class NotificationSetting(models.Model):
    """
    Stores configurable settings for automated SMS notifications.

    Settings are per-landlord (per owner): each owner configures their own
    reminder behaviour and message templates. A row is created on demand via
    :meth:`for_owner`.
    """

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_setting",
        null=True,
        blank=True,
        help_text="The landlord/owner these settings belong to",
    )
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
        who = self.owner.username if self.owner else "Unassigned"
        return f"Notification Settings for {who} (updated {self.updated_at})"

    @classmethod
    def for_owner(cls, owner):
        """
        Return the :class:`NotificationSetting` for ``owner``, creating one
        with defaults if it does not exist yet.

        When ``owner`` is ``None`` an unsaved instance with default values is
        returned so callers can safely read the default templates/settings
        without persisting anything.
        """
        if owner is None:
            return cls()
        setting, _created = cls.objects.get_or_create(owner=owner)
        return setting

