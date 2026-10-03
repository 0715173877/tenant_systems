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


def _unique_username(base: str, exclude_pk=None) -> str:
    """Return ``base`` or ``base-2``/``base-3``… so usernames stay unique.

    ``exclude_pk`` lets a user keep its own current username when checking for
    collisions (used when re-syncing a login after the phone number changes).
    """
    username = base
    suffix = 1
    while True:
        clash = User.objects.filter(username=username)
        if exclude_pk is not None:
            clash = clash.exclude(pk=exclude_pk)
        if not clash.exists():
            return username
        suffix += 1
        username = f"{base}-{suffix}"


def ensure_portal_account(tenant):
    """Create-and-link (or refresh) the portal login for ``tenant``.

    Returns the ``User`` or ``None`` when the tenant has no phone number. Safe
    to call repeatedly: once a user is linked the same account is reused.

    The phone number is used as both the username and the password, so when a
    tenant's phone number is edited later the linked login is re-synced to match
    it — otherwise the tenant could no longer sign in with their new number.
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
    elif user.username != phone or not user.check_password(phone):
        # Keep the phone-derived credentials in sync after an edit.
        if user.username != phone:
            user.username = _unique_username(phone, exclude_pk=user.pk)
        if not user.check_password(phone):
            user.set_password(phone)
        user.save()
        # Refresh the cached linked object so callers see the new username.
        tenant.user = user

    group, _ = Group.objects.get_or_create(name=TENANT_GROUP_NAME)
    user.groups.add(group)

    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])

    return user


@receiver(post_save, sender=Tenant)
def _sync_tenant_portal_account(sender, instance, **kwargs):
    """Auto-provision (and keep in sync) the login for a tenant."""
    ensure_portal_account(instance)
