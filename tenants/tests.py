from datetime import date

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from config.test_factories import TwoLandlordFixtureMixin
from payments.models import Payment
from .models import Tenant, Lease, RentInvoice
from .services import generate_rent_invoices


class TenantModelFactoryMixin(TwoLandlordFixtureMixin):
    def setUp(self):
        super().setUp()
        self.tenant_a = Tenant.objects.create(
            property=self.property_a, full_name="Tenant A", phone_number="+255712000001"
        )
        self.tenant_b = Tenant.objects.create(
            property=self.property_b, full_name="Tenant B", phone_number="+255712000002"
        )
        self.lease_a = Lease.objects.create(
            tenant=self.tenant_a,
            unit=self.long_unit_a,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            monthly_rent="500000.00",
            status="active",
        )
        self.lease_b = Lease.objects.create(
            tenant=self.tenant_b,
            unit=self.long_unit_b,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            monthly_rent="500000.00",
            status="active",
        )


class TenantIsolationTests(TenantModelFactoryMixin, TestCase):
    def test_tenant_list_is_scoped(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("tenants:tenant_list"))
        tenants = list(response.context["tenants"])
        self.assertIn(self.tenant_a, tenants)
        self.assertNotIn(self.tenant_b, tenants)

    def test_tenant_detail_other_owner_404(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("tenants:tenant_detail", args=[self.tenant_b.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_lease_list_is_scoped(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("tenants:lease_list"))
        leases = list(response.context["leases"])
        self.assertIn(self.lease_a, leases)
        self.assertNotIn(self.lease_b, leases)

    def test_lease_detail_other_owner_404(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("tenants:lease_detail", args=[self.lease_b.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_lease_create_form_excludes_other_owner_choices(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("tenants:lease_create"))
        form = response.context["form"]
        self.assertIn(self.tenant_a, form.fields["tenant"].queryset)
        self.assertNotIn(self.tenant_b, form.fields["tenant"].queryset)
        self.assertIn(self.long_unit_a, form.fields["unit"].queryset)
        self.assertNotIn(self.long_unit_b, form.fields["unit"].queryset)


class RentInvoiceModelTests(TenantModelFactoryMixin, TestCase):
    """Derived properties on a rent invoice."""

    def _invoice(self, **kwargs):
        defaults = {
            "lease": self.lease_a,
            "period_start": date(2026, 3, 1),
            "period_end": date(2026, 3, 31),
            "due_date": date(2026, 3, 5),
            "amount": "500000.00",
        }
        defaults.update(kwargs)
        return RentInvoice.objects.create(**defaults)

    def test_period_label(self):
        self.assertEqual(self._invoice().period_label, "Mar 2026")

    def test_balance_and_paid_status(self):
        from datetime import timedelta

        invoice = self._invoice(
            amount_paid="200000.00",
            due_date=date.today() + timedelta(days=30),
        )
        self.assertEqual(invoice.balance, 300000)
        self.assertFalse(invoice.is_paid)
        self.assertEqual(invoice.effective_status, "partial")  # not yet due
        invoice.amount_paid = "500000.00"
        invoice.save()
        self.assertTrue(invoice.is_paid)
        self.assertEqual(invoice.effective_status, "paid")

    def test_overdue_status_and_days(self):
        invoice = self._invoice(due_date=date(2020, 1, 1))
        self.assertTrue(invoice.is_overdue)
        self.assertEqual(invoice.effective_status, "overdue")
        self.assertGreater(invoice.days_overdue, 0)
        self.assertEqual(invoice.aging_label, "90+ days")

    def test_aging_buckets(self):
        from datetime import timedelta

        today = date.today()
        expected = [
            (today + timedelta(days=10), "current"),
            (today - timedelta(days=10), "1-30"),
            (today - timedelta(days=45), "31-60"),
            (today - timedelta(days=75), "61-90"),
            (today - timedelta(days=200), "90+"),
        ]
        for due, bucket in expected:
            invoice = self._invoice(due_date=due)
            self.assertEqual(invoice.aging_bucket, bucket)
            invoice.delete()

    def test_unpaid_and_overdue_querysets(self):
        overdue = self._invoice(due_date=date(2020, 1, 1))
        paid = self._invoice(
            period_start=date(2026, 4, 1), period_end=date(2026, 4, 30),
            due_date=date(2026, 4, 5), amount_paid="500000.00",
        )
        self.assertIn(overdue, RentInvoice.objects.unpaid())
        self.assertNotIn(paid, RentInvoice.objects.unpaid())
        self.assertIn(overdue, RentInvoice.objects.overdue())


class GenerateRentInvoicesTests(TenantModelFactoryMixin, TestCase):
    """Service + management command behaviour (idempotency, overlap)."""

    def test_generates_one_invoice_per_active_lease(self):
        created, skipped = generate_rent_invoices(date(2026, 3, 1))
        self.assertEqual(created, 2)
        self.assertEqual(skipped, 0)
        self.assertEqual(RentInvoice.objects.count(), 2)

    def test_is_idempotent(self):
        generate_rent_invoices(date(2026, 3, 1))
        created, skipped = generate_rent_invoices(date(2026, 3, 15))
        self.assertEqual(created, 0)
        self.assertEqual(skipped, 2)
        self.assertEqual(RentInvoice.objects.count(), 2)

    def test_dry_run_writes_nothing(self):
        created, skipped = generate_rent_invoices(date(2026, 3, 1), dry_run=True)
        self.assertEqual(created, 2)
        self.assertEqual(RentInvoice.objects.count(), 0)

    def test_skips_leases_outside_period(self):
        self.lease_a.end_date = date(2025, 12, 31)
        self.lease_a.save()
        created, _ = generate_rent_invoices(
            date(2026, 3, 1), leases=Lease.objects.filter(pk=self.lease_a.pk)
        )
        self.assertEqual(created, 0)

    def test_due_day_is_clamped_to_month_end(self):
        generate_rent_invoices(date(2026, 2, 1), due_day=31,
                               leases=Lease.objects.filter(pk=self.lease_a.pk))
        invoice = RentInvoice.objects.get(lease=self.lease_a)
        self.assertEqual(invoice.due_date, date(2026, 2, 28))

    def test_command_dry_run_reports_without_writing(self):
        call_command("generate_rent_invoices", "--start", "2026-03", "--dry-run")
        self.assertEqual(RentInvoice.objects.count(), 0)

    def test_command_creates_invoices(self):
        call_command("generate_rent_invoices", "--start", "2026-03", "--end", "2026-04")
        self.assertEqual(RentInvoice.objects.count(), 4)



class RentInvoiceViewTests(TenantModelFactoryMixin, TestCase):
    """Scoping, detail access and payment recording through the views."""

    def setUp(self):
        super().setUp()
        generate_rent_invoices(date(2026, 3, 1), due_day=5, leases=Lease.objects.all())
        self.invoice_a = RentInvoice.objects.get(lease=self.lease_a)
        self.invoice_b = RentInvoice.objects.get(lease=self.lease_b)

    def test_rent_list_is_scoped(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("tenants:rent_list"))
        invoices = list(response.context["invoices"])
        self.assertIn(self.invoice_a, invoices)
        self.assertNotIn(self.invoice_b, invoices)

    def test_summary_totals(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("tenants:rent_list"))
        self.assertEqual(response.context["billed"], 500000)
        self.assertEqual(response.context["outstanding"], 500000)

    def test_rent_list_renders(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("tenants:rent_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Arrears Aging")

    def test_detail_renders_for_own_invoice(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("tenants:rent_detail", args=[self.invoice_a.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Balance Summary")

    def test_detail_other_owner_404(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("tenants:rent_detail", args=[self.invoice_b.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_record_payment_creates_payment_and_updates_balance(self):
        self.client.force_login(self.owner_a)
        response = self.client.post(
            reverse("tenants:rent_record_payment", args=[self.invoice_a.pk]),
            {"amount": "200000.00", "payment_method": "mpesa",
             "payment_date": "2026-03-06", "transaction_reference": "ABC123"},
        )
        self.assertEqual(response.status_code, 302)
        self.invoice_a.refresh_from_db()
        self.assertEqual(self.invoice_a.amount_paid, 200000)
        payment = Payment.objects.get(lease=self.lease_a)
        self.assertEqual(payment.amount, 200000)
        self.assertEqual(payment.payment_type, "rent")
        self.assertEqual(payment.transaction_reference, "ABC123")

    def test_record_payment_rejects_invalid_amount(self):
        self.client.force_login(self.owner_a)
        self.client.post(
            reverse("tenants:rent_record_payment", args=[self.invoice_a.pk]),
            {"amount": "0"},
        )
        self.invoice_a.refresh_from_db()
        self.assertEqual(self.invoice_a.amount_paid, 0)
        self.assertFalse(Payment.objects.filter(lease=self.lease_a).exists())

    def test_record_payment_other_owner_blocked(self):
        self.client.force_login(self.owner_a)
        response = self.client.post(
            reverse("tenants:rent_record_payment", args=[self.invoice_b.pk]),
            {"amount": "100000.00"},
        )
        self.assertEqual(response.status_code, 404)

    def test_generate_view_scoped_to_owner(self):
        RentInvoice.objects.all().delete()
        self.client.force_login(self.owner_a)
        self.client.post(reverse("tenants:rent_generate"), {"period": "2026-05"})
        self.assertEqual(RentInvoice.objects.count(), 1)
        self.assertEqual(RentInvoice.objects.get().lease, self.lease_a)


    # --- Cross-landlord isolation guarantees ---

    def test_login_required_for_all_rent_views(self):
        for url in (
            reverse("tenants:rent_list"),
            reverse("tenants:rent_detail", args=[self.invoice_a.pk]),
            reverse("tenants:rent_record_payment", args=[self.invoice_a.pk]),
            reverse("tenants:rent_generate"),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("login", response.url)

    def test_owner_b_list_only_sees_own_invoices(self):
        self.client.force_login(self.owner_b)
        response = self.client.get(reverse("tenants:rent_list"))
        invoices = list(response.context["invoices"])
        self.assertIn(self.invoice_b, invoices)
        self.assertNotIn(self.invoice_a, invoices)

    def test_summary_ignores_other_landlords_invoices(self):
        # A large invoice belonging to owner B must never affect owner A totals.
        RentInvoice.objects.create(
            lease=self.lease_b,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
            due_date=date(2026, 2, 5),
            amount="900000.00",
        )
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("tenants:rent_list"))
        self.assertEqual(response.context["billed"], 500000)
        self.assertEqual(response.context["outstanding"], 500000)
        self.assertLessEqual(
            response.context["overdue_total"], self.invoice_a.amount
        )

    def test_other_landlord_invoices_absent_from_list_html(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("tenants:rent_list"))
        self.assertContains(response, self.tenant_a.full_name)
        self.assertNotContains(response, self.tenant_b.full_name)

    def test_cannot_generate_invoices_for_other_landlord(self):
        RentInvoice.objects.all().delete()
        self.client.force_login(self.owner_a)
        self.client.post(reverse("tenants:rent_generate"), {"period": "2026-06"})
        invoices = RentInvoice.objects.all()
        self.assertEqual(invoices.count(), 1)
        self.assertNotIn(self.lease_b, [inv.lease for inv in invoices])

