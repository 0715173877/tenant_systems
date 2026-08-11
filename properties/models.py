from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal


class Property(models.Model):
    """A top-level property/estate owned by an owner."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="properties",
        limit_choices_to={"groups__name": "owner"},
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    location = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="property_images/", blank=True,
                               help_text="Cover/featured image for the property")
    logo = models.ImageField(upload_to="property_logos/", blank=True)
    currency = models.CharField(
        max_length=3, choices=[("TZS", "TZS (Tanzanian Shilling)"), ("USD", "USD (US Dollar)")],
        default="TZS",
        help_text="Default currency for rent and deposits (used in SMS templates as {currency})"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Properties"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base = slugify(self.name)
            slug = base
            counter = 1
            while Property.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def total_blocks(self):
        return self.blocks.count()

    @property
    def total_units(self):
        return Unit.objects.filter(block__property=self).count()


class Block(models.Model):
    """A building block within a property."""

    BUILDING_TYPE_CHOICES = [
        ("apartment", "Apartment Building"),
        ("villa", "Villa"),
        ("cottage", "Cottage"),
        ("bungalow", "Bungalow"),
        ("commercial", "Commercial"),
        ("mixed", "Mixed Use"),
        ("other", "Other"),
    ]

    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="blocks"
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=300, blank=True,
                                 help_text="Specific location within the property")
    building_type = models.CharField(
        max_length=20, choices=BUILDING_TYPE_CHOICES, blank=True,
        help_text="Type of building"
    )
    image = models.ImageField(upload_to="block_images/", blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "name"]
        unique_together = ["property", "name"]

    def __str__(self):
        return f"{self.property.name} – {self.name}"


class UnitAmenity(models.Model):
    """Amenities available in a unit."""

    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=50, blank=True,
                            help_text="Bootstrap icon class (e.g., bi-wifi)")

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Unit Amenities"


class Unit(models.Model):
    """An individual rental unit within a block."""

    UNIT_TYPE_CHOICES = [
        ("studio", "Studio"),
        ("one_bedroom", "One Bedroom"),
        ("two_bedroom", "Two Bedroom"),
        ("three_bedroom", "Three Bedroom"),
    ]

    RENTAL_TYPE_CHOICES = [
        ("long_term", "Long-term (Lease)"),
        ("short_term", "Short-term (Booking)"),
    ]

    STATUS_CHOICES = [
        ("available", "Available"),
        ("occupied", "Occupied"),
        ("maintenance", "Under Maintenance"),
        ("unavailable", "Unavailable"),
    ]

    block = models.ForeignKey(
        Block, on_delete=models.CASCADE, related_name="units"
    )
    unit_number = models.CharField(max_length=10)
    rental_type = models.CharField(
        max_length=20, choices=RENTAL_TYPE_CHOICES
    )
    unit_type = models.CharField(
        max_length=20, choices=UNIT_TYPE_CHOICES, default="studio"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="available"
    )
    description = models.TextField(blank=True,
                                   help_text="Description of the unit")
    image = models.ImageField(upload_to="unit_images/", blank=True)
    amenities = models.ManyToManyField(
        UnitAmenity, blank=True, related_name="units"
    )
    square_feet = models.PositiveIntegerField(
        null=True, blank=True, help_text="Square footage of the unit"
    )
    bedrooms = models.PositiveIntegerField(default=1)
    bathrooms = models.PositiveIntegerField(default=1)
    # Long-term fields
    monthly_rent = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    deposit_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    # Short-term fields
    nightly_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    weekly_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    cleaning_fee = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00")
    )
    max_guests = models.PositiveIntegerField(
        default=2, validators=[MinValueValidator(1), MaxValueValidator(20)]
    )

    currency = models.CharField(
        max_length=3,
        choices=[("", "--------- (Use Property Currency)"), ("TZS", "TZS (Tanzanian Shilling)"), ("USD", "USD (US Dollar)")],
        blank=True, default="",
        help_text="Currency for this unit. Leave blank to inherit from the parent property."
    )
    is_available = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["block", "unit_number"]
        unique_together = ["block", "unit_number"]

    def __str__(self):
        return f"{self.block.name} – Unit {self.unit_number} ({self.get_rental_type_display()})"

    @property
    def effective_currency(self):
        """Return the unit's currency if set, otherwise fall back to the parent property's currency."""
        if self.currency:
            return self.currency
        return self.block.property.currency


class PropertyStaff(models.Model):
    """Maps a user to a property with a specific staff role."""

    STAFF_ROLES = [
        ("manager", "Manager"),
        ("receptionist", "Receptionist"),
        ("accountant", "Accountant"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_assignments",
    )
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="staff"
    )
    role = models.CharField(max_length=20, choices=STAFF_ROLES)
    mobile = models.CharField(max_length=20, blank=True, help_text="Staff mobile/phone number")
    is_active = models.BooleanField(default=True)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__username", "property"]
        verbose_name_plural = "Property Staff"

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} – {self.get_role_display()} @ {self.property.name}"


class MaintenanceRequest(models.Model):
    """A maintenance or repair request for a unit."""

    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("urgent", "Urgent"),
    ]

    STATUS_CHOICES = [
        ("reported", "Reported"),
        ("assigned", "Assigned"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="maintenance_requests"
    )
    unit = models.ForeignKey(
        Unit, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="maintenance_requests"
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default="medium"
    )
    status = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default="reported"
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="reported_maintenance",
        help_text="Staff or tenant who reported the issue"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="assigned_maintenance",
        help_text="Staff member assigned to fix the issue"
    )
    notes = models.TextField(blank=True, help_text="Internal notes / work log")
    resolution_notes = models.TextField(
        blank=True, help_text="How the issue was resolved"
    )
    cost = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Cost of repair / parts"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-priority", "-created_at"]
        verbose_name = "Maintenance Request"
        verbose_name_plural = "Maintenance Requests"

    def __str__(self):
        return f"{self.title} ({self.get_status_display()}) – {self.property.name}"

    def save(self, *args, **kwargs):
        # Auto-set completed_at when status changes to completed
        if self.status == "completed" and not self.completed_at:
            from django.utils import timezone
            self.completed_at = timezone.now()
        elif self.status != "completed":
            self.completed_at = None
        super().save(*args, **kwargs)


class OwnerProfile(models.Model):
    """Profile for the property owner with payment account details visible to tenants & guests."""

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owner_profile",
        limit_choices_to={"groups__name": "owner"},
    )
    phone = models.CharField(max_length=20, blank=True, help_text="Owner contact phone number")
    email = models.EmailField(blank=True, help_text="Owner contact email")

    # --- Bank Account ---
    bank_name = models.CharField(max_length=200, blank=True, help_text="e.g. CRDB Bank, NMB, NBC")
    bank_account_name = models.CharField(max_length=200, blank=True, help_text="Account holder name")
    bank_account_number = models.CharField(max_length=100, blank=True)
    bank_branch = models.CharField(max_length=200, blank=True)
    bank_currency = models.CharField(max_length=10, default="TZS", blank=True)

    # --- Mobile Money / Lipa na M-Pesa ---
    mpesa_number = models.CharField(max_length=20, blank=True, help_text="M-Pesa paybill/till number or phone")
    mpesa_account_name = models.CharField(max_length=200, blank=True, help_text="Business name / account name for M-Pesa")
    tigo_pesa_number = models.CharField(max_length=20, blank=True)
    airtel_money_number = models.CharField(max_length=20, blank=True)

    # --- Other / Notes ---
    payment_instructions = models.TextField(
        blank=True,
        help_text="Extra payment instructions shown to tenants & guests (e.g. 'Please use lease number as reference')"
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Owner Profile"
        verbose_name_plural = "Owner Profiles"

    def __str__(self):
        return f"Owner Profile – {self.owner.get_full_name() or self.owner.username}"

    @property
    def has_bank_account(self):
        return bool(self.bank_name and self.bank_account_number)

    @property
    def has_mobile_money(self):
        return bool(self.mpesa_number or self.tigo_pesa_number or self.airtel_money_number)
