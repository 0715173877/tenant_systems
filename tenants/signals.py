"""Signals that keep tenant portal logins in sync with tenant records.

Every ``Tenant`` gets a login account so they can use the tenant portal. The
credentials are intentionally simple: the phone number is used as *both* the
username and the initial password, so a tenant can sign in immediately after
the landlord adds them.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Tenant

User = get_user_model()

#: Name of the auth group that marks a user as a tenant (portal-only access).
TENANT_GROUP_NAME = "tenant"


def _unique_username(base: str) -> str:
    """Return ``base`` or ``base-2``/``base-3``… so usernames stay unique."""
    username = base
    suffix = 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{base}-{suffix}"
    return username


def ensure_portal_account(tenant):
    """Create-and-link (or reuse) the portal login for ``tenant``.

    Returns the ``User`` or ``None`` when the tenant has no phone number.
    Safe to call repeatedly: once a user is linked the same account is reused.
    """
    phone = (tenant.phone_number or "").strip()
    if not phone:
        return None

    user = tenant.user
    if user is None:
        user = User.objects.create_user(
            username=_unique_username(phone), password=phone
        )
        # ``update`` avoids re-triggering this signal.
        Tenant.objects.filter(pk=tenant.pk).update(user=user)
        tenant.user = user

    group, _ = Group.objects.get_or_create(name=TENANT_GROUP_NAME)
    user.groups.add(group)

    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])

    return user


@receiver(post_save, sender=Tenant)
def _create_tenant_portal_account(sender, instance, **kwargs):
    """Auto-provision a login for any tenant that does not have one yet."""
    if instance.user_id is None:
        ensure_portal_account(instance)
