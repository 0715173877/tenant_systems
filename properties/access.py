"""
Central helpers for per-landlord (owner) data isolation.

Every app that exposes owner data (properties, tenants, bookings, payments,
finance, notifications) must funnel its querysets through these helpers so a
logged-in landlord can only ever see / act on their own records.

Access rules
------------
* superuser            -> all properties
* ``owner`` group      -> properties they own (``Property.owner``)
* any other user      -> properties they are actively assigned to via
                         ``PropertyStaff`` (managers, receptionists, ...)
* anonymous           -> nothing
"""
from functools import wraps

from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef

from .models import Property, PropertyStaff

# Roles a property manager may grant/manage. A manager can never create or
# edit another manager (nor an owner), which keeps them from escalating access.
MANAGER_ASSIGNABLE_ROLES = ("accountant", "receptionist")

# Human-readable labels for every role a user can hold, in descending order of
# privilege. Used to describe who someone is on the "access denied" page.
ROLE_LABELS = {
    "owner": "Owner",
    "manager": "Manager",
    "accountant": "Accountant",
    "receptionist": "Receptionist",
    "tenant": "Tenant",
}
ROLE_ORDER = ("owner", "manager", "accountant", "receptionist", "tenant")

# ---------------------------------------------------------------------------
# Role capabilities (what each role may *do*, not just which records it sees)
# ---------------------------------------------------------------------------
# Property scoping (which properties a user may touch) is handled above. This
# matrix decides which *sections of the app* a role may open at all, so a
# receptionist no longer gets the same surface as an accountant.
#
# ``owner`` and superusers implicitly hold every capability; ``tenant`` gets
# none of the back-office capabilities (they use the separate tenant portal).
#
# Adding a section: add the capability here for every role that should reach it,
# then annotate the view(s) with ``<X>ViewMixin``/``<X>ManageMixin`` and gate the
# sidebar link in ``templates/base.html`` with ``{% if '<capability>' in
# capabilities %}``.
ROLE_CAPABILITIES = {
    # Managers run the properties day-to-day. Only the owner payment profile
    # (property create/edit/delete are owner-only too) is out of reach.
    "manager": {
        "properties_view",
        "properties_manage",
        "staff_manage",
        "maintenance_view",
        "maintenance_manage",
        "tenants_view",
        "tenants_manage",
        "leases_view",
        "leases_manage",
        "rent_view",
        "rent_manage",
        "bookings_view",
        "bookings_manage",
        "payments_view",
        "payments_manage",
        "payments_report",
        "finance_view",
        "finance_manage",
        "sms_settings",
    },
    # Accountants work the money: rent & arrears, payments, expenses, purchases,
    # stock and reporting. They get read-only context on properties/tenants/
    # leases but cannot change the estate or the people side of it.
    "accountant": {
        "properties_view",
        "tenants_view",
        "leases_view",
        "rent_view",
        "rent_manage",
        "payments_view",
        "payments_manage",
        "payments_report",
        "finance_view",
        "finance_manage",
    },
    # Receptionists run the front desk: tenants, leases, bookings, guests,
    # maintenance and day-to-day payment capture. Finance, staffing, reports
    # and rent-invoice administration stay with owner/manager/accountant.
    "receptionist": {
        "properties_view",
        "maintenance_view",
        "maintenance_manage",
        "tenants_view",
        "tenants_manage",
        "leases_view",
        "leases_manage",
        "bookings_view",
        "bookings_manage",
        "payments_view",
        "payments_manage",
    },
}

# Every capability that exists, whether granted to a staff role or not.
ALL_CAPABILITIES = frozenset(
    capability for capabilities in ROLE_CAPABILITIES.values() for capability in capabilities
)

# Noun phrases used by the friendly 403 page ("Your role (Receptionist) cannot
# access the Finance section.").
CAPABILITY_LABELS = {
    "properties_view": "the Properties section",
    "properties_manage": "managing properties, blocks and units",
    "staff_manage": "the Staff section",
    "maintenance_view": "the Maintenance section",
    "maintenance_manage": "updating maintenance requests",
    "tenants_view": "the Tenants section",
    "tenants_manage": "adding or editing tenants",
    "leases_view": "the Leases section",
    "leases_manage": "adding or editing leases",
    "rent_view": "the Rent & Arrears section",
    "rent_manage": "generating invoices or recording rent payments",
    "bookings_view": "the Bookings section",
    "bookings_manage": "adding or editing bookings and guests",
    "payments_view": "the Payments section",
    "payments_manage": "adding or editing payments",
    "payments_report": "the Payments Report",
    "finance_view": "the Finance section",
    "finance_manage": "adding or editing finance records",
    "sms_settings": "SMS settings",
}

# Roles that participate in the capability matrix above. ``tenant`` is excluded
# on purpose: tenant accounts live in the separate ``portal`` app.
STAFF_ROLE_NAMES = ("owner", "manager", "accountant", "receptionist")


