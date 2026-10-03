"""Tenant self-service portal.

Every view is scoped to the signed-in tenant's own record via
:class:`tenants.access.TenantPortalMixin`, so a tenant can only ever see their
own lease, rent invoices, payments and maintenance requests.
"""
from datetime import date
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.db.models import F, Sum
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from payments.models import Payment
from properties.models import MaintenanceRequest
from tenants.access import TenantPortalMixin
from tenants.models import RentInvoice, Tenant


def _tenant_unit_ids(tenant):
    """Unit ids the tenant has ever leased (used to find their maintenance)."""
    return tenant.leases.values_list("unit_id", flat=True)


class _ActiveLeaseMixin:
    """Adds a helper for the tenant's current (active) lease."""

    def get_current_lease(self):
        return (
            self.tenant.leases.filter(status="active")
            .select_related("unit__block__property")
            .order_by("-start_date")
            .first()
        )


# ---------- Dashboard ----------

class PortalDashboardView(_ActiveLeaseMixin, TenantPortalMixin, TemplateView):
    template_name = "portal/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        tenant = self.tenant
        lease = self.get_current_lease()
        invoices = RentInvoice.objects.filter(lease__tenant=tenant)

        outstanding = invoices.unpaid().aggregate(
            total=Sum(F("amount") - F("amount_paid"))
        )["total"] or Decimal("0")

        ctx.update({
            "tenant": tenant,
            "lease": lease,
            "property": lease.unit.block.property if lease and lease.unit else None,
            "invoices": invoices.select_related("lease__unit")[:5],
            "outstanding": outstanding,
            "next_invoice": invoices.unpaid().order_by("due_date").first(),
            "recent_payments": Payment.objects.filter(lease__tenant=tenant)
            .select_related("lease__unit")
            .order_by("-payment_date")[:5],
            "open_maintenance": MaintenanceRequest.objects.filter(
                unit_id__in=_tenant_unit_ids(tenant)
            ).exclude(status__in=["completed", "cancelled"])[:5],
            "today": date.today(),
        })
        return ctx


# ---------- Lease ----------

class PortalLeaseListView(_ActiveLeaseMixin, TenantPortalMixin, ListView):
    template_name = "portal/lease_list.html"
    context_object_name = "leases"

    def get_queryset(self):
        return self.tenant.leases.select_related("unit__block__property").all()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["current_lease"] = self.get_current_lease()
        return ctx


class PortalLeaseDetailView(_ActiveLeaseMixin, TenantPortalMixin, DetailView):
    template_name = "portal/lease_detail.html"
    context_object_name = "lease"

    def get_queryset(self):
        return self.tenant.leases.select_related("unit__block__property")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        lease = self.object
        ctx["invoices"] = lease.invoices.all()[:12]
        ctx["payments"] = Payment.objects.filter(lease=lease).order_by("-payment_date")
        return ctx


# ---------- Invoices ----------

class PortalInvoiceListView(TenantPortalMixin, ListView):
    template_name = "portal/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 20

    def get_queryset(self):
        return (
            RentInvoice.objects.filter(lease__tenant=self.tenant)
            .select_related("lease__unit__block__property")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        invoices = RentInvoice.objects.filter(lease__tenant=self.tenant)
        ctx["outstanding"] = invoices.unpaid().aggregate(
            total=Sum(F("amount") - F("amount_paid"))
        )["total"] or Decimal("0")
        ctx["overdue_count"] = invoices.overdue().count()
        ctx["today"] = date.today()
        return ctx


class PortalInvoiceDetailView(TenantPortalMixin, DetailView):
    template_name = "portal/invoice_detail.html"
    context_object_name = "invoice"

    def get_queryset(self):
        return RentInvoice.objects.filter(
            lease__tenant=self.tenant
        ).select_related("lease__unit__block__property")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["payments"] = Payment.objects.filter(
            lease=self.object.lease
        ).order_by("-payment_date")
        return ctx


# ---------- Payments ----------

class PortalPaymentListView(TenantPortalMixin, ListView):
    template_name = "portal/payment_list.html"
    context_object_name = "payments"
    paginate_by = 20

    def get_queryset(self):
        return (
            Payment.objects.filter(lease__tenant=self.tenant)
            .select_related("lease__unit")
            .order_by("-payment_date")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total_paid"] = (
            Payment.objects.filter(lease__tenant=self.tenant, status="completed")
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0")
        )
        return ctx


# ---------- Maintenance ----------

class PortalMaintenanceForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ["title", "description", "priority"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class PortalMaintenanceListView(TenantPortalMixin, ListView):
    template_name = "portal/maintenance_list.html"
    context_object_name = "requests"

    def get_queryset(self):
        return MaintenanceRequest.objects.filter(
            unit_id__in=_tenant_unit_ids(self.tenant)
        ).select_related("unit")


class PortalMaintenanceCreateView(_ActiveLeaseMixin, TenantPortalMixin, CreateView):
    template_name = "portal/maintenance_form.html"
    form_class = PortalMaintenanceForm
    success_url = reverse_lazy("portal:maintenance")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["lease"] = self.get_current_lease()
        return ctx

    def form_valid(self, form):
        lease = self.get_current_lease()
        if lease is None or lease.unit is None:
            messages.error(
                self.request,
                "You need an active lease before reporting a maintenance issue.",
            )
            return redirect("portal:maintenance")
        form.instance.property = lease.unit.block.property
        form.instance.unit = lease.unit
        form.instance.reported_by = self.request.user
        messages.success(self.request, "Maintenance request submitted. Thank you!")
        return super().form_valid(form)


# ---------- How to pay ----------

class PortalPaymentInstructionsView(_ActiveLeaseMixin, TenantPortalMixin, TemplateView):
    template_name = "portal/payment_instructions.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        lease = self.get_current_lease()
        prop = lease.unit.block.property if lease and lease.unit else None
        ctx["lease"] = lease
        ctx["property"] = prop
        ctx["owner_profile"] = (
            getattr(prop.owner, "owner_profile", None) if prop else None
        )
        return ctx


# ---------- Profile ----------

class PortalProfileForm(forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ["email", "emergency_contact", "emergency_phone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class PortalProfileView(TenantPortalMixin, UpdateView):
    template_name = "portal/profile.html"
    form_class = PortalProfileForm
    success_url = reverse_lazy("portal:profile")

    def get_object(self, queryset=None):
        return self.tenant

    def form_valid(self, form):
        messages.success(self.request, "Your details were updated.")
        return super().form_valid(form)


