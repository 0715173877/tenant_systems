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
