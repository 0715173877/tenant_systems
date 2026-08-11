"""
Celery tasks for async SMS sending and automated reminders.
"""
from celery import shared_task
from django.utils import timezone
from django.db.models import Q
from .services import beem_client
from .models import NotificationSetting
from tenants.models import Lease, Tenant
from bookings.models import Booking


@shared_task
def send_async_sms(phone_number: str, message: str) -> dict:
    """Send an SMS asynchronously via Celery."""
    return beem_client.send_sms(phone_number, message)


@shared_task
def send_bulk_sms_async(message: str, recipients: list[dict]) -> dict:
    """
    Send an SMS to multiple recipients asynchronously via Celery.

    Args:
        message: SMS text content.
        recipients: List of dicts with keys recipient_id and dest_addr.

    Returns:
        API response dict.
    """
    return beem_client.send_bulk_sms(message=message, recipients=recipients)


@shared_task
def send_rent_reminders():
    """
    Daily task: send SMS reminders for active leases
    whose rent is due within the next N days (configurable).
    """
    today = timezone.now().date()

    # Read configurable settings from NotificationSetting
    try:
        ns = NotificationSetting.objects.first()
        days_before = ns.rent_reminder_days_before if ns else 3
        enabled = ns.rent_reminder_enabled if ns else True
    except Exception:
        days_before = 3
        enabled = True

    if not enabled:
        return "Rent reminders are disabled (skipping)"

    due_date = today + timezone.timedelta(days=days_before)

    upcoming_leases = Lease.objects.filter(
        status="active",
        start_date__gte=today,
        start_date__lte=due_date,
    ).select_related("tenant", "unit__block__property")

    # Get the custom message template (or fallback to default)
    try:
        ns = NotificationSetting.objects.first()
        template = ns.rent_reminder_message_template if ns else ""
    except Exception:
        template = ""

    if not template:
        template = "Dear {tenant_name}, this is a reminder that your rent of {currency} {amount} for {unit_name} is due on {due_date}. Please make payment to avoid late charges. Thank you."

    sent = 0
    for lease in upcoming_leases:
        tenant = lease.tenant
        currency = lease.unit.effective_currency
        try:
            message = template.format(
                tenant_name=tenant.full_name,
                unit_name=str(lease.unit),
                amount=str(lease.monthly_rent),
                currency=currency,
                due_date=str(lease.start_date),
                phone_number=tenant.phone_number,
            )
            beem_client.send_tenant_sms_with_cc(
                tenant.phone_number,
                message,
                lease.unit.block.property,
            )
            sent += 1
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.error("Rent reminder failed for %s: %s", tenant, exc)

    return f"Sent {sent} rent reminder(s)"


@shared_task
def send_upcoming_checkin_reminders():
    """
    Daily task: send SMS reminders for bookings with check-in tomorrow.
    """
    tomorrow = timezone.now().date() + timezone.timedelta(days=1)

    upcoming = Booking.objects.filter(
        check_in=tomorrow,
        status__in=["confirmed", "pending"],
    ).select_related("guest", "unit")

    sent = 0
    for booking in upcoming:
        guest = booking.guest
        try:
            beem_client.notify_booking_confirmation(
                phone=guest.phone_number,
                guest_name=guest.full_name,
                unit_name=str(booking.unit),
                check_in=str(booking.check_in),
                check_out=str(booking.check_out),
                total=str(booking.total_amount or ""),
            )
            sent += 1
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.error("Check-in reminder failed for %s: %s", guest, exc)

    return f"Sent {sent} check-in reminder(s)"


@shared_task
def send_lease_expiry_reminders():
    """
    Daily task: send SMS reminders for active leases expiring within
    a configurable number of days (default 14).
    Also alerts for leases that expired in the last 7 days.

    The schedule time (hour/minute) is configured via NotificationSetting
    in the UI, but the Celery Beat schedule in settings.py determines when
    this task actually runs.
    """
    from datetime import timedelta
    today = timezone.now().date()

    # Read configurable settings from NotificationSetting
    try:
        ns = NotificationSetting.objects.first()
        days_before = ns.lease_expiry_days_before if ns else 14
        enabled = ns.lease_expiry_enabled if ns else True
    except Exception:
        days_before = 14
        enabled = True

    if not enabled:
        return "Lease expiry reminders are disabled (skipping)"

    target_date = today + timedelta(days=days_before)
    seven_days_ago = today - timedelta(days=7)

    # Leases expiring within the configurable window (still active)
    expiring_soon = Lease.objects.filter(
        status="active",
        end_date__gte=today,
        end_date__lte=target_date,
    ).select_related("tenant", "unit__block__property")

    # Leases that expired in the last 7 days (but may still be marked active)
    recently_expired = Lease.objects.filter(
        status="active",
        end_date__gte=seven_days_ago,
        end_date__lt=today,
    ).select_related("tenant", "unit__block__property")

    sent = 0

    # Get the custom message template
    template = ns.lease_expiry_message_template if ns else ""
    if not template:
        template = "Dear {tenant_name}, your lease for {unit_name} will expire in {days_left} day(s) on {end_date}. Please contact us to discuss renewal options."

    for lease in expiring_soon:
        tenant = lease.tenant
        days_left = (lease.end_date - today).days
        try:
            message = template.format(
                tenant_name=tenant.full_name,
                unit_name=str(lease.unit),
                end_date=str(lease.end_date),
                days_left=days_left,
                phone_number=tenant.phone_number,
            )
            beem_client.send_tenant_sms_with_cc(
                tenant.phone_number,
                message,
                lease.unit.block.property,
            )
            sent += 1
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.error("Lease expiry reminder failed for %s: %s", tenant, exc)

    for lease in recently_expired:
        tenant = lease.tenant
        try:
            message = template.format(
                tenant_name=tenant.full_name,
                unit_name=str(lease.unit),
                end_date=str(lease.end_date),
                days_left=0,
                phone_number=tenant.phone_number,
            )
            beem_client.send_tenant_sms_with_cc(
                tenant.phone_number,
                message,
                lease.unit.block.property,
            )
            sent += 1
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.error("Lease expiry alert failed for %s: %s", tenant, exc)

    return f"Sent {sent} lease expiry reminder(s)"
