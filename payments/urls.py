from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("", views.PaymentListView.as_view(), name="payment_list"),
    path("<int:pk>/", views.PaymentDetailView.as_view(), name="payment_detail"),
    path("create/", views.PaymentCreateView.as_view(), name="payment_create"),
    path("<int:pk>/edit/", views.PaymentUpdateView.as_view(), name="payment_edit"),
    path("<int:pk>/delete/", views.PaymentDeleteView.as_view(), name="payment_delete"),
    path("report/", views.PaymentReportView.as_view(), name="report"),
]
