"""Business logic for generating rent invoices (shared by the management
command, the "Generate invoices" button on the Rent & Arrears page and the
automatic payment captured when a lease is created or renewed)."""
from calendar import monthrange
from datetime import date
from decimal import Decimal

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


def record_initial_payments(lease, amount, payment_method="cash", payment_date=None):
    """Book the opening rent payment for a freshly created (or renewed) lease.

    The invoice covering the lease's start month is created when it does not
    exist yet, so the payment is reflected on the Rent & Arrears page instead
    of leaving the period un-billed. When the lease is flagged ``deposit_paid``
    a second payment of type *deposit* is recorded as well.

    Returns ``(payments, invoice)`` where ``payments`` is the list of created
    :class:`~payments.models.Payment` rows (rent first, then the deposit).
    """
    # Imported lazily: ``payments.models`` imports this app's models.
    from payments.models import Payment

    amount = Decimal(str(amount))
    payment_date = payment_date or lease.start_date
    payment_method = payment_method or "cash"

    period_start, period_end = month_bounds(lease.start_date)
    invoice, _ = RentInvoice.objects.get_or_create(
        lease=lease,
        period_start=period_start,
        defaults={
            "period_end": period_end,
            "due_date": period_start.replace(day=min(5, period_end.day)),
            "amount": lease.monthly_rent,
        },
    )

    payments = [
        Payment.objects.create(
            lease=lease,
            payment_type="rent",
            payment_method=payment_method,
            amount=amount,
            payment_date=payment_date,
            status="completed",
            notes=f"Initial rent payment for {invoice.period_label}",
        )
    ]
    invoice.amount_paid = Decimal(invoice.amount_paid) + amount
    invoice.save(update_fields=["amount_paid", "updated_at"])

    if lease.deposit_paid and lease.deposit_amount and lease.deposit_amount > 0:
        payments.append(
            Payment.objects.create(
                lease=lease,
                payment_type="deposit",
                payment_method=payment_method,
                amount=lease.deposit_amount,
                payment_date=payment_date,
                status="completed",
                notes="Security deposit",
            )
        )

    return payments, invoice


def iter_months(start, end):
    """Yield the first day of each calendar month from ``start`` through ``end``."""
    current = start.replace(day=1)
    last = end.replace(day=1)
    while current <= last:
        yield current
        current = current + relativedelta(months=1)
