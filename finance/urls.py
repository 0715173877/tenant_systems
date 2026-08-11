from django.urls import path
from . import views

app_name = "finance"

urlpatterns = [
    # ── API ──
    path("api/stock-items/", views.StockItemsByPropertyAPI.as_view(), name="api_stock_items_by_property"),


    # ── Expenses ──
    path("expenses/", views.ExpenseListView.as_view(), name="expense_list"),
    path("expenses/create/", views.ExpenseCreateView.as_view(), name="expense_create"),
    path("expenses/<int:pk>/", views.ExpenseDetailView.as_view(), name="expense_detail"),
    path("expenses/<int:pk>/edit/", views.ExpenseUpdateView.as_view(), name="expense_edit"),
    path("expenses/<int:pk>/delete/", views.ExpenseDeleteView.as_view(), name="expense_delete"),

    # ── Purchases ──
    path("purchases/", views.PurchaseListView.as_view(), name="purchase_list"),
    path("purchases/create/", views.PurchaseCreateView.as_view(), name="purchase_create"),
    path("purchases/<int:pk>/", views.PurchaseDetailView.as_view(), name="purchase_detail"),
    path("purchases/<int:pk>/edit/", views.PurchaseUpdateView.as_view(), name="purchase_edit"),
    path("purchases/<int:pk>/delete/", views.PurchaseDeleteView.as_view(), name="purchase_delete"),

    # ── Stock ──
    path("stock/", views.StockItemListView.as_view(), name="stock_list"),
    path("stock/create/", views.StockItemCreateView.as_view(), name="stock_create"),
    path("stock/<int:pk>/", views.StockItemDetailView.as_view(), name="stock_detail"),
    path("stock/<int:pk>/edit/", views.StockItemUpdateView.as_view(), name="stock_edit"),
    path("stock/<int:pk>/delete/", views.StockItemDeleteView.as_view(), name="stock_delete"),
    path("stock/<int:pk>/adjust/", views.StockItemAdjustView.as_view(), name="stock_adjust"),
    path("stock/out/", views.StockOutView.as_view(), name="stock_out"),
    path("stock/movements/", views.StockMovementView.as_view(), name="stock_movements"),
    path("stock/movements/in/", views.StockMovementInView.as_view(), name="stock_movement_in"),
    path("stock/movements/out/", views.StockMovementOutView.as_view(), name="stock_movement_out"),

    # ── Report ──
    path("report/", views.FinanceReportView.as_view(), name="report"),
]
