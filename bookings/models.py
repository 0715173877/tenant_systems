from django.db import models
from django.core.validators import RegexValidator, MinValueValidator
from django.core.exceptions import ValidationError
from properties.models import Unit, Property


class Guest(models.Model):
    """A short-term guest staying in a unit."""

    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="guests",
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
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class Booking(models.Model):
    """A short-term booking for a unit."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("confirmed", "Confirmed"),
        ("checked_in", "Checked In"),
        ("checked_out", "Checked Out"),
        ("cancelled", "Cancelled"),
    ]

    guest = models.ForeignKey(
        Guest, on_delete=models.CASCADE, related_name="bookings"
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        related_name="bookings",
        limit_choices_to={"rental_type": "short_term"},
    )
    check_in = models.DateField()
    check_out = models.DateField()
    number_of_guests = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)]
    )
    nightly_rate_override = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Override the unit's default nightly rate"
    )
    cleaning_fee_override = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Override the unit's default cleaning fee"
    )
    total_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    amount_paid = models.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-check_in"]

    def __str__(self):
        return (
            f"{self.guest} – {self.unit} "
            f"({self.check_in} to {self.check_out})"
        )

    def clean(self):
        if self.check_in and self.check_out and self.check_in >= self.check_out:
            raise ValidationError("Check-out must be after check-in.")
        # Prevent overlapping bookings for the same unit (only on create)
        if not self.pk and self.unit_id and self.check_in and self.check_out:
            overlapping = Booking.objects.filter(
                unit=self.unit,
                status__in=["pending", "confirmed", "checked_in"],
            ).filter(
                models.Q(check_in__lt=self.check_out)
                & models.Q(check_out__gt=self.check_in)
            )
            if overlapping.exists():
                raise ValidationError(
                    "This unit is already booked for the selected dates."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        if not self.total_amount:
            self.calculate_total()
        super().save(*args, **kwargs)

    def calculate_total(self):
        """Auto-calculate total based on nights + cleaning fee."""
        if not self.check_in or not self.check_out:
            return
        nights = (self.check_out - self.check_in).days
        if nights <= 0:
            return
        rate = (
            self.nightly_rate_override
            or self.unit.nightly_rate
            or 0
        )
        cleaning = (
            self.cleaning_fee_override
            or self.unit.cleaning_fee
            or 0
        )
        self.total_amount = (rate * nights) + cleaning