def describe_roles(user):
    """Human-readable list of the roles ``user`` holds (for UI / error pages).

    Combines Django group membership (owner/tenant/...) with active
    ``PropertyStaff`` roles so a user is described correctly even if the two
    ever drift apart. Returns ``[]`` for anonymous users or users with no role.
    """
    if not user or not user.is_authenticated:
        return []
    if user.is_superuser:
        return ["Superuser"]

    roles = set(user.groups.values_list("name", flat=True))
    roles |= set(
        PropertyStaff.objects.filter(user=user, is_active=True).values_list(
            "role", flat=True
        )
    )
    return [ROLE_LABELS[role] for role in ROLE_ORDER if role in roles]


# ---------- Capability checks ----------

def get_user_roles(user):
    """The role names ``user`` effectively holds, as a ``set``.

    Combines Django group membership with active ``PropertyStaff`` rows, so a
    user whose group row is missing but who is assigned as (say) an accountant
    is still treated as one. Returns ``{"superuser"}`` for superusers and an
    empty set for anonymous users / users with no role at all.
    """
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return {"superuser"}

    roles = set(user.groups.values_list("name", flat=True))
    roles |= set(
        PropertyStaff.objects.filter(user=user, is_active=True).values_list(
            "role", flat=True
        )
    )
    return roles & set(STAFF_ROLE_NAMES)


def get_capabilities(user):
    """Every capability ``user`` holds, as a ``set`` (used for UI gating)."""
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser or is_owner(user):
        return set(ALL_CAPABILITIES)

    capabilities = set()
    for role in get_user_roles(user):
        capabilities |= ROLE_CAPABILITIES.get(role, set())
    return capabilities


def user_can(user, capability: str) -> bool:
    """True if ``user``'s role grants ``capability``.

    Owners and superusers always pass; a user whose roles do not include the
    capability is denied even when they are a logged-in staff member.
    """
    if not user or not user.is_authenticated or not capability:
        return False
    if user.is_superuser or is_owner(user):
        return True
    return capability in get_capabilities(user)


def capability_denial_message(user, capability):
    """A friendly explanation shown on the 403 page."""
    roles = ", ".join(describe_roles(user)) or "No assigned role"
    label = CAPABILITY_LABELS.get(capability, "this section")
    return (
        f"Your role ({roles}) does not have access to {label}. "
        "Ask an owner or manager if you need it."
    )


def is_owner(user) -> bool:
    """True if the user is in the ``owner`` group."""
    if not user or not user.is_authenticated:
        return False
    return user.groups.filter(name="owner").exists()


def is_manager(user) -> bool:
    """True if the user is an active manager on at least one property."""
    if not user or not user.is_authenticated:
        return False
    return PropertyStaff.objects.filter(
        user=user, role="manager", is_active=True
    ).exists()


def get_accessible_properties(user):
    """Return the ``Property`` queryset a user is allowed to access."""
    if not user or not user.is_authenticated:
        return Property.objects.none()
    if user.is_superuser:
        return Property.objects.all()
    if is_owner(user):
        return Property.objects.filter(owner=user)
    # Staff / managers: only properties they are actively assigned to.
    return Property.objects.filter(
        staff__user=user, staff__is_active=True
    ).distinct()


def get_accessible_property_ids(user):
    """Return a list of property ids the user can access."""
    return list(get_accessible_properties(user).values_list("id", flat=True))


# ---------- Staff administration ----------

def get_managed_properties(user):
    """Properties the user administers, i.e. can assign staff to.

    * superuser -> every property
    * owner     -> the properties they own
    * manager   -> the properties where they hold an active *manager* role
    * anyone else -> none
    """
    if not user or not user.is_authenticated:
        return Property.objects.none()
    if user.is_superuser:
        return Property.objects.all()
    if is_owner(user):
        return Property.objects.filter(owner=user)
    if is_manager(user):
        return Property.objects.filter(
            staff__user=user, staff__is_active=True, staff__role="manager"
        ).distinct()
    return Property.objects.none()


def can_manage_staff(user) -> bool:
    """True if the user may add/edit/remove staff (owner, manager or superuser)."""
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or is_owner(user) or is_manager(user)


def assignable_roles(user):
    """The role choices a user may grant when adding or editing staff.

    Owners/superusers may grant any role; managers only the day-to-day roles
    (accountant, receptionist) so they cannot create peers or owners.
    """
    if not user or not user.is_authenticated:
        return []
    if user.is_superuser or is_owner(user):
        return list(PropertyStaff.STAFF_ROLES)
    if is_manager(user):
        return [
            role for role in PropertyStaff.STAFF_ROLES
            if role[0] in MANAGER_ASSIGNABLE_ROLES
        ]
    return []


def get_manageable_staff(user):
    """``PropertyStaff`` rows the user may list, edit, toggle or remove."""
    qs = PropertyStaff.objects.select_related("user", "property")
    if not user or not user.is_authenticated:
        return qs.none()
    if user.is_superuser:
        return qs
    if is_owner(user):
        return qs.filter(property__owner=user)
    if not is_manager(user):
        return qs.none()

    managed = get_managed_properties(user)
    # A manager may only touch staff whose every assignment lies inside their
    # own scope, so they can never edit an owner or another manager.
    out_of_scope = PropertyStaff.objects.filter(user_id=OuterRef("user_id")).exclude(
        property__in=managed, role__in=MANAGER_ASSIGNABLE_ROLES
    )
    return qs.filter(
        property__in=managed, role__in=MANAGER_ASSIGNABLE_ROLES
    ).filter(~Exists(out_of_scope))


