"""
Celery tasks for async SMS sending and automated reminders.
"""
from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone
from .services import beem_client
from .models import NotificationSetting
from tenants.models import Lease
from bookings.models import Booking
from properties.models import Property


DEFAULT_RENT_TEMPLATE = (
    "Dear {tenant_name}, this is a reminder that your rent of {currency} {amount} "
    "for {unit_name} is due on {due_date}. Please make payment to avoid late charges. Thank you."
)
DEFAULT_LEASE_TEMPLATE = (
    "Dear {tenant_name}, your lease for {unit_name} will expire in {days_left} day(s) "
    "on {end_date}. Please contact us to discuss renewal options."
)


def _iter_owner_settings():
    """
    Yield ``(owner, setting)`` for every distinct property owner plus a
    ``(None, setting)`` pair for properties that have no owner, so each
    landlord's reminders use only their own configuration and data.
    """
    owner_ids = (
        Property.objects.exclude(owner__isnull=True)
        .values_list("owner_id", flat=True)
        .distinct()
    )
    User = get_user_model()
    for owner in User.objects.filter(pk__in=list(owner_ids)):
        yield owner, NotificationSetting.for_owner(owner)
    if Property.objects.filter(owner__isnull=True).exists():
        yield None, NotificationSetting.for_owner(None)


def _scope_leases_to_owner(queryset, owner):
    """Restrict a Lease queryset to those belonging to ``owner``."""
    if owner is None:
        return queryset.filter(unit__block__property__owner__isnull=True)
    return queryset.filter(unit__block__property__owner=owner)


def _scope_bookings_to_owner(queryset, owner):
    """Restrict a Booking queryset to those belonging to ``owner``."""
    if owner is None:
        return queryset.filter(unit__block__property__owner__isnull=True)
    return queryset.filter(unit__block__property__owner=owner)


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
    whose rent is due within the next N days (configurable per owner).
    """
    import logging
    logger = logging.getLogger(__name__)
    today = timezone.now().date()

    sent = 0
    for owner, ns in _iter_owner_settings():
        if not ns.rent_reminder_enabled:
            continue

        due_date = today + timezone.timedelta(days=ns.rent_reminder_days_before)
        upcoming_leases = _scope_leases_to_owner(
            Lease.objects.filter(
                status="active",
                start_date__gte=today,
                start_date__lte=due_date,
            ),
            owner,
        ).select_related("tenant", "unit__block__property")

        template = ns.rent_reminder_message_template or DEFAULT_RENT_TEMPLATE

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
                logger.error("Rent reminder failed for %s: %s", tenant, exc)

    return f"Sent {sent} rent reminder(s)"


@shared_task
def send_upcoming_checkin_reminders():
    """
    Daily task: send SMS reminders for bookings with check-in tomorrow.
    Scoped per owner so each landlord only notifies their own guests.
    """
    import logging
    logger = logging.getLogger(__name__)
    tomorrow = timezone.now().date() + timezone.timedelta(days=1)

    sent = 0
    for owner, _ns in _iter_owner_settings():
        upcoming = _scope_bookings_to_owner(
            Booking.objects.filter(
                check_in=tomorrow,
                status__in=["confirmed", "pending"],
            ),
            owner,
        ).select_related("guest", "unit")

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
                logger.error("Check-in reminder failed for %s: %s", guest, exc)

    return f"Sent {sent} check-in reminder(s)"


@shared_task
def send_lease_expiry_reminders():
    """
    Daily task: send SMS reminders for active leases expiring within
    a configurable number of days (default 14).
    Also alerts for leases that expired in the last 7 days.

    Settings are read per owner, so each landlord's leases use only their
    own configuration and message templates.

    The schedule time (hour/minute) is configured via NotificationSetting
    in the UI, but the Celery Beat schedule in settings.py determines when
    this task actually runs.
    """
    import logging
    from datetime import timedelta
    logger = logging.getLogger(__name__)
    today = timezone.now().date()
    seven_days_ago = today - timedelta(days=7)

    sent = 0
    for owner, ns in _iter_owner_settings():
        if not ns.lease_expiry_enabled:
            continue

        target_date = today + timedelta(days=ns.lease_expiry_days_before)

        # Leases expiring within the configurable window (still active)
        expiring_soon = _scope_leases_to_owner(
            Lease.objects.filter(
                status="active",
                end_date__gte=today,
                end_date__lte=target_date,
            ),
            owner,
        ).select_related("tenant", "unit__block__property")

        # Leases that expired in the last 7 days (but may still be marked active)
        recently_expired = _scope_leases_to_owner(
            Lease.objects.filter(
                status="active",
                end_date__gte=seven_days_ago,
                end_date__lt=today,
            ),
            owner,
        ).select_related("tenant", "unit__block__property")

        template = ns.lease_expiry_message_template or DEFAULT_LEASE_TEMPLATE

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
                logger.error("Lease expiry alert failed for %s: %s", tenant, exc)

    return f"Sent {sent} lease expiry reminder(s)"
