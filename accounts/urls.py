from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.LandlordSignUpView.as_view(), name="signup"),
]
