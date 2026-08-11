from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from decimal import Decimal
from builtins import property as _property


class ExpenseCategory(models.Model):
    """Category / type of expense (e.g. Utilities, Salaries, Maintenance, etc.)."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Expense Categories"

    def __str__(self):
        return self.name


class Expense(models.Model):
    """A single expense transaction."""

    EXPENSE_TYPES = [
        ("utilities", "Utilities (Water, Electricity, Gas)"),
        ("salaries", "Salaries & Wages"),
        ("maintenance", "Maintenance & Repairs"),
        ("supplies", "Office & Cleaning Supplies"),
        ("taxes", "Taxes & Licenses"),
        ("insurance", "Insurance"),
        ("marketing", "Marketing & Advertising"),
        ("security", "Security"),
        ("transport", "Transport & Fuel"),
        ("food", "Food & Catering"),
        ("furniture", "Furniture & Equipment"),
        ("renovation", "Renovation & Improvement"),
        ("legal", "Legal & Professional Fees"),
        ("internet", "Internet & Communication"),
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

    property = models.ForeignKey(
        "properties.Property", on_delete=models.CASCADE,
        related_name="expenses",
        help_text="Property this expense belongs to",
    )
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="expenses",
    )
    expense_type = models.CharField(
        max_length=20, choices=EXPENSE_TYPES, default="other",
        help_text="Type of expense",
    )
    description = models.TextField(help_text="What was this expense for?")
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0.01)],
    )
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES, default="cash",
    )
    transaction_reference = models.CharField(
        max_length=100, blank=True,
        help_text="Receipt/invoice/reference number",
    )
    expense_date = models.DateField()
    vendor = models.CharField(
        max_length=200, blank=True,
        help_text="Vendor/supplier/payee name",
    )
    receipt_image = models.ImageField(
        upload_to="expense_receipts/", blank=True,
        help_text="Upload receipt or invoice image",
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="created_expenses",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-expense_date"]
        verbose_name = "Expense"
        verbose_name_plural = "Expenses"

    def __str__(self):
        return f"{self.get_expense_type_display()} – {self.amount} on {self.expense_date}"

    @_property
    def effective_currency(self):
        return self.property.currency if self.property else "TZS"


class Purchase(models.Model):
    """Record of a purchase / asset acquisition for the property."""

    property = models.ForeignKey(
        "properties.Property", on_delete=models.CASCADE,
        related_name="purchases",
    )
    item_name = models.CharField(max_length=200, help_text="Name of the purchased item")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2)
    supplier = models.CharField(max_length=200, blank=True, help_text="Supplier/vendor name")
    purchase_date = models.DateField()
    receipt_number = models.CharField(max_length=100, blank=True)
    receipt_image = models.ImageField(upload_to="purchase_receipts/", blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="created_purchases",
    )
    stock_item = models.ForeignKey(
        "StockItem", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="purchases",
        help_text="Link this purchase to a stock item to auto-update inventory",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-purchase_date"]
        verbose_name = "Purchase"
        verbose_name_plural = "Purchases"

    def __str__(self):
        return f"{self.item_name} x{self.quantity} – {self.total_cost}"

    def save(self, *args, **kwargs):
        self.total_cost = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    @_property
    def effective_currency(self):
        return self.property.currency if self.property else "TZS"


class StockItem(models.Model):
    """An inventory item tracked for stock management."""

    UNIT_CHOICES = [
        ("pcs", "Pieces"),
        ("packs", "Packs"),
        ("bottles", "Bottles"),
        ("liters", "Liters"),
        ("kg", "Kilograms"),
        ("grams", "Grams"),
        ("boxes", "Boxes"),
        ("rolls", "Rolls"),
        ("bags", "Bags"),
        ("units", "Units"),
        ("other", "Other"),
    ]

    property = models.ForeignKey(
        "properties.Property", on_delete=models.CASCADE,
        related_name="stock_items",
    )
    item_name = models.CharField(max_length=200, verbose_name="Item Name")
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default="pcs")
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0"),
        verbose_name="Quantity",
        help_text="Current stock on hand",
    )
    low_stock_threshold = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("5"),
        verbose_name="Low Stock Threshold",
        help_text="Minimum quantity before low stock alert",
    )
    unit_cost = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0"),
        verbose_name="Unit Cost",
        help_text="Cost per unit",
    )
    location = models.CharField(
        max_length=200, blank=True,
        help_text="Storage location (e.g., Room 12, Store A)",
    )
    supplier = models.CharField(
        max_length=200, blank=True,
        help_text="Preferred supplier for this item",
    )
    expiry_date = models.DateField(
        null=True, blank=True,
        help_text="Expiry date (if applicable, e.g. food, cleaning supplies)",
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["item_name"]
        unique_together = ["property", "item_name"]

    def __str__(self):
        return f"{self.item_name} ({self.quantity} {self.unit})"

    @_property
    def total_value(self):
        """Total value of current stock."""
        return self.quantity * self.unit_cost

    @_property
    def needs_reorder(self):
        return self.is_active and self.low_stock_threshold > 0 and self.quantity <= self.low_stock_threshold


class StockMovement(models.Model):
    """Record of stock in/out movement."""

    MOVEMENT_TYPES = [
        ("in", "Stock In"),
        ("out", "Stock Out"),
    ]

    stock_item = models.ForeignKey(
        StockItem, on_delete=models.CASCADE,
        related_name="movements",
    )
    movement_type = models.CharField(max_length=10, choices=MOVEMENT_TYPES)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Unit price at time of movement",
    )
    total_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reference = models.CharField(
        max_length=200, blank=True,
        help_text="Reference (e.g. purchase order, usage note)",
    )
    notes = models.TextField(blank=True, help_text="Reason for stock movement")
    moved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="stock_movements",
    )
    moved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-moved_at"]
        verbose_name = "Stock Movement"
        verbose_name_plural = "Stock Movements"

    def __str__(self):
        arrow = "→ IN" if self.movement_type == "in" else "→ OUT"
        return f"{self.stock_item.item_name} {arrow} {self.quantity} {self.stock_item.unit}"

    def save(self, *args, **kwargs):
        self.total_value = self.quantity * self.unit_price
        if not self.pk:
            # Update stock quantity on first save
            item = self.stock_item
            if self.movement_type == "in":
                item.quantity += self.quantity
            else:
                item.quantity -= self.quantity
            item.save(update_fields=["quantity"])
        super().save(*args, **kwargs)
