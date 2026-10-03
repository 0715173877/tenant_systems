from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse
from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum, F
from .models import Tenant, Lease, RentInvoice
from .pdf import build_lease_pdf, lease_pdf_filename
from .services import generate_rent_invoices
from properties.models import Unit
from properties.access import (
    capability_required,
    get_accessible_properties,
    LeasesManageMixin,
    LeasesViewMixin,
    PropertyScopedMixin,
    RentManageMixin,
    RentViewMixin,
    TenantsManageMixin,
    TenantsViewMixin,
)
from payments.models import Payment
from notifications.services import beem_client
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta


# ---------- Data-isolation mixins ----------

class TenantScopedMixin(LoginRequiredMixin):
    """Restrict tenant querysets/objects to the user's accessible properties."""

    def get_property_queryset(self):
        return get_accessible_properties(self.request.user)

    def get_queryset(self):
        return super().get_queryset().filter(
            property__in=self.get_property_queryset()
        )


class LeaseScopedMixin(LoginRequiredMixin):
    """Restrict lease querysets/objects to the user's accessible properties."""

    def get_property_queryset(self):
        return get_accessible_properties(self.request.user)

    def get_queryset(self):
        # Lazily retire leases that have run past their end date so list/detail
        # pages never show a stale "Active" status for an ended agreement.
        Lease.objects.expire_past_due()
        return super().get_queryset().filter(
            unit__block__property__in=self.get_property_queryset()
        )


# ---------- Tenants ----------

class TenantListView(TenantsViewMixin, TenantScopedMixin, ListView):
    model = Tenant
    template_name = "tenants/tenant_list.html"
    context_object_name = "tenants"
    paginate_by = 10

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related("leases__unit")
        q = self.request.GET.get("q")
        is_active = self.request.GET.get("is_active")
        if q:
            qs = qs.filter(full_name__icontains=q) | qs.filter(phone_number__icontains=q)
        if is_active:
            qs = qs.filter(is_active=(is_active == "true"))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["filter_active"] = self.request.GET.get("is_active", "")
        return ctx


class TenantDetailView(TenantsViewMixin, TenantScopedMixin, DetailView):
    model = Tenant
    template_name = "tenants/tenant_detail.html"
    context_object_name = "tenant"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        tenant = self.get_object()
        ctx["leases"] = tenant.leases.select_related("unit").all()
        ctx["payments"] = Payment.objects.filter(lease__tenant=tenant).order_by("-payment_date")[:20]
        return ctx


