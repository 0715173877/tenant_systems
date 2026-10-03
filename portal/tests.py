"""Tests for the tenant portal: account provisioning, access control and
data isolation between tenants.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import authenticate
from django.test import TestCase
from django.urls import reverse

from config.test_factories import TwoLandlordFixtureMixin
from payments.models import Payment
from properties.models import MaintenanceRequest
from tenants.models import Lease, RentInvoice, Tenant
from tenants.signals import TENANT_GROUP_NAME


class PortalFixtureMixin(TwoLandlordFixtureMixin):
    """Two landlords, each with one tenant, active lease, invoice and payment."""

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
        self.invoice_a = RentInvoice.objects.create(
            lease=self.lease_a, period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31), due_date=date(2026, 1, 5),
            amount="500000.00",
        )
        self.invoice_b = RentInvoice.objects.create(
            lease=self.lease_b, period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31), due_date=date(2026, 1, 5),
            amount="500000.00",
        )
        self.payment_a = Payment.objects.create(
            lease=self.lease_a, payment_type="rent", payment_method="cash",
            amount=Decimal("500000.00"), payment_date=date(2026, 1, 10),
            status="completed",
        )
        self.payment_b = Payment.objects.create(
            lease=self.lease_b, payment_type="rent", payment_method="cash",
            amount=Decimal("500000.00"), payment_date=date(2026, 1, 10),
            status="completed",
        )


class TenantAccountProvisionTests(PortalFixtureMixin, TestCase):
    def test_tenant_gets_linked_portal_login(self):
        user = self.tenant_a.user
        self.assertIsNotNone(user)
        self.assertEqual(user.username, self.tenant_a.phone_number)
        self.assertTrue(user.check_password(self.tenant_a.phone_number))

    def test_tenant_user_is_in_tenant_group(self):
        self.assertTrue(
            self.tenant_a.user.groups.filter(name=TENANT_GROUP_NAME).exists()
        )

    def test_tenant_without_phone_gets_no_login(self):
        blank = Tenant.objects.create(
            property=self.property_a, full_name="No Phone", phone_number=""
        )
        self.assertIsNone(blank.user)


class TenantAccountSyncTests(PortalFixtureMixin, TestCase):
    """Editing a tenant's phone number must follow through to their login."""

    def test_editing_phone_updates_login_credentials(self):
        tenant = self.tenant_a
        tenant.phone_number = "+255700999888"
        tenant.save()
        tenant.refresh_from_db()

        user = tenant.user
        self.assertEqual(user.username, "+255700999888")
        self.assertTrue(user.check_password("+255700999888"))
        self.assertIsNotNone(
            authenticate(username="+255700999888", password="+255700999888")
        )

    def test_old_phone_no_longer_works_after_edit(self):
        old_phone = self.tenant_a.phone_number
        self.tenant_a.phone_number = "+255700999777"
        self.tenant_a.save()

        self.assertIsNone(
            authenticate(username=old_phone, password=old_phone)
        )

    def test_login_view_accepts_new_phone_after_edit(self):
        self.tenant_a.phone_number = "+255700999666"
        self.tenant_a.save()
        response = self.client.post(
            reverse("login"),
            {"username": "+255700999666", "password": "+255700999666"},
        )
        self.assertRedirects(response, reverse("portal:dashboard"))

    def test_editing_phone_keeps_same_linked_account(self):
        user_id = self.tenant_a.user_id
        self.tenant_a.phone_number = "+255700999555"
        self.tenant_a.save()
        self.tenant_a.refresh_from_db()
        self.assertEqual(self.tenant_a.user_id, user_id)


