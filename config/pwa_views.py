"""Views that expose PWA assets at the site root.

A service worker's scope is limited to the path it is served from. If we served
``sw.js`` from ``/static/sw.js`` its scope would be ``/static/`` only, so the
application pages (``/``, ``/properties/``, ``/tenants/`` ...) would never be
controlled by the worker. That breaks offline support and can prevent the app
from being installable ("Add to Home screen").

We therefore serve the worker from ``/sw.js`` so its scope covers the entire
site. The ``Service-Worker-Allowed`` header makes the intent explicit.
"""
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse


def service_worker(request):
    """Serve the service worker from the site root so scope is "/"."""
    sw_path = Path(settings.BASE_DIR) / "static" / "sw.js"
    if not sw_path.exists():
        raise Http404("Service worker not found")

    response = HttpResponse(
        sw_path.read_text(encoding="utf-8"),
        content_type="application/javascript",
    )
    # Allow the worker to control the whole origin (not just its own directory).
    response["Service-Worker-Allowed"] = "/"
    # Never cache the worker itself, so updates are picked up promptly.
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response
