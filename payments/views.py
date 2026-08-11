import datetime
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView
from django.urls import reverse_lazy
from django.contrib import messages
from django.shortcuts import redirect
from django.db.models import Sum, Count, Q
from .models import Payment
from tenants.models import Lease
from bookings.models import Booking


class PaymentListView(ListView):
    model = Payment
    template_name = "payments/payment_list.html"
    context_object_name = "payments"
    paginate_by = 10

    def get_queryset(self):
        qs = Payment.objects.select_related("lease__tenant", "booking__guest").all()
        payment_type = self.request.GET.get("payment_type")
        status = self.request.GET.get("status")
        start_date = self.request.GET.get("start_date")
        end_date = self.request.GET.get("end_date")
        if payment_type:
            qs = qs.filter(payment_type=payment_type)
        if status:
            qs = qs.filter(status=status)
        if start_date:
            qs = qs.filter(payment_date__gte=start_date)
        if end_date:
            qs = qs.filter(payment_date__lte=end_date)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["current_type"] = self.request.GET.get("payment_type", "")
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["start_date"] = self.request.GET.get("start_date", "")
        ctx["end_date"] = self.request.GET.get("end_date", "")
        return ctx


class PaymentDetailView(DetailView):
    model = Payment
    template_name = "payments/payment_detail.html"
    context_object_name = "payment"


class PaymentCreateView(CreateView):
    model = Payment
    fields = [
        "lease", "booking", "payment_type", "payment_method",
        "amount", "transaction_reference", "payment_date",
        "status", "notes",
    ]
    template_name = "payments/payment_form.html"
    success_url = reverse_lazy("payments:payment_list")

    def form_valid(self, form):
        messages.success(self.request, "Payment recorded successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["active_leases"] = Lease.objects.filter(status="active").select_related("tenant", "unit")
        ctx["confirmed_bookings"] = Booking.objects.filter(
            status__in=["confirmed", "checked_in"]
        ).select_related("guest", "unit")
        return ctx


class PaymentUpdateView(UpdateView):
    model = Payment
    fields = [
        "lease", "booking", "payment_type", "payment_method",
        "amount", "transaction_reference", "payment_date",
        "status", "notes",
    ]
    template_name = "payments/payment_form.html"
    success_url = reverse_lazy("payments:payment_list")

    def form_valid(self, form):
        messages.success(self.request, "Payment updated successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["active_leases"] = Lease.objects.filter(status="active").select_related("tenant", "unit")
        ctx["confirmed_bookings"] = Booking.objects.filter(
            status__in=["confirmed", "checked_in"]
        ).select_related("guest", "unit")
        return ctx


class PaymentDeleteView(DeleteView):
    model = Payment
    template_name = "payments/payment_confirm_delete.html"
    success_url = reverse_lazy("payments:payment_list")

    def form_valid(self, form):
        messages.success(self.request, "Payment deleted successfully.")
        return super().form_valid(form)


# ---------- Reports ----------

class PaymentReportView(TemplateView):
    template_name = "payments/report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = datetime.date.today()
        start_date = self.request.GET.get("start_date", str(today.replace(day=1)))
        end_date = self.request.GET.get("end_date", str(today))

        # All payments (not just completed) within date range
        qs = Payment.objects.filter(
            payment_date__gte=start_date,
            payment_date__lte=end_date,
        )

        # Summary aggregations
        total_revenue = qs.aggregate(total=Sum("amount"))["total"] or 0
        completed_amount = qs.filter(status="completed").aggregate(total=Sum("amount"))["total"] or 0
        pending_amount = qs.filter(status="pending").aggregate(total=Sum("amount"))["total"] or 0
        failed_amount = qs.filter(status="failed").aggregate(total=Sum("amount"))["total"] or 0

        # Summary by type
        by_type = list(
            qs.values("payment_type")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("-total")
        )
        type_labels = dict(Payment.PAYMENT_TYPE_CHOICES)
        for item in by_type:
            item["display"] = type_labels.get(item["payment_type"], item["payment_type"])

        # Summary by method
        by_method = list(
            qs.values("payment_method")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("-total")
        )
        method_labels = dict(Payment.PAYMENT_METHOD_CHOICES)
        for item in by_method:
            item["display"] = method_labels.get(item["payment_method"], item["payment_method"])

        # Daily totals for chart
        daily = list(
            qs.values("payment_date")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("payment_date")
        )

        total_count = qs.count()

        ctx.update({
            "start_date": start_date,
            "end_date": end_date,
            "payments": qs.select_related("lease__tenant", "booking__guest").order_by("-payment_date"),
            "by_type": by_type,
            "by_method": by_method,
            "daily": daily,
            "total_revenue": total_revenue,
            "completed_amount": completed_amount,
            "pending_amount": pending_amount,
            "failed_amount": failed_amount,
            "grand_total": total_revenue,
            "total_count": total_count,
        })
        return ctx
