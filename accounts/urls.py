from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.LandlordSignUpView.as_view(), name="signup"),
    # Custom logout so the login page can explain why the user was signed out
    # (idle timeout / browser close). Registered here so it resolves before the
    # same path provided by django.contrib.auth.urls.
    path("logout/", views.PortalLogoutView.as_view(), name="logout"),
    # Called by the client-side idle watcher to keep the session alive.
    path("heartbeat/", views.heartbeat, name="heartbeat"),
]
