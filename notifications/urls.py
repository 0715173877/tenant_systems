from django.urls import path
from . import views

app_name = "notifications"

urlpatterns = [
    path("send-sms/", views.send_sms_view, name="send_sms"),
    path("settings/", views.notification_settings_view, name="settings"),
]
