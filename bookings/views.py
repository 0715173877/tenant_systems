import datetime
import logging
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.db.models import Q
from django.views.generic import TemplateView
from django.http import JsonResponse, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
import json
from .models import Guest, Booking
from properties.models import Unit, Block
from notifications.services import beem_client


# ---------- Guests ----------

class GuestListView(ListView):
    model = Guest
    template_name = "bookings/guest_list.html"
    context_object_name = "guests"
    paginate_by = 10

    def get_queryset(self):
        qs = Guest.objects.all()
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(full_name__icontains=q) | qs.filter(phone_number__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class GuestCreateView(CreateView):
    model = Guest
    fields = ["full_name", "phone_number", "email", "id_number", "is_active", "notes"]
    template_name = "bookings/guest_form.html"
    success_url = reverse_lazy("bookings:guest_list")

    def form_valid(self, form):
        messages.success(self.request, "Guest created successfully.")
        return super().form_valid(form)


class GuestUpdateView(UpdateView):
    model = Guest
    fields = ["full_name", "phone_number", "email", "id_number", "is_active", "notes"]
    template_name = "bookings/guest_form.html"
    success_url = reverse_lazy("bookings:guest_list")

    def form_valid(self, form):
        messages.success(self.request, "Guest updated successfully.")
        return super().form_valid(form)


# ---------- Bookings ----------

class BookingListView(ListView):
    model = Booking
    template_name = "bookings/booking_list.html"
    context_object_name = "bookings"
    paginate_by = 10

    def get_queryset(self):
        qs = Booking.objects.select_related("guest", "unit__block").all()
        status = self.request.GET.get("status")
        unit_id = self.request.GET.get("unit_id")
        if status:
            qs = qs.filter(status=status)
        if unit_id:
            qs = qs.filter(unit_id=unit_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["units"] = Unit.objects.filter(rental_type="short_term")
        ctx["current_unit"] = self.request.GET.get("unit_id", "")
        ctx["booking_statuses"] = Booking.STATUS_CHOICES
        return ctx


class BookingDetailView(DetailView):
    model = Booking
    template_name = "bookings/booking_detail.html"
    context_object_name = "booking"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        booking = self.get_object()
        ctx["payments"] = booking.payments.all()
        # Compute balance (since Django templates can't do subtraction)
        ctx["balance"] = (booking.total_amount or 0) - (booking.amount_paid or 0)
        ctx["booking_statuses"] = Booking.STATUS_CHOICES
        return ctx


class BookingCreateView(CreateView):
    model = Booking
    fields = [
        "guest", "unit", "check_in", "check_out",
        "number_of_guests", "nightly_rate_override",
        "cleaning_fee_override", "total_amount", "amount_paid",
        "status", "notes",
    ]
    template_name = "bookings/booking_form.html"
    success_url = reverse_lazy("bookings:booking_list")

    def form_valid(self, form):
        messages.success(self.request, "Booking created successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["short_term_units"] = Unit.objects.filter(rental_type="short_term")
        ctx["guests"] = Guest.objects.filter(is_active=True)
        return ctx


class BookingUpdateView(UpdateView):
    model = Booking
    fields = [
        "guest", "unit", "check_in", "check_out",
        "number_of_guests", "nightly_rate_override",
        "cleaning_fee_override", "total_amount", "amount_paid",
        "status", "notes",
    ]
    template_name = "bookings/booking_form.html"
    success_url = reverse_lazy("bookings:booking_list")

    def form_valid(self, form):
        messages.success(self.request, "Booking updated successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["short_term_units"] = Unit.objects.filter(rental_type="short_term")
        ctx["guests"] = Guest.objects.filter(is_active=True)
        return ctx


class BookingDeleteView(DeleteView):
    model = Booking
    template_name = "bookings/booking_confirm_delete.html"
    success_url = reverse_lazy("bookings:booking_list")

    def form_valid(self, form):
        messages.success(self.request, "Booking deleted successfully.")
        return super().form_valid(form)


# ---------- Calendar ----------

class BookingCalendarView(TemplateView):
    template_name = "bookings/calendar.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = datetime.date.today()
        month = self.request.GET.get("month", str(today.month))
        year = self.request.GET.get("year", str(today.year))
        try:
            month = int(month)
            year = int(year)
        except ValueError:
            month = today.month
            year = today.year

        # Get all short-term units
        units = Unit.objects.filter(rental_type="short_term").select_related("block")

        # Get bookings for this month
        first_day = datetime.date(year, month, 1)
        if month == 12:
            last_day = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
        else:
            last_day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

        bookings = Booking.objects.filter(
            Q(check_in__lte=last_day) & Q(check_out__gte=first_day),
            status__in=["pending", "confirmed", "checked_in", "checked_out"],
        ).select_related("guest", "unit")

        # Build unit_bookings: dict of unit identifier -> {date: status}
        unit_bookings = {}
        for unit in units:
            key = f"Unit {unit.unit_number}"
            unit_bookings[key] = {}

        for b in bookings:
            start = max(b.check_in, first_day)
            end = min(b.check_out, last_day)
            delta = (end - start).days
            for i in range(delta + 1):
                d = start + datetime.timedelta(days=i)
                key = f"Unit {b.unit.unit_number}"
                if key in unit_bookings:
                    unit_bookings[key][d] = b.status

        # Build days list for the month
        days = list(range(1, last_day.day + 1))

        # Build prev/next month navigation
        if month == 1:
            prev_month, prev_year = 12, year - 1
        else:
            prev_month, prev_year = month - 1, year
        if month == 12:
            next_month, next_year = 1, year + 1
        else:
            next_month, next_year = month + 1, year

        ctx.update({
            "units": units,
            "bookings": bookings,
            "unit_bookings": unit_bookings,
            "days": days,
            "prev_month": prev_month,
            "prev_year": prev_year,
            "next_month": next_month,
            "next_year": next_year,
            "month": month,
            "year": year,
            "month_name": [
                "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"
            ][month - 1],
            "today": today,
            "first_day": first_day,
            "last_day": last_day,
            "months": [
                (1, "January"), (2, "February"), (3, "March"),
                (4, "April"), (5, "May"), (6, "June"),
                (7, "July"), (8, "August"), (9, "September"),
                (10, "October"), (11, "November"), (12, "December"),
            ],
            "years": range(today.year - 1, today.year + 3),
        })
        return ctx


def booking_availability(request):
    """HTMX: Check availability for a date range."""
    check_in = request.GET.get("check_in")
    check_out = request.GET.get("check_out")
    template_name = "bookings/_availability_results.html"

    context = {"check_in": check_in, "check_out": check_out}
    if check_in and check_out:
        try:
            ci = datetime.date.fromisoformat(check_in)
            co = datetime.date.fromisoformat(check_out)
        except ValueError:
            context["error"] = "Invalid date format."
        else:
            if ci >= co:
                context["error"] = "Check-out must be after check-in."
            else:
                all_units = Unit.objects.filter(rental_type="short_term", is_available=True)
                booked_ids = Booking.objects.filter(
                    unit__rental_type="short_term",
                    status__in=["pending", "confirmed", "checked_in"],
                ).filter(
                    Q(check_in__lt=co) & Q(check_out__gt=ci)
                ).values_list("unit_id", flat=True).distinct()

                context["available_units"] = all_units.exclude(id__in=booked_ids)

    html = render_to_string(template_name, context, request=request)
    return HttpResponse(html)


@login_required
@require_POST
def booking_update_status(request, pk):
    """Quick-update a booking's status via POST and redirect back."""
    booking = get_object_or_404(Booking, pk=pk)
    new_status = request.POST.get("status")
    valid_statuses = dict(Booking.STATUS_CHOICES).keys()
    if new_status in valid_statuses:
        booking.status = new_status
        booking.save(update_fields=["status"])
        messages.success(
            request,
            f"Booking #{booking.pk} status changed to {dict(Booking.STATUS_CHOICES).get(new_status)}.",
        )
    else:
        messages.error(request, f"Invalid status: {new_status}")
    return redirect(request.META.get("HTTP_REFERER", "bookings:booking_list"))


@login_required
@require_POST
def quick_create_guest(request):
    """HTMX: Quick create a guest and return JSON with the new guest data."""
    try:
        data = json.loads(request.body)
        full_name = data.get("full_name", "").strip()
        phone_number = data.get("phone_number", "").strip()
        email = data.get("email", "").strip()
        id_number = data.get("id_number", "").strip()

        if not full_name:
            return JsonResponse({"error": "Full name is required."}, status=400)
        if not phone_number:
            return JsonResponse({"error": "Phone number is required."}, status=400)

        guest = Guest.objects.create(
            full_name=full_name,
            phone_number=phone_number,
            email=email,
            id_number=id_number,
            is_active=True,
        )
        return JsonResponse({
            "success": True,
            "guest": {"id": guest.pk, "name": guest.full_name},
        })
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def booking_send_sms(request, pk):
    """
    Send an SMS to the guest associated with a booking.
    POST with: message (the SMS text).
    """
    booking = get_object_or_404(Booking.objects.select_related("guest"), pk=pk)
    phone = booking.guest.phone_number
    message = request.POST.get("message", "").strip()

    if not phone:
        return JsonResponse({"success": False, "error": "Guest has no phone number."}, status=400)
    if not message:
        return JsonResponse({"success": False, "error": "Message is required."}, status=400)

    try:
        result = beem_client.send_sms(phone, message)
        logger = logging.getLogger(__name__)
        logger.info(
            "User %s sent SMS to guest %s (booking #%s)",
            request.user.username, booking.guest.full_name, booking.pk,
        )
        messages.success(request, f"SMS sent to {booking.guest.full_name} ({phone}).")
        return JsonResponse({"success": True, "result": result})
    except Exception as exc:
        logger = logging.getLogger(__name__)
        logger.error("SMS failed for booking #%s: %s", booking.pk, exc)
        return JsonResponse({"success": False, "error": str(exc)}, status=500)
