from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse
from django import forms
from django.core.exceptions import ValidationError
from .models import Tenant, Lease
from properties.models import Unit
from payments.models import Payment
from notifications.services import beem_client
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib import colors
from django.utils import timezone
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta


# ---------- Tenants ----------

class TenantListView(ListView):
    model = Tenant
    template_name = "tenants/tenant_list.html"
    context_object_name = "tenants"
    paginate_by = 10

    def get_queryset(self):
        qs = Tenant.objects.prefetch_related("leases__unit").all()
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


class TenantDetailView(DetailView):
    model = Tenant
    template_name = "tenants/tenant_detail.html"
    context_object_name = "tenant"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        tenant = self.get_object()
        ctx["leases"] = tenant.leases.select_related("unit").all()
        ctx["payments"] = Payment.objects.filter(lease__tenant=tenant).order_by("-payment_date")[:20]
        return ctx


class TenantCreateView(CreateView):
    model = Tenant
    fields = ["full_name", "phone_number", "email", "id_number", "emergency_contact", "emergency_phone", "is_active", "notes"]
    template_name = "tenants/tenant_form.html"
    success_url = reverse_lazy("tenants:tenant_list")

    def form_valid(self, form):
        messages.success(self.request, "Tenant created successfully.")
        return super().form_valid(form)


class TenantUpdateView(UpdateView):
    model = Tenant
    fields = ["full_name", "phone_number", "email", "id_number", "emergency_contact", "emergency_phone", "is_active", "notes"]
    template_name = "tenants/tenant_form.html"
    success_url = reverse_lazy("tenants:tenant_list")

    def form_valid(self, form):
        messages.success(self.request, "Tenant updated successfully.")
        return super().form_valid(form)


class TenantDeleteView(DeleteView):
    model = Tenant
    template_name = "tenants/tenant_confirm_delete.html"
    success_url = reverse_lazy("tenants:tenant_list")

    def form_valid(self, form):
        messages.success(self.request, "Tenant deleted successfully.")
        return super().form_valid(form)


def tenant_send_sms(request, pk):
    """HTMX action: send an SMS to a tenant."""
    tenant = get_object_or_404(Tenant, pk=pk)
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = Unit.objects.filter(
            rental_type="long_term"
        ).select_related("block__property")
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


class LeaseListView(ListView):
    model = Lease
    template_name = "tenants/lease_list.html"
    context_object_name = "leases"
    paginate_by = 10

    def get_queryset(self):
        qs = Lease.objects.select_related("tenant", "unit").all()
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
        from properties.models import Property
        ctx["properties"] = Property.objects.filter(is_active=True)
        return ctx


class LeaseDetailView(DetailView):
    model = Lease
    template_name = "tenants/lease_detail.html"
    context_object_name = "lease"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        lease = self.get_object()
        ctx["payments"] = Payment.objects.filter(lease=lease).order_by("-payment_date")
        return ctx


class LeaseCreateView(CreateView):
    model = Lease
    form_class = LeaseForm
    template_name = "tenants/lease_form.html"
    success_url = reverse_lazy("tenants:lease_list")

    def form_valid(self, form):
        messages.success(self.request, "Lease created successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["long_term_units"] = Unit.objects.filter(
            rental_type="long_term"
        ).select_related("block__property")
        return ctx


class LeaseUpdateView(UpdateView):
    model = Lease
    form_class = LeaseForm
    template_name = "tenants/lease_form.html"
    success_url = reverse_lazy("tenants:lease_list")

    def form_valid(self, form):
        messages.success(self.request, "Lease updated successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["long_term_units"] = Unit.objects.filter(
            rental_type="long_term"
        ).select_related("block__property")
        return ctx


class LeaseDeleteView(DeleteView):
    model = Lease
    template_name = "tenants/lease_confirm_delete.html"
    success_url = reverse_lazy("tenants:lease_list")

    def form_valid(self, form):
        messages.success(self.request, "Lease deleted successfully.")
        return super().form_valid(form)


def lease_send_reminder(request, pk):
    """HTMX action: send rent reminder SMS for a lease."""
    lease = get_object_or_404(Lease.objects.select_related("tenant", "unit__block__property"), pk=pk)
    if request.method == "POST":
        try:
            # Read custom template from NotificationSetting (if set)
            from notifications.models import NotificationSetting
            ns = NotificationSetting.objects.first()
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


def lease_send_sms(request, pk):
    """Send a custom SMS to the tenant on a lease."""
    lease = get_object_or_404(Lease.objects.select_related("tenant", "unit"), pk=pk)
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


def lease_send_expiry_reminder(request, pk):
    """Send a lease-expiry SMS reminder for a lease."""
    lease = get_object_or_404(Lease.objects.select_related("tenant", "unit__block__property"), pk=pk)
    if request.method == "POST":
        from datetime import date
        today = date.today()
        days_left = (lease.end_date - today).days
        try:
            # Read custom template from NotificationSetting (if set)
            from notifications.models import NotificationSetting
            ns = NotificationSetting.objects.first()
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
            beem_client.send_sms(lease.tenant.phone_number, message)
            messages.success(request, f"Lease expiry reminder sent to {lease.tenant.full_name}.")
        except Exception as e:
            messages.error(request, f"Failed to send expiry reminder: {e}")
    return redirect("tenants:lease_detail", pk=pk)


