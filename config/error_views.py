"""Friendly, on-brand error pages (403 / 404 / 500).

Django's built-in pages are bare (``<h1>403 Forbidden</h1>``). These handlers
reuse the application layout so a user who lacks permission sees *why* access
was refused, which role they are signed in as, and a way back into the app.

Wired up in ``config/urls.py`` via ``handler403`` / ``handler404`` /
``handler500``.
"""
import logging

from django.http import HttpResponseServerError
from django.shortcuts import render
from django.template import TemplateDoesNotExist
from django.views import defaults as default_views

from properties.access import describe_roles

logger = logging.getLogger(__name__)


def _status_context(
    request,
    *,
    status_code,
    status_icon,
    status_tone,
    status_title,
    status_text,
    detail="",
):
    """Build the context consumed by ``partials/status_page.html``."""
    return {
        "status_code": status_code,
        "status_icon": status_icon,
        "status_tone": status_tone,
        "status_title": status_title,
        "status_text": status_text,
        "status_detail": detail,
        "status_roles": describe_roles(getattr(request, "user", None)),
    }


def permission_denied(request, exception, template_name="403.html"):
    """403 handler: explain the refusal instead of showing a bare error."""
    message = str(exception).strip() if exception else ""
    try:
        context = _status_context(
            request,
            status_code=403,
            status_icon="shield-lock",
            status_tone="danger",
            status_title="Access denied",
            status_text="You do not have permission to open this page.",
            detail=message,
        )
        return render(request, template_name, context, status=403)
    except TemplateDoesNotExist:
        # No custom template available -> fall back to Django's plain response.
        return default_views.permission_denied(request, exception)


def page_not_found(request, exception, template_name="404.html"):
    """404 handler: friendly not-found page."""
    try:
        context = _status_context(
            request,
            status_code=404,
            status_icon="compass",
            status_tone="warning",
            status_title="Page not found",
            status_text=(
                "We couldn't find the page you were looking for. "
                "It may have been moved or deleted."
            ),
        )
        return render(request, template_name, context, status=404)
    except TemplateDoesNotExist:
        return default_views.page_not_found(request, exception)


def server_error(request, template_name="500.html"):
    """500 handler: a calm apology rather than a stack-trace page."""
    try:
        context = _status_context(
            request,
            status_code=500,
            status_icon="exclamation-octagon",
            status_tone="danger",
            status_title="Something went wrong",
            status_text=(
                "An unexpected error occurred on our side. "
                "Please try again in a moment."
            ),
        )
        return render(request, template_name, context, status=500)
    except Exception:  # pragma: no cover - last-resort safety net
        logger.exception("Could not render the 500 error page")
        return HttpResponseServerError(
            "<!doctype html><title>Server error</title>"
            "<h1>Something went wrong</h1>"
            "<p>Please try again in a moment.</p>"
        )
