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
from .models import Property


def is_owner(user) -> bool:
    """True if the user is in the ``owner`` group."""
    if not user or not user.is_authenticated:
        return False
    return user.groups.filter(name="owner").exists()


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
