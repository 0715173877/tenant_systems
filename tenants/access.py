"""Helpers for the tenant portal (tenant-facing access).

While ``properties.access`` isolates *landlord* data (owners and their staff),
this module isolates the *tenant* surface: a signed-in tenant can only ever see
the records that hang off their own :class:`~tenants.models.Tenant` row.

A portal tenant is identified by the ``tenant`` auth group **and** a linked
``Tenant`` record (``Tenant.user``). Both are created automatically when a
tenant is added.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect

from .models import Tenant
from .signals import TENANT_GROUP_NAME


def is_tenant(user) -> bool:
    """True when ``user`` is a portal tenant (member of the ``tenant`` group)."""
    if not user or not user.is_authenticated:
        return False
    return user.groups.filter(name=TENANT_GROUP_NAME).exists()


def get_tenant_for_user(user):
    """Return the ``Tenant`` linked to ``user``, or ``None``."""
    if not user or not user.is_authenticated:
        return None
    return Tenant.objects.filter(user=user).first()


class TenantPortalMixin(LoginRequiredMixin):
    """Restrict a view to a signed-in tenant and expose ``self.tenant``.

    Anonymous users are sent to the login page. Authenticated non-tenants
    (landlords, staff, superusers) are redirected to the landlord dashboard
    with a message — the portal is not their surface.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.tenant = get_tenant_for_user(request.user)
        if self.tenant is None:
            messages.warning(
                request, "The tenant portal is only available to tenant accounts."
            )
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)
