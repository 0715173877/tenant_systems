from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView

from .forms import LandlordSignUpForm


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