class PropertyScopedMixin:
    """Reusable mixin that scopes a CBV queryset to the user's properties.

    Subclasses set ``property_filter`` to the ORM lookup that reaches a
    ``Property`` from the view's model, e.g. ``"property__in"`` (default) or
    ``"unit__block__property__in"``.
    """

    property_filter = "property__in"

    def get_property_queryset(self):
        return get_accessible_properties(self.request.user)

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(**{self.property_filter: self.get_property_queryset()})


# ---------- Capability enforcement ----------

class CapabilityRequiredMixin(UserPassesTestMixin):
    """Deny access unless the user's role grants ``required_capability``.

    Pairs with :data:`ROLE_CAPABILITIES`: the section mixins below just pin a
    capability name, so a view declares *what it is* rather than re-implementing
    role logic. Anonymous users are still redirected to the login page by
    ``UserPassesTestMixin``; logged-in users without the capability get the
    friendly 403 page (see ``config/error_views.py``).
    """

    # e.g. "finance_view" — set by the section mixins below.
    required_capability = None

    def test_func(self):
        return user_can(self.request.user, self.required_capability)

    def get_permission_denied_message(self):
        return capability_denial_message(self.request.user, self.required_capability)


def make_capability_mixin(capability):
    """Build a ``CapabilityRequiredMixin`` subclass pinned to ``capability``.

    Convenience for one-off views; the named section mixins below cover the
    standard sections.
    """
    return type(
        "CapabilityRequiredMixin_" + capability,
        (CapabilityRequiredMixin,),
        {"required_capability": capability},
    )


class PropertiesViewMixin(CapabilityRequiredMixin):
    """Properties / blocks / units — read."""
    required_capability = "properties_view"


class PropertiesManageMixin(CapabilityRequiredMixin):
    """Blocks / units — create, edit, delete."""
    required_capability = "properties_manage"


class StaffManageCapabilityMixin(CapabilityRequiredMixin):
    """Staff section (the people, not the role rules: see can_manage_staff)."""
    required_capability = "staff_manage"


class MaintenanceViewMixin(CapabilityRequiredMixin):
    """Maintenance requests — read."""
    required_capability = "maintenance_view"


class MaintenanceManageMixin(CapabilityRequiredMixin):
    """Maintenance requests — create, edit."""
    required_capability = "maintenance_manage"


class TenantsViewMixin(CapabilityRequiredMixin):
    """Tenants — read."""
    required_capability = "tenants_view"


class TenantsManageMixin(CapabilityRequiredMixin):
    """Tenants — create, edit, delete, SMS."""
    required_capability = "tenants_manage"


class LeasesViewMixin(CapabilityRequiredMixin):
    """Leases — read."""
    required_capability = "leases_view"


class LeasesManageMixin(CapabilityRequiredMixin):
    """Leases — create, edit, renew, delete, reminders."""
    required_capability = "leases_manage"


class RentViewMixin(CapabilityRequiredMixin):
    """Rent invoices & arrears — read."""
    required_capability = "rent_view"


class RentManageMixin(CapabilityRequiredMixin):
    """Rent invoices — generate and record payments."""
    required_capability = "rent_manage"


class BookingsViewMixin(CapabilityRequiredMixin):
    """Bookings, guests and calendar — read."""
    required_capability = "bookings_view"


class BookingsManageMixin(CapabilityRequiredMixin):
    """Bookings and guests — create, edit, delete, status changes."""
    required_capability = "bookings_manage"


class PaymentsViewMixin(CapabilityRequiredMixin):
    """Payments — read."""
    required_capability = "payments_view"


class PaymentsManageMixin(CapabilityRequiredMixin):
    """Payments — create, edit, delete."""
    required_capability = "payments_manage"


class PaymentsReportMixin(CapabilityRequiredMixin):
    """Payments report."""
    required_capability = "payments_report"


class FinanceViewMixin(CapabilityRequiredMixin):
    """Expenses / purchases / stock — read."""
    required_capability = "finance_view"


class FinanceManageMixin(CapabilityRequiredMixin):
    """Expenses / purchases / stock — create, edit, delete, adjust."""
    required_capability = "finance_manage"


class SmsSettingsMixin(CapabilityRequiredMixin):
    """Automated SMS notification settings."""
    required_capability = "sms_settings"


def capability_required(capability):
    """Decorator twin of :class:`CapabilityRequiredMixin` for function views.

    Stack it *inside* ``@login_required`` so anonymous users are redirected to
    the login page instead of seeing a 403:

        @login_required
        @capability_required("tenants_manage")
        def my_view(request): ...
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not user_can(request.user, capability):
                raise PermissionDenied(
                    capability_denial_message(request.user, capability)
                )
            return view(request, *args, **kwargs)

        return wrapper

    return decorator

