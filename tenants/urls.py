from django.urls import path
from . import views

app_name = "tenants"

urlpatterns = [
    path("", views.TenantListView.as_view(), name="tenant_list"),
    path("<int:pk>/", views.TenantDetailView.as_view(), name="tenant_detail"),
    path("create/", views.TenantCreateView.as_view(), name="tenant_create"),
    path("<int:pk>/edit/", views.TenantUpdateView.as_view(), name="tenant_edit"),
    path("<int:pk>/delete/", views.TenantDeleteView.as_view(), name="tenant_delete"),
    path("<int:pk>/send-sms/", views.tenant_send_sms, name="tenant_send_sms"),
    # Leases
    path("leases/", views.LeaseListView.as_view(), name="lease_list"),
    path("leases/<int:pk>/", views.LeaseDetailView.as_view(), name="lease_detail"),
    path("leases/create/", views.LeaseCreateView.as_view(), name="lease_create"),
    path("leases/<int:pk>/edit/", views.LeaseUpdateView.as_view(), name="lease_edit"),
    path("leases/<int:pk>/delete/", views.LeaseDeleteView.as_view(), name="lease_delete"),
    path("leases/<int:pk>/send-reminder/", views.lease_send_reminder, name="lease_send_reminder"),
    path("leases/<int:pk>/send-sms/", views.lease_send_sms, name="lease_send_sms"),
    path("leases/<int:pk>/send-expiry-reminder/", views.lease_send_expiry_reminder, name="lease_send_expiry_reminder"),
    path("leases/<int:pk>/pdf/", views.lease_download_pdf, name="lease_download_pdf"),
]

