from django.contrib import admin
from .models import ExpenseCategory, Expense, Purchase, StockItem, StockMovement


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active"]
    search_fields = ["name"]


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ["expense_type", "amount", "expense_date", "property", "vendor", "payment_method"]
    list_filter = ["expense_type", "payment_method", "property", "expense_date"]
    search_fields = ["description", "vendor", "transaction_reference"]
    date_hierarchy = "expense_date"


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ["item_name", "quantity", "total_cost", "purchase_date", "property"]
    list_filter = ["property", "purchase_date"]
    search_fields = ["item_name", "supplier", "receipt_number"]
    date_hierarchy = "purchase_date"


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ["item_name", "quantity", "unit", "low_stock_threshold", "needs_reorder", "property"]
    list_filter = ["is_active", "property"]
    search_fields = ["item_name"]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ["stock_item", "movement_type", "quantity", "total_value", "moved_at", "reference"]
    list_filter = ["movement_type", "moved_at"]
    search_fields = ["stock_item__item_name", "reference", "notes"]
