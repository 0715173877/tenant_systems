from datetime import date

from django.test import TestCase
from django.urls import reverse

from config.test_factories import TwoLandlordFixtureMixin
from .models import Guest, Booking


class BookingFactoryMixin(TwoLandlordFixtureMixin):
    def setUp(self):
        super().setUp()
        self.guest_a = Guest.objects.create(
            property=self.property_a, full_name="Guest A", phone_number="+255713000001"
        )
        self.guest_b = Guest.objects.create(
            property=self.property_b, full_name="Guest B", phone_number="+255713000002"
        )
        self.booking_a = Booking.objects.create(
            guest=self.guest_a,
            unit=self.short_unit_a,
            check_in=date(2026, 6, 1),
            check_out=date(2026, 6, 5),
            total_amount="200000.00",
            status="confirmed",
        )
        self.booking_b = Booking.objects.create(
            guest=self.guest_b,
            unit=self.short_unit_b,
            check_in=date(2026, 6, 1),
            check_out=date(2026, 6, 5),
            total_amount="200000.00",
            status="confirmed",
        )


class BookingIsolationTests(BookingFactoryMixin, TestCase):
    def test_guest_list_is_scoped(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("bookings:guest_list"))
        guests = list(response.context["guests"])
        self.assertIn(self.guest_a, guests)
        self.assertNotIn(self.guest_b, guests)

    def test_booking_list_is_scoped(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("bookings:booking_list"))
        bookings = list(response.context["bookings"])
        self.assertIn(self.booking_a, bookings)
        self.assertNotIn(self.booking_b, bookings)

    def test_booking_detail_other_owner_404(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("bookings:booking_detail", args=[self.booking_b.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_booking_create_form_unit_choices_scoped(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("bookings:booking_create"))
        form = response.context["form"]
        self.assertIn(self.short_unit_a, form.fields["unit"].queryset)
        self.assertNotIn(self.short_unit_b, form.fields["unit"].queryset)
        self.assertIn(self.guest_a, form.fields["guest"].queryset)
        self.assertNotIn(self.guest_b, form.fields["guest"].queryset)