class TenantCreateView(TenantsManageMixin, TenantScopedMixin, CreateView):
    model = Tenant
    fields = ["property", "full_name", "phone_number", "email", "id_number", "emergency_contact", "emergency_phone", "is_active", "notes"]
    template_name = "tenants/tenant_form.html"
    success_url = reverse_lazy("tenants:tenant_list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        properties = self.get_property_queryset()
        form.fields["property"].queryset = properties
        form.fields["property"].required = True
        # Auto-select when the user only has one property.
        if properties.count() == 1:
            form.fields["property"].initial = properties.first()
        return form

    def form_valid(self, form):
        messages.success(self.request, "Tenant created successfully.")
        return super().form_valid(form)


class TenantUpdateView(TenantsManageMixin, TenantScopedMixin, UpdateView):
    model = Tenant
    fields = ["property", "full_name", "phone_number", "email", "id_number", "emergency_contact", "emergency_phone", "is_active", "notes"]
    template_name = "tenants/tenant_form.html"
    success_url = reverse_lazy("tenants:tenant_list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["property"].queryset = self.get_property_queryset()
        form.fields["property"].required = True
        return form

    def form_valid(self, form):
        messages.success(self.request, "Tenant updated successfully.")
        return super().form_valid(form)


class TenantDeleteView(TenantsManageMixin, TenantScopedMixin, DeleteView):
    model = Tenant
    template_name = "tenants/tenant_confirm_delete.html"
    success_url = reverse_lazy("tenants:tenant_list")

    def form_valid(self, form):
        messages.success(self.request, "Tenant deleted successfully.")
        return super().form_valid(form)


@login_required
@capability_required("tenants_manage")
def tenant_send_sms(request, pk):
    """HTMX action: send an SMS to a tenant."""
    tenant = get_object_or_404(
        Tenant, pk=pk, property__in=get_accessible_properties(request.user)
    )
    if request.method == "POST":
        message = request.POST.get("message", "")
        if message:
            try:
                beem_client.send_sms(tenant.phone_number, message)
                messages.success(request, f"SMS sent to {tenant.full_name} successfully.")
            except Exception as e:
                messages.error(request, f"Failed to send SMS: {e}")
        else:
            messages.error(request, "Message cannot be empty.")
    return redirect("tenants:tenant_detail", pk=pk)


# ---------- Leases ----------

class LeaseForm(forms.ModelForm):
    """Custom Lease form with duration-based end date calculation."""

    DURATION_UNIT_CHOICES = [
        ("months", "Months"),
        ("days", "Days"),
    ]

    duration_value = forms.IntegerField(
        label="Lease Duration",
        min_value=1,
        initial=12,
        help_text="Number of days or months from start date",
    )
    duration_unit = forms.ChoiceField(
        label="Duration Unit",
        choices=DURATION_UNIT_CHOICES,
        initial="months",
    )

    class Meta:
        model = Lease
        fields = ["tenant", "unit", "start_date", "end_date", "monthly_rent", "deposit_paid", "deposit_amount", "status", "file", "notes"]
        widgets = {
            "end_date": forms.DateInput(attrs={"type": "date", "readonly": "readonly"}),
        }

    def __init__(self, *args, properties=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Default to nothing; callers must pass the properties the current
        # user is allowed to access (see LeaseCreateView/LeaseUpdateView).
        unit_qs = Unit.objects.none()
        tenant_qs = Tenant.objects.none()
        if properties is not None:
            unit_qs = Unit.objects.filter(
                rental_type="long_term", block__property__in=properties
            ).select_related("block__property")
            tenant_qs = Tenant.objects.filter(property__in=properties)
        self.fields["unit"].queryset = unit_qs
        self.fields["tenant"].queryset = tenant_qs
        # Make end_date not required (it's auto-calculated)
        self.fields["end_date"].required = False
        # If editing an existing lease, populate the duration fields from current dates
        if self.instance and self.instance.pk and self.instance.start_date and self.instance.end_date:
            # Default to showing months for editing
            self.fields["duration_unit"].initial = "months"
            self.fields["duration_value"].initial = self.instance.duration_months or 12
            self.fields["end_date"].required = True  # allow manual override during edit

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        duration_value = cleaned_data.get("duration_value")
        duration_unit = cleaned_data.get("duration_unit")
        end_date = cleaned_data.get("end_date")

        # If duration_value and duration_unit are provided, calculate end_date
        if start_date and duration_value and duration_unit:
            if duration_unit == "months":
                calculated_end = start_date + relativedelta(months=duration_value)
            else:  # days
                calculated_end = start_date + timedelta(days=duration_value)
            cleaned_data["end_date"] = calculated_end
        elif not end_date:
            raise ValidationError(
                "Either provide an end date directly or specify duration (value + unit)."
            )

        return cleaned_data


class LeaseListView(LeasesViewMixin, LeaseScopedMixin, ListView):
    model = Lease
    template_name = "tenants/lease_list.html"
    context_object_name = "leases"
    paginate_by = 10

    def get_queryset(self):
        qs = super().get_queryset().select_related("tenant", "unit")
        status = self.request.GET.get("status")
        property_id = self.request.GET.get("property")
        if status:
            qs = qs.filter(status=status)
        if property_id:
            qs = qs.filter(unit__block__property_id=property_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["filter_property"] = self.request.GET.get("property", "")
        ctx["properties"] = self.get_property_queryset().filter(is_active=True)
        return ctx


class LeaseDetailView(LeasesViewMixin, LeaseScopedMixin, DetailView):
    model = Lease
    template_name = "tenants/lease_detail.html"
    context_object_name = "lease"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        lease = self.get_object()
        ctx["payments"] = Payment.objects.filter(lease=lease).order_by("-payment_date")
        return ctx


class LeaseCreateView(LeasesManageMixin, LeaseScopedMixin, CreateView):
    model = Lease
    form_class = LeaseForm
    template_name = "tenants/lease_form.html"
    success_url = reverse_lazy("tenants:lease_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["properties"] = self.get_property_queryset()
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "Lease created successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["long_term_units"] = Unit.objects.filter(
            rental_type="long_term",
            block__property__in=self.get_property_queryset(),
        ).select_related("block__property")
        return ctx


class LeaseRenewView(LeasesManageMixin, LeaseScopedMixin, CreateView):
    """Renew a lease into a fresh one pre-filled from the current agreement.

    The new term starts the day after the source lease ends
    (``renewal_start_date``); every other field (tenant, unit, rent, deposit,
    duration, notes, ...) is copied so a manager/owner only has to adjust what
    has changed before submitting.
    """

    model = Lease
    form_class = LeaseForm
    template_name = "tenants/lease_form.html"
    success_url = reverse_lazy("tenants:lease_list")

    def get_source_lease(self):
        if not hasattr(self, "_source_lease"):
            # Scoped queryset -> a lease from another landlord's property 404s.
            self._source_lease = get_object_or_404(
                self.get_queryset(), pk=self.kwargs["pk"]
            )
        return self._source_lease

    def get_initial(self):
        initial = super().get_initial()
        lease = self.get_source_lease()
        initial.update(
            {
                "tenant": lease.tenant_id,
                "unit": lease.unit_id,
                "start_date": lease.renewal_start_date,
                "monthly_rent": lease.monthly_rent,
                "deposit_paid": False,
                "deposit_amount": lease.deposit_amount,
                "status": "active",
                "notes": lease.notes,
                "duration_unit": "months",
                "duration_value": lease.duration_months or 12,
            }
        )
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["properties"] = self.get_property_queryset()
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "Lease renewed successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["renew_from"] = self.get_source_lease()
        ctx["long_term_units"] = Unit.objects.filter(
            rental_type="long_term",
            block__property__in=self.get_property_queryset(),
        ).select_related("block__property")
        return ctx


class LeaseUpdateView(LeasesManageMixin, LeaseScopedMixin, UpdateView):
    model = Lease
    form_class = LeaseForm
    template_name = "tenants/lease_form.html"
    success_url = reverse_lazy("tenants:lease_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["properties"] = self.get_property_queryset()
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "Lease updated successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["long_term_units"] = Unit.objects.filter(
            rental_type="long_term",
            block__property__in=self.get_property_queryset(),
        ).select_related("block__property")
        return ctx


class LeaseDeleteView(LeasesManageMixin, LeaseScopedMixin, DeleteView):
    model = Lease
    template_name = "tenants/lease_confirm_delete.html"
    success_url = reverse_lazy("tenants:lease_list")

    def form_valid(self, form):
        messages.success(self.request, "Lease deleted successfully.")
        return super().form_valid(form)


@login_required
@capability_required("leases_manage")
def lease_send_reminder(request, pk):
    """HTMX action: send rent reminder SMS for a lease."""
    lease = get_object_or_404(
        Lease.objects.select_related("tenant", "unit__block__property"),
        pk=pk,
        unit__block__property__in=get_accessible_properties(request.user),
    )
    if request.method == "POST":
        try:
            # Read custom template from NotificationSetting (if set)
            from notifications.models import NotificationSetting
            ns = NotificationSetting.for_owner(lease.unit.block.property.owner)
            currency = lease.unit.effective_currency
            template = ns.rent_reminder_message_template if (ns and ns.rent_reminder_message_template) else (
                "Dear {tenant_name}, this is a reminder that your rent of "
                "{currency} {amount} for {unit_name} is due on {due_date}. "
                "Please make payment to avoid late charges. Thank you."
            )
            message = template.format(
                tenant_name=lease.tenant.full_name,
                unit_name=str(lease.unit),
                amount=str(lease.monthly_rent),
                currency=currency,
                due_date=str(lease.start_date),
                phone_number=lease.tenant.phone_number,
            )
            beem_client.send_sms(lease.tenant.phone_number, message)
            messages.success(request, f"Rent reminder sent to {lease.tenant.full_name}.")
        except Exception as e:
            messages.error(request, f"Failed to send reminder: {e}")
    return redirect("tenants:lease_detail", pk=pk)


@login_required
@capability_required("leases_manage")
def lease_send_sms(request, pk):
    """Send a custom SMS to the tenant on a lease."""
    lease = get_object_or_404(
        Lease.objects.select_related("tenant", "unit"),
        pk=pk,
        unit__block__property__in=get_accessible_properties(request.user),
    )
    if request.method == "POST":
        message = request.POST.get("message", "").strip()
        if message:
            try:
                beem_client.send_sms(lease.tenant.phone_number, message)
                messages.success(request, f"SMS sent to {lease.tenant.full_name} successfully.")
            except Exception as e:
                messages.error(request, f"Failed to send SMS: {e}")
        else:
            messages.error(request, "Message cannot be empty.")
    return redirect("tenants:lease_detail", pk=pk)


@login_required
@capability_required("leases_manage")
def lease_send_expiry_reminder(request, pk):
    """Send a lease-expiry SMS reminder for a lease."""
    lease = get_object_or_404(
        Lease.objects.select_related("tenant", "unit__block__property"),
        pk=pk,
        unit__block__property__in=get_accessible_properties(request.user),
    )
    if request.method == "POST":
        from datetime import date
        today = date.today()
        days_left = (lease.end_date - today).days
        try:
            # Read custom template from NotificationSetting (if set)
            from notifications.models import NotificationSetting
            ns = NotificationSetting.for_owner(lease.unit.block.property.owner)
            template = ns.lease_expiry_message_template if (ns and ns.lease_expiry_message_template) else (
                "Dear {tenant_name}, your lease for {unit_name} will expire in "
                "{days_left} day(s) on {end_date}. "
                "Please contact us to discuss renewal options."
            )
            message = template.format(
                tenant_name=lease.tenant.full_name,
                unit_name=str(lease.unit),
                end_date=str(lease.end_date),
                days_left=max(days_left, 0),
                phone_number=lease.tenant.phone_number,
            )
            beem_client.send_tenant_sms_with_cc(
                lease.tenant.phone_number,
                message,
                lease.unit.block.property,
            )
            messages.success(request, f"Lease expiry reminder sent to {lease.tenant.full_name}, owner and manager.")
        except Exception as e:
            messages.error(request, f"Failed to send expiry reminder: {e}")
    return redirect("tenants:lease_detail", pk=pk)


@login_required
@capability_required("leases_view")
def lease_download_pdf(request, pk):
    """Generate and download a PDF copy of the lease agreement."""
    lease = get_object_or_404(
        Lease.objects.select_related("tenant", "unit__block__property"),
        pk=pk,
        unit__block__property__in=get_accessible_properties(request.user),
    )
    response = HttpResponse(build_lease_pdf(lease), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{lease_pdf_filename(lease)}"'
    )
    return response


# ---------- Rent invoices & arrears ----------

class RentInvoiceScopedMixin(LoginRequiredMixin, PropertyScopedMixin):
    """Restrict rent-invoice querysets/objects to the user's properties."""

    property_filter = "lease__unit__block__property__in"


class RentListView(RentViewMixin, RentInvoiceScopedMixin, ListView):
    """Rent invoice register with an arrears / aging summary."""

    model = RentInvoice
    template_name = "tenants/rent_list.html"
    context_object_name = "invoices"
    paginate_by = 20

    def _base_queryset(self):
        """Invoices the user may access (scoped by the access helper) with
        property/search filters applied but *not* the status filter, so the
        summary cards always reflect the caller's whole portfolio."""
        qs = super().get_queryset().select_related(
            "lease__tenant", "lease__unit__block__property"
        )
        property_id = self.request.GET.get("property")
        q = self.request.GET.get("q")
        if property_id:
            qs = qs.filter(lease__unit__block__property_id=property_id)
        if q:
            qs = qs.filter(
                Q(lease__tenant__full_name__icontains=q)
                | Q(lease__unit__unit_number__icontains=q)
            )
        return qs

    def get_queryset(self):
        qs = self._base_queryset()
        status = self.request.GET.get("status")
        if status == "paid":
            qs = qs.filter(amount_paid__gte=F("amount"))
        elif status == "overdue":
            qs = qs.overdue()
        elif status == "unpaid":
            qs = qs.unpaid()
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        base = self._base_queryset()

        billed = base.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        collected = base.aggregate(total=Sum("amount_paid"))["total"] or Decimal("0")
        overdue_qs = base.overdue()

        # Aging buckets (computed in Python – the unpaid set is small).
        bucket_totals = {
            key: {"count": 0, "total": Decimal("0")}
            for key, _label in RentInvoice.AGING_BUCKETS
        }
        for invoice in base.unpaid():
            bucket = bucket_totals[invoice.aging_bucket]
            bucket["count"] += 1
            bucket["total"] += invoice.balance

        aging = [
            {
                "key": key,
                "label": label,
                "count": bucket_totals[key]["count"],
                "total": bucket_totals[key]["total"],
            }
            for key, label in RentInvoice.AGING_BUCKETS
        ]

        ctx.update({
            "properties": self.get_property_queryset().filter(is_active=True),
            "filter_property": self.request.GET.get("property", ""),
            "current_status": self.request.GET.get("status", ""),
            "q": self.request.GET.get("q", ""),
            "billed": billed,
            "collected": collected,
            "outstanding": billed - collected,
            "overdue_count": overdue_qs.count(),
            "overdue_total": sum((inv.balance for inv in overdue_qs), Decimal("0")),
            "aging": aging,
            "today": date.today(),
        })
        return ctx


class RentInvoiceDetailView(RentViewMixin, RentInvoiceScopedMixin, DetailView):
    model = RentInvoice
    template_name = "tenants/rent_invoice_detail.html"
    context_object_name = "invoice"

    def get_queryset(self):
        return super().get_queryset().select_related(
            "lease__tenant", "lease__unit__block__property"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        invoice = self.get_object()
        ctx["payments"] = (
            Payment.objects.filter(lease=invoice.lease)
            .order_by("-payment_date")[:20]
        )
        ctx["payment_methods"] = Payment.PAYMENT_METHOD_CHOICES
        return ctx


@login_required
@capability_required("rent_manage")
def rent_invoice_record_payment(request, pk):
    """Record a rent payment against an invoice and update its balance."""
    invoice = get_object_or_404(
        RentInvoice.objects.select_related("lease__tenant", "lease__unit"),
        pk=pk,
        lease__unit__block__property__in=get_accessible_properties(request.user),
    )
    if request.method == "POST":
        raw_amount = request.POST.get("amount", "")
        try:
            amount = Decimal(raw_amount)
        except (InvalidOperation, TypeError):
            messages.error(request, "Enter a valid payment amount.")
            return redirect("tenants:rent_detail", pk=pk)
        if amount <= 0:
            messages.error(request, "Payment amount must be greater than zero.")
            return redirect("tenants:rent_detail", pk=pk)

        payment_date_raw = request.POST.get("payment_date")
        try:
            payment_date = (
                date.fromisoformat(payment_date_raw) if payment_date_raw else date.today()
            )
        except ValueError:
            messages.error(request, "Enter a valid payment date.")
            return redirect("tenants:rent_detail", pk=pk)

        Payment.objects.create(
            lease=invoice.lease,
            payment_type="rent",
            payment_method=request.POST.get("payment_method") or "cash",
            amount=amount,
            transaction_reference=request.POST.get("transaction_reference", ""),
            payment_date=payment_date,
            status="completed",
            notes=f"Rent payment for {invoice.period_label}",
        )
        invoice.amount_paid = invoice.amount_paid + amount
        invoice.save(update_fields=["amount_paid", "updated_at"])
        messages.success(
            request,
            f"Payment of {amount} recorded for {invoice.lease.tenant.full_name} "
            f"({invoice.period_label}). Balance: {invoice.balance}.",
        )
    return redirect("tenants:rent_detail", pk=pk)


@login_required
@capability_required("rent_manage")
def rent_invoice_generate(request):
    """Generate invoices for a month across the user's accessible leases."""
    if request.method == "POST":
        period_raw = request.POST.get("period")
        try:
            period = (
                date.fromisoformat(f"{period_raw}-01") if period_raw else date.today()
            )
        except ValueError:
            messages.error(request, "Enter a valid period (YYYY-MM).")
            return redirect("tenants:rent_list")

        leases = Lease.objects.filter(
            status="active",
            unit__block__property__in=get_accessible_properties(request.user),
        ).select_related("tenant")
        created, skipped = generate_rent_invoices(period, leases=leases)
        messages.success(
            request,
            f"{created} invoice(s) generated for {period.strftime('%b %Y')} "
            f"({skipped} already existed).",
        )
    return redirect("tenants:rent_list")
