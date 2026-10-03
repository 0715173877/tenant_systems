from datetime import date, timedelta

from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from dateutil.relativedelta import relativedelta

from config.test_factories import TwoLandlordFixtureMixin, make_staff_user
from payments.models import Payment
from properties.models import PropertyStaff
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


class TenantOwnershipTests(TenantModelFactoryMixin, TestCase):
    """A tenant must belong to an owner's property, reachable by that owner's staff."""

    def _list_tenants(self):
        return list(
            self.client.get(reverse("tenants:tenant_list")).context["tenants"]
        )

    def test_tenant_requires_a_property(self):
        # Without a property the tenant would detach from every scoped queryset.
        with self.assertRaises(IntegrityError):
            Tenant.objects.create(
                full_name="Detached", phone_number="+255712999999"
            )

    def test_owner_sees_only_own_tenants(self):
        self.client.force_login(self.owner_a)
        tenants = self._list_tenants()
        self.assertIn(self.tenant_a, tenants)
        self.assertNotIn(self.tenant_b, tenants)

    def test_staff_see_tenants_of_their_property(self):
        for role in ("manager", "receptionist", "accountant"):
            with self.subTest(role=role):
                staff = make_staff_user(f"{role}_a", self.property_a, role)
                self.client.force_login(staff)
                tenants = self._list_tenants()
                self.assertIn(self.tenant_a, tenants)
                self.assertNotIn(self.tenant_b, tenants)

    def test_staff_of_property_b_only_see_property_b_tenants(self):
        staff = make_staff_user("manager_b", self.property_b, "manager")
        self.client.force_login(staff)
        tenants = self._list_tenants()
        self.assertIn(self.tenant_b, tenants)
        self.assertNotIn(self.tenant_a, tenants)

    def test_staff_detail_of_other_landlord_tenant_404(self):
        staff = make_staff_user("accountant_b", self.property_b, "accountant")
        self.client.force_login(staff)
        response = self.client.get(
            reverse("tenants:tenant_detail", args=[self.tenant_a.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_deactivated_staff_sees_no_tenants(self):
        staff = make_staff_user("loner", self.property_a, "manager")
        PropertyStaff.objects.filter(user=staff).update(is_active=False)
        self.client.force_login(staff)
        self.assertEqual(self._list_tenants(), [])

    def test_tenant_create_form_scoped_for_staff(self):
        staff = make_staff_user("receptionist_a", self.property_a, "receptionist")
        self.client.force_login(staff)
        response = self.client.get(reverse("tenants:tenant_create"))
        property_qs = response.context["form"].fields["property"].queryset
        self.assertIn(self.property_a, property_qs)
        self.assertNotIn(self.property_b, property_qs)

class LeaseRenewalTests(TenantModelFactoryMixin, TestCase):
    """A manager/owner can renew an expiring lease into a pre-filled draft."""

    def _expiring_lease(self, days_left=10, **kwargs):
        """A lease for owner A that ends ``days_left`` days from today."""
        defaults = {
            "tenant": self.tenant_a,
            "unit": self.long_unit_a,
            "start_date": date.today() - timedelta(days=355),
            "end_date": date.today() + timedelta(days=days_left),
            "monthly_rent": "500000.00",
            "status": "active",
            "notes": "Original terms",
        }
        defaults.update(kwargs)
        return Lease.objects.create(**defaults)

    # ---- Model helpers ----

    def test_renewal_start_date_is_day_after_end(self):
        lease = self._expiring_lease(days_left=10)
        self.assertEqual(
            lease.renewal_start_date, lease.end_date + timedelta(days=1)
        )

    def test_is_renewable_flag(self):
        self.assertTrue(self._expiring_lease(days_left=10).is_renewable)
        self.assertFalse(self._expiring_lease(days_left=500).is_renewable)
        self.assertTrue(
            self._expiring_lease(days_left=-5, status="expired").is_renewable
        )
        self.assertFalse(
            self._expiring_lease(days_left=-5, status="terminated").is_renewable
        )

    # ---- Renew form pre-fill ----

    def test_renew_get_prefills_form_from_source(self):
        lease = self._expiring_lease(days_left=10)
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("tenants:lease_renew", args=[lease.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["renew_from"], lease)
        initial = response.context["form"].initial
        self.assertEqual(initial["tenant"], self.tenant_a.id)
        self.assertEqual(initial["unit"], self.long_unit_a.id)
        self.assertEqual(
            initial["start_date"], lease.end_date + timedelta(days=1)
        )
        self.assertEqual(str(initial["monthly_rent"]), str(lease.monthly_rent))
        self.assertEqual(initial["duration_value"], lease.duration_months)
        # The pre-filled start date is rendered into the form.
        renewed_start = (lease.end_date + timedelta(days=1)).isoformat()
        self.assertContains(response, renewed_start)

    # ---- Renew submit ----

    def test_renew_post_creates_new_lease_and_keeps_original(self):
        lease = self._expiring_lease(days_left=10)
        self.client.force_login(self.owner_a)
        new_start = lease.end_date + timedelta(days=1)
        response = self.client.post(
            reverse("tenants:lease_renew", args=[lease.id]),
            {
                "tenant": self.tenant_a.id,
                "unit": self.long_unit_a.id,
                "start_date": new_start.isoformat(),
                "duration_value": 12,
                "duration_unit": "months",
                "monthly_rent": "550000.00",
                "deposit_amount": "550000.00",
                "status": "active",
                "notes": "Renewed terms",
            },
        )
        self.assertRedirects(response, reverse("tenants:lease_list"))
        renewed = Lease.objects.get(tenant=self.tenant_a, start_date=new_start)
        self.assertEqual(renewed.end_date, new_start + relativedelta(months=12))
        self.assertEqual(str(renewed.monthly_rent), "550000.00")
        self.assertEqual(renewed.unit, self.long_unit_a)
        # The original agreement is left untouched.
        lease.refresh_from_db()
        self.assertEqual(lease.notes, "Original terms")
        self.assertEqual(lease.status, "active")

    # ---- Access control ----

    def test_renew_scoped_to_own_properties(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("tenants:lease_renew", args=[self.lease_b.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_manager_can_renew_own_property_lease(self):
        lease = self._expiring_lease(days_left=10)
        manager = make_staff_user("manager_renew", self.property_a, "manager")
        self.client.force_login(manager)
        response = self.client.get(
            reverse("tenants:lease_renew", args=[lease.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_renew_requires_login(self):
        lease = self._expiring_lease(days_left=10)
        response = self.client.get(
            reverse("tenants:lease_renew", args=[lease.id])
        )
        self.assertEqual(response.status_code, 302)

    # ---- Button visibility ----

    def test_renew_button_visible_when_lease_ending_soon(self):
        lease = self._expiring_lease(days_left=10)
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("tenants:lease_detail", args=[lease.id])
        )
        self.assertContains(
            response, reverse("tenants:lease_renew", args=[lease.id])
        )

    def test_renew_button_hidden_for_far_future_lease(self):
        lease = self._expiring_lease(days_left=500)
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("tenants:lease_detail", args=[lease.id])
        )
        self.assertNotContains(
            response, reverse("tenants:lease_renew", args=[lease.id])
        )

    def test_renew_button_in_list_when_renewable(self):
        lease = self._expiring_lease(days_left=10)
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("tenants:lease_list"))
        self.assertContains(
            response, reverse("tenants:lease_renew", args=[lease.id])
        )



class LeaseAutoExpiryTests(TenantModelFactoryMixin, TestCase):
    """Overdue leases are lazily flipped from active to expired."""

    def _overdue_lease(self, **kwargs):
        defaults = {
            "tenant": self.tenant_a,
            "unit": self.long_unit_a,
            "start_date": date.today() - timedelta(days=400),
            "end_date": date.today() - timedelta(days=5),
            "monthly_rent": "500000.00",
            "status": "active",
        }
        defaults.update(kwargs)
        return Lease.objects.create(**defaults)

    def test_expire_past_due_flips_overdue_active(self):
        lease = self._overdue_lease()
        updated = Lease.objects.expire_past_due()
        self.assertEqual(updated, 1)
        lease.refresh_from_db()
        self.assertEqual(lease.status, "expired")

    def test_expire_past_due_keeps_future_and_terminated(self):
        future = self._overdue_lease(end_date=date.today() + timedelta(days=30))
        terminated = self._overdue_lease(status="terminated")
        Lease.objects.expire_past_due()
        future.refresh_from_db()
        terminated.refresh_from_db()
        self.assertEqual(future.status, "active")
        self.assertEqual(terminated.status, "terminated")

    def test_lease_list_auto_expires_overdue(self):
        lease = self._overdue_lease()
        self.client.force_login(self.owner_a)
        self.client.get(reverse("tenants:lease_list"))
        lease.refresh_from_db()
        self.assertEqual(lease.status, "expired")

    def test_lease_detail_shows_expired_status(self):
        lease = self._overdue_lease()
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("tenants:lease_detail", args=[lease.id])
        )
        self.assertEqual(response.context["lease"].status, "expired")
        self.assertContains(response, "Expired")

    def test_dashboard_auto_expires_overdue(self):
        lease = self._overdue_lease()
        self.client.force_login(self.owner_a)
        self.client.get(reverse("dashboard"))
        lease.refresh_from_db()
        self.assertEqual(lease.status, "expired")

