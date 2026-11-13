from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import render, redirect
from decimal import Decimal

from django.db.models import Count, Exists, OuterRef, Prefetch, Q, Sum
from datetime import date, timedelta, datetime
from django.contrib.auth.decorators import login_required
from django.views.generic import RedirectView
from properties.models import Property, Block, Unit
from properties.access import is_owner, user_can
from tenants.models import Tenant, Lease
from tenants.access import is_tenant
import accounts.views as account_views
from bookings.models import Booking
from payments.models import Payment
from config.pwa_views import service_worker


# Friendly, on-brand error pages (see config/error_views.py).
handler403 = "config.error_views.permission_denied"
handler404 = "config.error_views.page_not_found"
handler500 = "config.error_views.server_error"


@login_required
def dashboard(request):
    """Dashboard view with summary statistics per property."""
    today = date.today()
    user = request.user

    # Tenant portal accounts have their own home page; send them there instead
    # of showing them the landlord dashboard (which would be empty for them).
    if (
        is_tenant(user)
        and not user.is_superuser
        and not is_owner(user)
        and not user.staff_assignments.filter(is_active=True).exists()
    ):
        return redirect("portal:dashboard")

    # Retire leases that have run past their end date before tallying stats.
    Lease.objects.expire_past_due()

    # Determine which properties this user can see
    if user.is_authenticated:
        if user.is_superuser:
            properties = Property.objects.all()
        elif user.groups.filter(name="owner").exists():
            properties = Property.objects.filter(owner=user)
        else:
            properties = Property.objects.filter(
                staff__user=user, staff__is_active=True
            )
    else:
        properties = Property.objects.none()

    # Apply property filter if specified
    property_id = request.GET.get("property")
    if property_id:
        properties = properties.filter(id=property_id)

    # Global stats across all accessible properties
    total_properties = properties.count()
    total_units = Unit.objects.filter(
        block__property__in=properties
    ).count()
    active_tenants = Tenant.objects.filter(
        is_active=True, property__in=properties
    ).count()
    total_tenants = Tenant.objects.filter(
        property__in=properties
    ).count()
    active_leases = Lease.objects.filter(
        status="active", unit__block__property__in=properties
    ).count()
    active_bookings = Booking.objects.filter(
        status__in=["confirmed", "checked_in", "pending"],
        unit__block__property__in=properties,
    ).count()

    payment_agg = Payment.objects.filter(
        Q(lease__unit__block__property__in=properties) |
        Q(booking__unit__block__property__in=properties),
        status="completed",
    ).aggregate(total=Sum("amount"), count=Count("id"))
    total_income = payment_agg["total"] or 0
    payment_count = payment_agg["count"] or 0

    # Blocks with occupancy
    blocks = list(
        Block.objects.filter(property__in=properties)
        .prefetch_related("units")
        .select_related("property")
    )
    for block in blocks:
        units = list(block.units.all())
        block.unit_count = len(units)
        occupied_lt = Lease.objects.filter(
            unit__block=block, status="active"
        ).count()
        occupied_st = Booking.objects.filter(
            unit__block=block,
            status__in=["confirmed", "checked_in"],
        ).values("unit").distinct().count()
        block.occupied_count = occupied_lt + occupied_st

    # Recent payments (last 8)
    recent_payments = Payment.objects.filter(
        Q(lease__unit__block__property__in=properties) |
        Q(booking__unit__block__property__in=properties)
    ).select_related(
        "lease__tenant", "booking__guest"
    ).order_by("-payment_date")[:8]

    # Pending payments count
    pending_payments = Payment.objects.filter(
        Q(lease__unit__block__property__in=properties) |
        Q(booking__unit__block__property__in=properties),
        status="pending",
    ).count()

    # Recent bookings (last 8 created)
    recent_bookings = Booking.objects.filter(
        unit__block__property__in=properties,
    ).select_related("guest", "unit").order_by("-created_at")[:8]

    # Upcoming bookings (future check-ins)
    upcoming_bookings = Booking.objects.filter(
        status__in=["confirmed", "pending"],
        check_in__gte=today,
        unit__block__property__in=properties,
    ).select_related("guest", "unit").order_by("check_in")[:8]

    # Upcoming check-outs (bookings ending within 7 days)
    upcoming_checkouts = Booking.objects.filter(
        status__in=["confirmed", "checked_in"],
        check_out__gte=today,
        check_out__lte=today + timedelta(days=7),
        unit__block__property__in=properties,
    ).select_related("guest", "unit").order_by("check_out")[:8]

    # Expiring leases (within 60 days)
    expiring_leases_qs = Lease.objects.filter(
        status="active",
        end_date__lte=today + timedelta(days=60),
        unit__block__property__in=properties,
    ).select_related("tenant", "unit").order_by("end_date")[:8]
    expiring_leases_count = Lease.objects.filter(
        status="active",
        end_date__lte=today + timedelta(days=60),
        unit__block__property__in=properties,
    ).count()

    # Urgent: expired leases without a successor contract. They stay in
    # Notifications & Reminders until the tenant signs a new lease or the unit
    # is given to another lease (a newer contract supersedes this one), no
    # matter how much of the old contract was paid.
    newer_lease = (
        Lease.objects.filter(
            Q(tenant=OuterRef("tenant")) | Q(unit=OuterRef("unit")),
        )
        .exclude(pk=OuterRef("pk"))
        .filter(
            Q(status="active")
            | (Q(start_date__gte=OuterRef("end_date")) & ~Q(status="terminated"))
        )
    )
    expired_candidates = (
        Lease.objects.filter(
            status="expired", unit__block__property__in=properties
        )
        .annotate(has_newer_lease=Exists(newer_lease))
        .filter(has_newer_lease=False)
        .select_related("tenant", "unit__block__property")
        .prefetch_related(
            "invoices",
            Prefetch(
                "payments",
                queryset=Payment.objects.filter(
                    status="completed", payment_type="rent"
                ),
                to_attr="completed_rent_payments",
            ),
        )
        .order_by("end_date")
    )

    ended_unpaid_leases = []
    for lease in expired_candidates:
        invoices = list(lease.invoices.all())
        if invoices:
            rent_due = sum((inv.amount for inv in invoices), Decimal("0"))
            invoice_paid = sum(
                (inv.amount_paid for inv in invoices), Decimal("0")
            )
        else:
            # Legacy lease without generated invoices: assume at least one
            # month of rent is due for the term.
            rent_due = lease.monthly_rent * max(lease.duration_months, 1)
            invoice_paid = Decimal("0")
        payments_paid = sum(
            (payment.amount for payment in lease.completed_rent_payments),
            Decimal("0"),
        )
        # ``amount_paid`` on the invoice and completed rent payments both
        # represent the same money; take the larger so a payment recorded
        # through the payments module is reflected even when the invoice was
        # not updated.
        received = max(invoice_paid, payments_paid)
        lease.outstanding = max(rent_due - received, Decimal("0"))
        lease.rent_received_since_end = any(
            payment.payment_date > lease.end_date
            for payment in lease.completed_rent_payments
        )
        # Every expired lease without a successor stays listed - even when the
        # old contract was fully paid - until the tenant signs a new lease or
        # the unit is re-let.
        ended_unpaid_leases.append(lease)

    ended_unpaid_leases_count = len(ended_unpaid_leases)
    ended_unpaid_leases = ended_unpaid_leases[:8]

    # Active leases list for dashboard card
    active_leases_list = Lease.objects.filter(
        status="active",
        unit__block__property__in=properties,
    ).select_related("tenant", "unit").order_by("-start_date")[:8]

    # Occupied units
    occupied_long_term = Lease.objects.filter(
        status="active",
        unit__block__property__in=properties,
    ).count()
    occupied_short_term = Booking.objects.filter(
        status__in=["confirmed", "checked_in"],
        unit__block__property__in=properties,
    ).values("unit").distinct().count()
    occupied_units = occupied_long_term + occupied_short_term

    total_guests_count = Booking.objects.filter(
        status__in=["confirmed", "checked_in", "pending"],
        unit__block__property__in=properties,
    ).values("guest").distinct().count()

    # Hide the widgets a role cannot open so the dashboard never links to a page
    # that would answer with a 403 (see properties.access.ROLE_CAPABILITIES).
    if not user_can(user, "bookings_view"):
        recent_bookings = []
        upcoming_bookings = []
        upcoming_checkouts = []
    if not user_can(user, "leases_view"):
        active_leases_list = []
        expiring_leases_qs = []
        expiring_leases_count = 0
        ended_unpaid_leases = []
        ended_unpaid_leases_count = 0

    # One total for the "Notifications & Reminders" badge (the template used to
    # chain |add filters, which silently collapsed to 0).
    notifications_count = (
        expiring_leases_count
        + len(upcoming_checkouts)
        + len(upcoming_bookings)
        + ended_unpaid_leases_count
    )

    return render(request, "dashboard.html", {
        "now": datetime.now(),
        "total_properties": total_properties,
        "total_units": total_units,
        "total_tenants": total_tenants,
        "total_blocks": Block.objects.filter(property__in=properties).count(),
        "active_tenants": active_tenants,
        "occupied_units": occupied_units,
        "empty_units": max(0, total_units - occupied_units),
        "active_bookings": active_bookings,
        "active_leases": active_leases,
        "total_guests": total_guests_count,
        "monthly_revenue": total_income,
        "total_payments": payment_count,
        "pending_payments": pending_payments,
        "occupancy_rate": (occupied_units / total_units * 100) if total_units > 0 else 0,
        "blocks": blocks,
        "selected_property": properties.first() if property_id else None,
        "recent_payments": recent_payments,
        "recent_bookings": recent_bookings,
        "upcoming_bookings": upcoming_bookings,
        "upcoming_checkouts": upcoming_checkouts,
        "expiring_leases": expiring_leases_qs,
        "expiring_leases_count": expiring_leases_count,
        "ended_unpaid_leases": ended_unpaid_leases,
        "ended_unpaid_leases_count": ended_unpaid_leases_count,
        "notifications_count": notifications_count,
        "active_leases_list": active_leases_list,
        "properties": properties,
    })


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", account_views.PortalLoginView.as_view(), name="login"),
    path("accounts/", include("accounts.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", dashboard, name="dashboard"),
    path("portal/", include("portal.urls")),
    path("properties/", include("properties.urls")),
    path("tenants/", include("tenants.urls")),
    path("bookings/", include("bookings.urls")),
    path("notifications/", include("notifications.urls")),
    path("payments/", include("payments.urls")),
    path("finance/", include("finance.urls")),
    # PWA / iOS convenience icons (browsers probe these root paths)
    path("favicon.ico", RedirectView.as_view(url="/static/img/icons/icon-192x192.png", permanent=True)),
    path("apple-touch-icon.png", RedirectView.as_view(url="/static/img/icons/icon-192x192.png", permanent=True)),
    path("apple-touch-icon-precomposed.png", RedirectView.as_view(url="/static/img/icons/icon-192x192.png", permanent=True)),
    # Service worker served from the root so its scope is the whole site.
    path("sw.js", service_worker, name="service_worker"),
]


# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
