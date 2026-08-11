from properties.models import Property
from django.db.models import Q


def global_context(request):
    """Inject global context variables for templates."""
    ctx = {}
    ctx["now"] = __import__("datetime").datetime.now()

    if request.user.is_authenticated:
        # Get properties the user has access to
        user = request.user
        if user.groups.filter(name="owner").exists():
            user_properties = Property.objects.filter(owner=user, is_active=True)
        else:
            user_properties = Property.objects.filter(
                staff__user=user, staff__is_active=True, is_active=True
            )
        ctx["user_properties"] = user_properties
        ctx["current_property_count"] = user_properties.count()

        # Get user's groups for role-based UI
        ctx["user_groups"] = list(user.groups.values_list("name", flat=True))
        ctx["is_owner"] = user.groups.filter(name="owner").exists()
        ctx["is_manager"] = user.groups.filter(name="manager").exists()
        ctx["is_receptionist"] = user.groups.filter(name="receptionist").exists()
        ctx["is_accountant"] = user.groups.filter(name="accountant").exists()
    else:
        ctx["user_properties"] = Property.objects.none()
        ctx["current_property_count"] = 0
        ctx["is_owner"] = False
        ctx["is_manager"] = False
        ctx["is_receptionist"] = False
        ctx["is_accountant"] = False
        ctx["user_groups"] = []

    return ctx
