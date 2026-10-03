from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from config.test_factories import TwoLandlordFixtureMixin
from tenants.models import Tenant, Lease
from .models import Payment


class PaymentFactoryMixin(TwoLandlordFixtureMixin):
    def setUp(self):
        super().setUp()
        self.tenant_a = Tenant.objects.create(
            property=self.property_a, full_name="Tenant A", phone_number="+255712000001"
        )
        self.tenant_b = Tenant.objects.create(
            property=self.property_b, full_name="Tenant B", phone_number="+255712000002"
        )
        self.lease_a = Lease.objects.create(
            tenant=self.tenant_a, unit=self.long_unit_a,
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            monthly_rent="500000.00", status="active",
        )
        self.lease_b = Lease.objects.create(
            tenant=self.tenant_b, unit=self.long_unit_b,
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            monthly_rent="500000.00", status="active",
        )
        self.payment_a = Payment.objects.create(
            lease=self.lease_a, payment_type="rent", payment_method="cash",
            amount=Decimal("500000.00"), payment_date=date(2026, 2, 1), status="completed",
        )
        self.payment_b = Payment.objects.create(
            lease=self.lease_b, payment_type="rent", payment_method="cash",
            amount=Decimal("500000.00"), payment_date=date(2026, 2, 1), status="completed",
        )


class PaymentIsolationTests(PaymentFactoryMixin, TestCase):
    def test_payment_list_is_scoped(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("payments:payment_list"))
        payments = list(response.context["payments"])
        self.assertIn(self.payment_a, payments)
        self.assertNotIn(self.payment_b, payments)

    def test_payment_detail_other_owner_404(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("payments:payment_detail", args=[self.payment_b.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_payment_report_totals_are_scoped(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("payments:report"),
            {"start_date": "2026-01-01", "end_date": "2026-12-31"},
        )
        self.assertEqual(response.status_code, 200)
        # Only owner A's single payment should be counted.
        self.assertEqual(Decimal(response.context["total_revenue"]), Decimal("500000.00"))

    def test_payment_create_form_choices_scoped(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("payments:payment_create"))
        form = response.context["form"]
        self.assertIn(self.lease_a, form.fields["lease"].queryset)
        self.assertNotIn(self.lease_b, form.fields["lease"].queryset)