def lease_download_pdf(request, pk):
    """Generate and download a PDF copy of the lease agreement."""
    lease = get_object_or_404(
        Lease.objects.select_related("tenant", "unit__block__property"), pk=pk
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title2", parent=styles["Title"], fontSize=18, spaceAfter=6 * mm,
        alignment=TA_CENTER, textColor=colors.HexColor("#1a1a2e"),
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"], fontSize=10, alignment=TA_CENTER,
        textColor=colors.HexColor("#666666"), spaceAfter=10 * mm,
    )
    heading_style = ParagraphStyle(
        "Heading2", parent=styles["Heading2"], fontSize=13, spaceAfter=4 * mm,
        spaceBefore=6 * mm, textColor=colors.HexColor("#1a1a2e"),
    )
    normal_style = ParagraphStyle(
        "Normal2", parent=styles["Normal"], fontSize=10, leading=14,
        spaceAfter=2 * mm,
    )
    field_style = ParagraphStyle(
        "Field", parent=styles["Normal"], fontSize=10, leading=14,
        textColor=colors.HexColor("#333333"),
    )

    elements = []

    # --- Title ---
    elements.append(Paragraph("LEASE AGREEMENT", title_style))
    elements.append(Paragraph(
        f"Prepared on {date.today().strftime('%B %d, %Y')}",
        subtitle_style,
    ))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))
    elements.append(Spacer(1, 4 * mm))

    # --- Party Details ---
    elements.append(Paragraph("1. PARTIES TO THE AGREEMENT", heading_style))
    parties_data = [
        ["Landlord / Property", lease.unit.block.property.name if lease.unit.block and lease.unit.block.property else "N/A"],
        ["Property Address", str(lease.unit.block) if lease.unit.block else "N/A"],
        ["Unit Number", lease.unit.unit_number],
        ["Tenant", lease.tenant.full_name],
        ["Tenant Phone", lease.tenant.phone_number],
        ["Tenant Email", lease.tenant.email or "—"],
    ]
    parties_table = Table(parties_data, colWidths=[50 * mm, 110 * mm])
    parties_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
    ]))
    elements.append(parties_table)
    elements.append(Spacer(1, 4 * mm))

    # --- Lease Terms ---
    elements.append(Paragraph("2. LEASE TERMS", heading_style))
    today = date.today()
    status_text = dict(Lease.STATUS_CHOICES).get(lease.status, lease.status)
    terms_data = [
        ["Lease Period", f"{lease.start_date.strftime('%B %d, %Y')} to {lease.end_date.strftime('%B %d, %Y')}"],
        ["Monthly Rent", f"${lease.monthly_rent:,.2f}"],
        ["Deposit Paid", "Yes" if lease.deposit_paid else "No"],
    ]
    if lease.deposit_amount:
        terms_data.append(["Deposit Amount", f"${lease.deposit_amount:,.2f}"])
    terms_data.append(["Status", status_text])

    terms_table = Table(terms_data, colWidths=[50 * mm, 110 * mm])
    terms_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
    ]))
    elements.append(terms_table)
    elements.append(Spacer(1, 4 * mm))

    # --- Terms & Conditions ---
    elements.append(Paragraph("3. TERMS AND CONDITIONS", heading_style))
    terms_text = """
    This Lease Agreement (the "Agreement") is entered into between the Landlord and the Tenant identified above.<br/><br/>
    <b>Payment:</b> The Tenant agrees to pay the monthly rent as specified above on or before the 5th day of each month.<br/><br/>
    <b>Deposit:</b> The deposit shall be held as security against damages or breach of terms and shall be refunded upon
    vacating, subject to deductions for any outstanding dues or damages.<br/><br/>
    <b>Use:</b> The leased premises shall be used exclusively as a private residence by the Tenant and their immediate
    family members. Subletting is prohibited without the Landlord's written consent.<br/><br/>
    <b>Maintenance:</b> The Tenant shall maintain the premises in good condition and shall promptly report any damages
    or needed repairs to the Landlord.<br/><br/>
    <b>Termination:</b> Either party may terminate this Agreement by giving written notice as required by law. Upon
    termination, the Tenant shall vacate the premises and return all keys.<br/><br/>
    <b>Governing Law:</b> This Agreement shall be governed by and construed in accordance with the laws of the
    applicable jurisdiction.
    """
    elements.append(Paragraph(terms_text, normal_style))
    elements.append(Spacer(1, 6 * mm))

    # --- Signatures ---
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))
    elements.append(Spacer(1, 6 * mm))
    elements.append(Paragraph("4. SIGNATURES", heading_style))

    sig_data = [
        ["", ""],
        ["", ""],
        ["", ""],
        ["", ""],
        ["Landlord Signature: ___________________", "Tenant Signature: ___________________"],
        ["", ""],
        [f"Date: {date.today().strftime('%B %d, %Y')}", f"Date: {date.today().strftime('%B %d, %Y')}"],
    ]
    sig_table = Table(sig_data, colWidths=[85 * mm, 85 * mm])
    sig_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(sig_table)

    # --- Footer ---
    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph(
        f"Generated by Tenant Systems &mdash; {date.today().strftime('%Y-%m-%d %H:%M')}",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8,
                       textColor=colors.HexColor("#999999"), alignment=TA_CENTER),
    ))

    doc.build(elements)
    pdf = buf.getvalue()
    buf.close()

    filename = f"lease_{lease.pk}_{lease.tenant.full_name.replace(' ', '_')}.pdf"
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
