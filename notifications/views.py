import json
import logging
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .services import beem_client
from .models import NotificationSetting
from .tasks import send_lease_expiry_reminders

logger = logging.getLogger(__name__)


def _can_manage_sms(user):
    """Check if user is superuser/staff, owner, or manager."""
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name__in=["owner", "manager"]).exists()


@login_required
@csrf_exempt
def send_sms_view(request):
    """
    AJAX endpoint to send an SMS from the dashboard.
    POST with: phone, message, name (optional), type (optional)
    Restricted to admin, owner, and manager roles.
    """
    if not _can_manage_sms(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Only POST allowed"}, status=405)

    phone = request.POST.get("phone", "").strip()
    message = request.POST.get("message", "").strip()

    if not phone:
        return JsonResponse({"success": False, "error": "Phone number is required"}, status=400)
    if not message:
        return JsonResponse({"success": False, "error": "Message is required"}, status=400)

    try:
        result = beem_client.send_sms(phone, message)
        # Log the action
        logger.info(
            "User %s sent SMS to %s (type=%s)",
            request.user.username, phone, request.POST.get("type", ""),
        )
        return JsonResponse({"success": True, "result": result})
    except Exception as exc:
        logger.error("SMS failed from dashboard user %s: %s", request.user.username, exc)
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


@login_required
def notification_settings_view(request):
    """
    View to update automated SMS notification settings.
    Restricted to admin, owner, and manager roles.
    Uses a singleton pattern - creates NotificationSetting if it doesn't exist.
    """
    if not _can_manage_sms(request.user):
        return HttpResponseForbidden("You do not have permission to access SMS settings.")

    ns, created = NotificationSetting.objects.get_or_create(pk=1)

    if request.method == "POST":
        # Lease expiry settings
        ns.lease_expiry_enabled = request.POST.get("lease_expiry_enabled") == "on"
        try:
            ns.lease_expiry_days_before = int(request.POST.get("lease_expiry_days_before", 14))
        except (ValueError, TypeError):
            ns.lease_expiry_days_before = 14
        try:
            ns.lease_expiry_hour = int(request.POST.get("lease_expiry_hour", 9))
        except (ValueError, TypeError):
            ns.lease_expiry_hour = 9
        try:
            ns.lease_expiry_minute = int(request.POST.get("lease_expiry_minute", 0))
        except (ValueError, TypeError):
            ns.lease_expiry_minute = 0
        ns.lease_expiry_message_template = request.POST.get(
            "lease_expiry_message_template",
            ns.lease_expiry_message_template,
        )

        # Rent reminder settings
        ns.rent_reminder_enabled = request.POST.get("rent_reminder_enabled") == "on"
        try:
            ns.rent_reminder_days_before = int(request.POST.get("rent_reminder_days_before", 3))
        except (ValueError, TypeError):
            ns.rent_reminder_days_before = 3
        try:
            ns.rent_reminder_hour = int(request.POST.get("rent_reminder_hour", 8))
        except (ValueError, TypeError):
            ns.rent_reminder_hour = 8
        try:
            ns.rent_reminder_minute = int(request.POST.get("rent_reminder_minute", 0))
        except (ValueError, TypeError):
            ns.rent_reminder_minute = 0
        ns.rent_reminder_message_template = request.POST.get(
            "rent_reminder_message_template",
            ns.rent_reminder_message_template,
        )

        ns.save()
        messages.success(request, "Notification settings updated successfully.")
        return redirect("notifications:settings")

    context = {
        "settings": ns,
    }
    return render(request, "notifications/settings.html", context)
