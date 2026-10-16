from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView

from tenants.access import is_tenant

from .forms import LandlordSignUpForm


class PortalLoginView(LoginView):
    """Login that routes tenants to the portal, everyone else to the dashboard."""

    template_name = "registration/login.html"

    def get_success_url(self):
        if is_tenant(self.request.user):
            return reverse("portal:dashboard")
        return super().get_success_url()


class PortalLogoutView(LogoutView):
    """Sign the user out and return them to login with an explanatory notice.

    Handles the ``reason`` posted by the client-side idle watcher
    (``static/js/idle-logout.js``) so the login page can explain *why* the user
    was signed out (idle timeout, browser close, or a manual sign-out).
    """

    # Django 5 removes GET-based logout for security; we still accept GET so a
    # stray link cannot end a session, and simply bounce the user to login.
    http_method_names = ["get", "post", "options"]

    def get(self, request, *args, **kwargs):
        return redirect(self.get_success_url())

    def post(self, request, *args, **kwargs):
        reason = request.POST.get("reason", "")
        # logout() flushes the session, so the notice must be added afterwards;
        # the messages framework stores it in the freshly created session.
        logout(request)
        if reason == "idle":
            messages.info(
                request,
                "You were signed out automatically after a period of inactivity.",
            )
        elif reason == "browser":
            messages.info(
                request,
                "You were signed out because the browser was closed.",
            )
        elif reason == "tab":
            messages.info(
                request,
                "You were signed out because this browser tab was closed.",
            )
        else:
            messages.success(request, "You have been signed out. See you soon!")
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("login")


@login_required
def heartbeat(request):
    """Lightweight endpoint used by the idle watcher to keep a session alive.

    Because ``SESSION_SAVE_EVERY_REQUEST`` is enabled, any authenticated request
    slides the server-side session expiry forward — so this simply needs to
    return 200 for the "Stay signed in" action to work.
    """
    return JsonResponse({"ok": True})


class LandlordSignUpView(CreateView):
    """Public registration page for new landlords (property owners)."""

    form_class = LandlordSignUpForm
    template_name = "accounts/signup.html"
    success_url = reverse_lazy("dashboard")

    def dispatch(self, request, *args, **kwargs):
        # Already-authenticated users don't need to sign up.
        if request.user.is_authenticated:
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        # Log the new landlord in and send them to their (empty) dashboard.
        login(self.request, self.object)
        messages.success(
            self.request,
            "Welcome! Your landlord account is ready. Start by adding a property.",
        )
        return response
