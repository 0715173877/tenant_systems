from django.urls import path
from . import views

app_name = "bookings"

urlpatterns = [
    # Guests
    path("guests/", views.GuestListView.as_view(), name="guest_list"),
    path("guests/create/", views.GuestCreateView.as_view(), name="guest_create"),
    path("guests/<int:pk>/edit/", views.GuestUpdateView.as_view(), name="guest_edit"),
    # Bookings
    path("", views.BookingListView.as_view(), name="booking_list"),
    path("<int:pk>/", views.BookingDetailView.as_view(), name="booking_detail"),
    path("create/", views.BookingCreateView.as_view(), name="booking_create"),
    path("<int:pk>/edit/", views.BookingUpdateView.as_view(), name="booking_edit"),
    path("<int:pk>/delete/", views.BookingDeleteView.as_view(), name="booking_delete"),
    # Quick status update
    path("<int:pk>/status/", views.booking_update_status, name="booking_update_status"),
    # Quick guest creation (HTMX)
    path("quick-guest/", views.quick_create_guest, name="quick_guest"),
    # Send SMS
    path("<int:pk>/sms/", views.booking_send_sms, name="booking_send_sms"),
    # Calendar
    path("calendar/", views.BookingCalendarView.as_view(), name="calendar"),
    path("availability/", views.booking_availability, name="availability"),
]
