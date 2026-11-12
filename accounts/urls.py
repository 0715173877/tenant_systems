from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.LandlordSignUpView.as_view(), name="signup"),
    # Self-service password change for any signed-in user (tenant or staff).
    path(
        "password/change/",
        views.UserPasswordChangeView.as_view(),
        name="password_change",
    ),
    # django.contrib.auth.urls also registers ``password_change/`` but ships no
    # template for it; forward that path to our own page instead of a 500.
    path(
        "password_change/",
        RedirectView.as_view(
            pattern_name="accounts:password_change", permanent=False
        ),
        name="password_change_legacy",
    ),
    # Custom logout so the login page can explain why the user was signed out
    # (idle timeout / browser close). Registered here so it resolves before the
    # same path provided by django.contrib.auth.urls.
    path("logout/", views.PortalLogoutView.as_view(), name="logout"),
    # Called by the client-side idle watcher to keep the session alive.
    path("heartbeat/", views.heartbeat, name="heartbeat"),
]
