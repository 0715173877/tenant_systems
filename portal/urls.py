from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.PortalDashboardView.as_view(), name="dashboard"),
    # Lease
    path("leases/", views.PortalLeaseListView.as_view(), name="leases"),
    path("leases/<int:pk>/", views.PortalLeaseDetailView.as_view(), name="lease_detail"),
    path("leases/<int:pk>/pdf/", views.PortalLeasePDFView.as_view(), name="lease_pdf"),
    # Rent invoices
    path("invoices/", views.PortalInvoiceListView.as_view(), name="invoices"),
    path("invoices/<int:pk>/", views.PortalInvoiceDetailView.as_view(), name="invoice_detail"),
    # Payments
    path("payments/", views.PortalPaymentListView.as_view(), name="payments"),
    # Maintenance
    path("maintenance/", views.PortalMaintenanceListView.as_view(), name="maintenance"),
    path("maintenance/new/", views.PortalMaintenanceCreateView.as_view(), name="maintenance_create"),
    # How to pay + profile
    path("how-to-pay/", views.PortalPaymentInstructionsView.as_view(), name="payment_instructions"),
    path("profile/", views.PortalProfileView.as_view(), name="profile"),
]
