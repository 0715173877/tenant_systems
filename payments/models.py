from django.db import models
from django.core.validators import MinValueValidator
from tenants.models import Lease
from bookings.models import Booking


class Payment(models.Model):
    """A financial transaction – rent payment or booking settlement."""

    PAYMENT_TYPE_CHOICES = [
        ("rent", "Rent (Long-term)"),
        ("deposit", "Deposit"),
        ("booking", "Booking (Short-term)"),
        ("cleaning_fee", "Cleaning Fee"),
        ("other", "Other"),
    ]

    PAYMENT_METHOD_CHOICES = [
        ("cash", "Cash"),
        ("mpesa", "M-Pesa"),
        ("tigo_pesa", "Tigo Pesa"),
        ("airtel_money", "Airtel Money"),
        ("bank_transfer", "Bank Transfer"),
        ("card", "Card"),
        ("other", "Other"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("refunded", "Refunded"),
        ("failed", "Failed"),
    ]

    # Link to either a lease or a booking
    lease = models.ForeignKey(
        Lease,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    booking = models.ForeignKey(
        Booking,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    tenant_name = models.CharField(
        max_length=200,
        help_text="Payer name (denormalized for reporting)",
        blank=True,
    )
    payment_type = models.CharField(
        max_length=20, choices=PAYMENT_TYPE_CHOICES
    )
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES, default="cash"
    )
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0.01)]
    )
    transaction_reference = models.CharField(
        max_length=100, blank=True,
        help_text="M-Pesa / bank reference number"
    )
    payment_date = models.DateField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="completed"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-payment_date"]

    def __str__(self):
        return (
            f"{self.get_payment_type_display()} – "
            f"{self.amount} – {self.payment_date}"
        )

    @property
    def effective_currency(self):
        """Return the currency from the related lease or booking unit."""
        if self.lease and self.lease.unit:
            return self.lease.unit.effective_currency
        if self.booking and self.booking.unit:
            return self.booking.unit.effective_currency
        return None

    def save(self, *args, **kwargs):
        if not self.tenant_name:
            if self.lease:
                self.tenant_name = self.lease.tenant.full_name
            elif self.booking:
                self.tenant_name = self.booking.guest.full_name
        super().save(*args, **kwargs)
