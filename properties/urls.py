from django.urls import path
from . import views

app_name = "properties"

urlpatterns = [
    # Properties
    path("", views.PropertyListView.as_view(), name="property_list"),
    path("property/new/", views.PropertyCreateView.as_view(), name="property_create"),
    path("property/<slug:slug>/", views.PropertyDetailView.as_view(), name="property_detail"),
    path("property/<slug:slug>/edit/", views.PropertyUpdateView.as_view(), name="property_update"),
    path("property/<slug:slug>/delete/", views.PropertyDeleteView.as_view(), name="property_delete"),
    # Blocks
    path("blocks/", views.BlockListView.as_view(), name="block_list"),
    path("blocks/new/", views.BlockCreateView.as_view(), name="block_create"),
    path("blocks/<int:pk>/", views.BlockDetailView.as_view(), name="block_detail"),
    path("blocks/<int:pk>/edit/", views.BlockUpdateView.as_view(), name="block_update"),
    path("blocks/<int:pk>/delete/", views.BlockDeleteView.as_view(), name="block_delete"),
    # Units
    path("units/", views.UnitListView.as_view(), name="unit_list"),
    path("units/new/", views.UnitCreateView.as_view(), name="unit_create"),
    path("units/<int:pk>/", views.UnitDetailView.as_view(), name="unit_detail"),
    path("units/<int:pk>/edit/", views.UnitUpdateView.as_view(), name="unit_update"),
    path("units/<int:pk>/delete/", views.UnitDeleteView.as_view(), name="unit_delete"),
    # Staff
    path("staff/", views.StaffListView.as_view(), name="staff_list"),
    path("staff/new/", views.StaffCreateView.as_view(), name="staff_create"),
    path("staff/<int:pk>/edit/", views.StaffUpdateView.as_view(), name="staff_update"),
    path("staff/<int:pk>/toggle/", views.StaffToggleActiveView.as_view(), name="staff_toggle"),
    path("staff/<int:pk>/delete/", views.StaffDeleteView.as_view(), name="staff_delete"),
    # Maintenance Requests
    path("maintenance/", views.MaintenanceRequestListView.as_view(), name="maintenance_list"),
    path("maintenance/new/", views.MaintenanceRequestCreateView.as_view(), name="maintenance_create"),
    path("maintenance/<int:pk>/", views.MaintenanceRequestDetailView.as_view(), name="maintenance_detail"),
    path("maintenance/<int:pk>/edit/", views.MaintenanceRequestUpdateView.as_view(), name="maintenance_update"),
    path("maintenance/<int:pk>/delete/", views.MaintenanceRequestDeleteView.as_view(), name="maintenance_delete"),
    # Owner Profile
    path("owner/profile/", views.OwnerProfileView.as_view(), name="owner_profile"),
    path("owner/profile/edit/", views.OwnerProfileUpdateView.as_view(), name="owner_profile_edit"),
]
