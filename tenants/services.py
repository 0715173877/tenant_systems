"""Business logic for generating rent invoices (shared by the management
command and the "Generate invoices" button on the Rent & Arrears page)."""
from calendar import monthrange
from datetime import date

from dateutil.relativedelta import relativedelta

from .models import Lease, RentInvoice


def month_bounds(period):
    """Return ``(first_day, last_day)`` for the calendar month containing ``period``."""
    period = period.replace(day=1)
    last_day = monthrange(period.year, period.month)[1]
    return period, period.replace(day=last_day)


def generate_rent_invoices(period_start, leases=None, due_day=5, dry_run=False):
    """Generate one :class:`~tenants.models.RentInvoice` per active lease per month.

    ``period_start`` may be any date inside the target month; it is normalised
    to the first day. Idempotent: an invoice that already exists for a
    ``(lease, period_start)`` pair is skipped, never duplicated.

    ``leases`` may be a queryset/list to restrict generation (e.g. only the
    properties a user can access); it defaults to all *active* leases.

    Returns ``(created, skipped)`` counts. With ``dry_run=True`` nothing is
    written to the database.
    """
    period_start, period_end = month_bounds(period_start)
    due = period_start.replace(day=min(due_day, period_end.day))

    if leases is None:
        leases = Lease.objects.filter(status="active")

    created = skipped = 0
    for lease in leases:
        # Skip leases that do not overlap the billing month.
        if lease.start_date > period_end or lease.end_date < period_start:
            continue
        if dry_run:
            if RentInvoice.objects.filter(
                lease=lease, period_start=period_start
            ).exists():
                skipped += 1
            else:
                created += 1
            continue
        _, was_created = RentInvoice.objects.get_or_create(
            lease=lease,
            period_start=period_start,
            defaults={
                "period_end": period_end,
                "due_date": due,
                "amount": lease.monthly_rent,
            },
        )
        if was_created:
            created += 1
        else:
            skipped += 1
    return created, skipped


def iter_months(start, end):
    """Yield the first day of each calendar month from ``start`` through ``end``."""
    current = start.replace(day=1)
    last = end.replace(day=1)
    while current <= last:
        yield current
        current = current + relativedelta(months=1)
