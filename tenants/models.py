from django.db import models
from django.core.validators import RegexValidator
from properties.models import Unit, Property
from decimal import Decimal
from datetime import date


class Tenant(models.Model):
    """A long-term tenant leasing a unit."""

    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="tenants",
        null=True, blank=True,
    )
    full_name = models.CharField(max_length=200)
    phone_number = models.CharField(
        max_length=15,
        validators=[
            RegexValidator(
                regex=r"^\+?[1-9]\d{8,14}$",
                message="Enter a valid phone number (e.g. +255712345678).",
            )
        ],
    )
    email = models.EmailField(blank=True)
    id_number = models.CharField(
        max_length=30, blank=True, help_text="National ID or passport number"
    )
    emergency_contact = models.CharField(max_length=100, blank=True)
    emergency_phone = models.CharField(max_length=15, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class Lease(models.Model):
    """A lease agreement between tenant(s) and the landlord for a unit."""

    STATUS_CHOICES = [
        ("active", "Active"),
        ("expired", "Expired"),
        ("terminated", "Terminated"),
    ]

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="leases"
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        related_name="leases",
        limit_choices_to={"rental_type": "long_term"},
    )
    start_date = models.DateField()
    end_date = models.DateField()
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    deposit_paid = models.BooleanField(default=False)
    deposit_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="active"
    )
    file = models.FileField(
        upload_to="leases/", blank=True, help_text="Upload signed lease PDF"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.tenant} – {self.unit} ({self.start_date} to {self.end_date})"

    @property
    def duration_months(self) -> int:
        """Calculate the full number of months covered by this lease."""
        if not self.start_date or not self.end_date:
            return 0
        months = (self.end_date.year - self.start_date.year) * 12
        months += self.end_date.month - self.start_date.month
        if self.end_date.day < self.start_date.day:
            months -= 1
        return max(months, 0)

    @property
    def total_rent(self) -> Decimal:
        """Calculate total rent = monthly_rent × duration_months."""
        return self.monthly_rent * Decimal(str(self.duration_months))


class RentInvoiceQuerySet(models.QuerySet):
    """Convenience queryset helpers for arrears / aging reporting."""

    def unpaid(self):
        """Invoices that still have an outstanding balance."""
        return self.filter(amount_paid__lt=models.F("amount"))

    def overdue(self, as_of=None):
        """Unpaid invoices whose due date has already passed."""
        as_of = as_of or date.today()
        return self.unpaid().filter(due_date__lt=as_of)


class RentInvoice(models.Model):
    """A monthly rent invoice raised against a lease, used for arrears tracking.

    The paid amount is tracked manually (or incremented when a ``Payment`` is
    recorded against the invoice) so the outstanding balance and aging can be
    derived without touching the payments ledger.
    """

    AGING_BUCKETS = [
        ("current", "Current (not yet due)"),
        ("1-30", "1–30 days"),
        ("31-60", "31–60 days"),
        ("61-90", "61–90 days"),
        ("90+", "90+ days"),
    ]

    STATUS_LABELS = {
        "paid": "Paid",
        "overdue": "Overdue",
        "partial": "Partially paid",
        "unpaid": "Unpaid",
    }

    lease = models.ForeignKey(
        Lease, on_delete=models.CASCADE, related_name="invoices"
    )
    period_start = models.DateField(help_text="First day of the billing period")
    period_end = models.DateField(help_text="Last day of the billing period")
    due_date = models.DateField(help_text="Date the rent is due")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RentInvoiceQuerySet.as_manager()

    class Meta:
        ordering = ["-period_start", "lease__tenant__full_name"]
        unique_together = ["lease", "period_start"]

    def __str__(self):
        return f"{self.period_label} rent – {self.lease.tenant.full_name}"

    @property
    def period_label(self) -> str:
        """Human label for the billing period, e.g. ``Mar 2026``."""
        return self.period_start.strftime("%b %Y")

    @property
    def balance(self) -> Decimal:
        """Outstanding amount still owed on this invoice."""
        return Decimal(self.amount) - Decimal(self.amount_paid)

    @property
    def is_paid(self) -> bool:
        return self.balance <= 0

    @property
    def days_overdue(self) -> int:
        """Whole days past the due date (0 when paid or not yet due)."""
        if self.is_paid:
            return 0
        return max((date.today() - self.due_date).days, 0)

    @property
    def is_overdue(self) -> bool:
        return (not self.is_paid) and self.due_date < date.today()

    @property
    def effective_status(self) -> str:
        """Derived status: paid > overdue > partial > unpaid."""
        if self.is_paid:
            return "paid"
        if self.is_overdue:
            return "overdue"
        if Decimal(self.amount_paid) > 0:
            return "partial"
        return "unpaid"

    @property
    def status_label(self) -> str:
        return self.STATUS_LABELS[self.effective_status]

    @property
    def aging_bucket(self) -> str:
        """Return the aging bucket key for this invoice (see ``AGING_BUCKETS``)."""
        if self.is_paid:
            return "paid"
        days = self.days_overdue
        if days <= 0:
            return "current"
        if days <= 30:
            return "1-30"
        if days <= 60:
            return "31-60"
        if days <= 90:
            return "61-90"
        return "90+"

    @property
    def aging_label(self) -> str:
        """Human label for the aging bucket (``Paid`` for settled invoices)."""
        if self.is_paid:
            return "Paid"
        return dict(self.AGING_BUCKETS)[self.aging_bucket]