class PortalLeaseDownloadTests(PortalFixtureMixin, TestCase):
    """A tenant can access and download a PDF of their own lease."""

    def test_lease_list_shows_download_link(self):
        self.client.force_login(self.tenant_a.user)
        response = self.client.get(reverse("portal:leases"))
        self.assertContains(
            response, reverse("portal:lease_pdf", args=[self.lease_a.pk])
        )

    def test_lease_detail_shows_download_link(self):
        self.client.force_login(self.tenant_a.user)
        response = self.client.get(
            reverse("portal:lease_detail", args=[self.lease_a.pk])
        )
        self.assertContains(
            response, reverse("portal:lease_pdf", args=[self.lease_a.pk])
        )

    def test_tenant_downloads_own_lease_pdf(self):
        self.client.force_login(self.tenant_a.user)
        response = self.client.get(
            reverse("portal:lease_pdf", args=[self.lease_a.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("attachment", response["Content-Disposition"])

    def test_tenant_cannot_download_another_tenants_lease(self):
        self.client.force_login(self.tenant_a.user)
        response = self.client.get(
            reverse("portal:lease_pdf", args=[self.lease_b.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_lease_pdf_requires_login(self):
        response = self.client.get(
            reverse("portal:lease_pdf", args=[self.lease_a.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])


class PortalAccessTests(PortalFixtureMixin, TestCase):
    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_non_tenant_is_redirected_to_dashboard(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("portal:dashboard"))
        self.assertRedirects(response, reverse("dashboard"))

    def test_tenant_can_open_portal(self):
        self.client.force_login(self.tenant_a.user)
        response = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(response.status_code, 200)


class PortalIsolationTests(PortalFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.tenant_a.user)

    def test_lease_list_only_shows_own_leases(self):
        response = self.client.get(reverse("portal:leases"))
        leases = list(response.context["leases"])
        self.assertIn(self.lease_a, leases)
        self.assertNotIn(self.lease_b, leases)

    def test_invoice_list_only_shows_own_invoices(self):
        response = self.client.get(reverse("portal:invoices"))
        invoices = list(response.context["invoices"])
        self.assertIn(self.invoice_a, invoices)
        self.assertNotIn(self.invoice_b, invoices)

    def test_payment_list_only_shows_own_payments(self):
        response = self.client.get(reverse("portal:payments"))
        payments = list(response.context["payments"])
        self.assertIn(self.payment_a, payments)
        self.assertNotIn(self.payment_b, payments)

    def test_cannot_view_another_tenants_invoice(self):
        response = self.client.get(
            reverse("portal:invoice_detail", args=[self.invoice_b.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_cannot_view_another_tenants_lease(self):
        response = self.client.get(
            reverse("portal:lease_detail", args=[self.lease_b.pk])
        )
        self.assertEqual(response.status_code, 404)


class PortalLoginRoutingTests(PortalFixtureMixin, TestCase):
    def test_tenant_login_lands_on_portal(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.tenant_a.phone_number, "password": self.tenant_a.phone_number},
        )
        self.assertRedirects(response, reverse("portal:dashboard"))

    def test_landlord_login_lands_on_dashboard(self):
        response = self.client.post(
            reverse("login"),
            {"username": "owner_a", "password": "pass12345"},
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_tenant_dashboard_redirects_to_portal(self):
        self.client.force_login(self.tenant_a.user)
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("portal:dashboard"))


class PortalMaintenanceTests(PortalFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.tenant_a.user)

    def test_report_issue_uses_current_lease_unit(self):
        response = self.client.post(
            reverse("portal:maintenance_create"),
            {"title": "Leaking tap", "description": "Kitchen tap drips.", "priority": "high"},
        )
        self.assertRedirects(response, reverse("portal:maintenance"))
        req = MaintenanceRequest.objects.get(title="Leaking tap")
        self.assertEqual(req.unit, self.long_unit_a)
        self.assertEqual(req.property, self.property_a)
        self.assertEqual(req.reported_by, self.tenant_a.user)

    def test_list_only_shows_own_units_requests(self):
        MaintenanceRequest.objects.create(
            property=self.property_a, unit=self.long_unit_a,
            title="Mine", description="x", reported_by=self.tenant_a.user,
        )
        MaintenanceRequest.objects.create(
            property=self.property_b, unit=self.long_unit_b,
            title="Theirs", description="y",
        )
        response = self.client.get(reverse("portal:maintenance"))
        titles = [r.title for r in response.context["requests"]]
        self.assertIn("Mine", titles)
        self.assertNotIn("Theirs", titles)


class PortalProfileTests(PortalFixtureMixin, TestCase):
    def test_tenant_can_update_contact_details(self):
        self.client.force_login(self.tenant_a.user)
        response = self.client.post(
            reverse("portal:profile"),
            {"email": "a@example.com", "emergency_contact": "Sister",
             "emergency_phone": "+255700000000"},
        )
        self.assertRedirects(response, reverse("portal:profile"))
        self.tenant_a.refresh_from_db()
        self.assertEqual(self.tenant_a.email, "a@example.com")
        self.assertEqual(self.tenant_a.emergency_contact, "Sister")

    def test_profile_page_opens(self):
        self.client.force_login(self.tenant_a.user)
        response = self.client.get(reverse("portal:profile"))
        self.assertEqual(response.status_code, 200)



class PortalLeaseExpiryTests(PortalFixtureMixin, TestCase):
    """A tenant's overdue lease is retired from active when the portal loads."""

    def test_overdue_lease_becomes_expired_on_portal_load(self):
        Lease.objects.filter(pk=self.lease_a.pk).update(
            end_date=date.today() - timedelta(days=3)
        )
        self.client.force_login(self.tenant_a.user)
        response = self.client.get(reverse("portal:leases"))
        self.lease_a.refresh_from_db()
        self.assertEqual(self.lease_a.status, "expired")
        # With no active lease left, the portal shows no "current" lease.
        self.assertIsNone(response.context["current_lease"])

