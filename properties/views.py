from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect
from django.db.models import Q, Count
from django import forms
from django.contrib.auth.models import User, Group
from .models import Property, Block, Unit, UnitAmenity, PropertyStaff, MaintenanceRequest, OwnerProfile
from .access import (
    assignable_roles,
    can_manage_staff,
    get_manageable_staff,
    get_managed_properties,
    MaintenanceManageMixin,
    MaintenanceViewMixin,
    PropertiesManageMixin,
    PropertiesViewMixin,
    StaffManageCapabilityMixin,
)
from tenants.models import Lease
from bookings.models import Booking


# ---------- Mixins ----------

class OwnerRequiredMixin(UserPassesTestMixin):
    """Only allow users in 'owner' group or superusers."""

    # Surfaced on the friendly 403 page (see config/error_views.py).
    permission_denied_message = (
        "This action is restricted to property owners. "
        "Ask an owner if you need access."
    )

    def test_func(self):
        user = self.request.user
        return user.is_superuser or user.groups.filter(name="owner").exists()


class PropertyAccessMixin(LoginRequiredMixin):
    """Filter queryset to user's accessible properties."""

    def get_property_queryset(self):
        user = self.request.user
        # Superusers can access all properties
        if user.is_superuser:
            return Property.objects.all()
        if user.groups.filter(name="owner").exists():
            return Property.objects.filter(owner=user)
        # Staff can access properties they are assigned to
        return Property.objects.filter(staff__user=user, staff__is_active=True)

    def get_block_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Block.objects.all()
        return Block.objects.filter(
            property__in=self.get_property_queryset()
        )

    def get_unit_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Unit.objects.all()
        return Unit.objects.filter(
            block__property__in=self.get_property_queryset()
        )


class StaffManageMixin(UserPassesTestMixin):
    """Allow owners/superusers **and property managers** to administer staff.

    Managers are limited further by :func:`~properties.access.get_manageable_staff`
    and :func:`~properties.access.assignable_roles`: they may only create/edit
    accountants and receptionists on the properties they manage.
    """

    # Surfaced on the friendly 403 page (see config/error_views.py).
    permission_denied_message = (
        "Only property owners and managers can add or manage staff."
    )

    def test_func(self):
        return can_manage_staff(self.request.user)

    def get_managed_properties(self):
        return get_managed_properties(self.request.user)

    def build_staff_form(self, data=None, user_pk=None):
        """A ``StaffForm`` scoped to what this user is allowed to assign."""
        form = StaffForm(
            data,
            user_pk=user_pk,
            allowed_roles=assignable_roles(self.request.user),
        )
        form.fields["properties"].queryset = self.get_managed_properties()
        return form


# ---------- Owner Profile ----------

class OwnerProfileForm(forms.ModelForm):
    class Meta:
        model = OwnerProfile
        fields = [
            "phone", "email",
            "bank_name", "bank_account_name", "bank_account_number",
            "bank_branch", "bank_currency",
            "mpesa_number", "mpesa_account_name",
            "tigo_pesa_number", "airtel_money_number",
            "payment_instructions",
        ]
        widgets = {
            "payment_instructions": forms.Textarea(attrs={"rows": 3}),
        }


class OwnerProfileView(LoginRequiredMixin, OwnerRequiredMixin, TemplateView):
    """View / edit the owner's payment profile."""
    template_name = "properties/owner_profile.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        owner = self.request.user
        profile, created = OwnerProfile.objects.get_or_create(owner=owner)
        ctx["profile"] = profile
        return ctx


class OwnerProfileUpdateView(LoginRequiredMixin, OwnerRequiredMixin, UpdateView):
    model = OwnerProfile
    form_class = OwnerProfileForm
    template_name = "properties/owner_profile_form.html"

    def get_object(self, queryset=None):
        profile, created = OwnerProfile.objects.get_or_create(owner=self.request.user)
        return profile

    def get_success_url(self):
        return reverse_lazy("properties:owner_profile")

    def form_valid(self, form):
        messages.success(self.request, "Owner profile updated successfully.")
        return super().form_valid(form)


# ---------- Properties ----------

class PropertyListView(PropertiesViewMixin, PropertyAccessMixin, ListView):
    model = Property
    template_name = "properties/property_list.html"
    context_object_name = "object_list"
    paginate_by = 10

    def get_queryset(self):
        qs = self.get_property_queryset().prefetch_related("blocks")
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(
                Q(name__icontains=q) | Q(location__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class PropertyDetailView(PropertiesViewMixin, PropertyAccessMixin, DetailView):
    model = Property
    template_name = "properties/property_detail.html"
    context_object_name = "property"

    def get_queryset(self):
        return self.get_property_queryset().prefetch_related(
            "blocks__units",
            "staff__user",
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        prop = self.get_object()
        blocks = prop.blocks.prefetch_related("units").all()
        ctx["blocks"] = blocks
        total_units = 0
        occupied_units = 0
        for block in blocks:
            units = list(block.units.all())
            total_units += len(units)
            occupied_units += sum(1 for u in units if u.status == "occupied")
        ctx["total_units"] = total_units
        ctx["occupied_units"] = occupied_units
        ctx["occupancy_rate"] = (occupied_units / total_units * 100) if total_units > 0 else 0
        ctx["recent_tenants"] = Lease.objects.filter(
            unit__block__property=prop
        ).select_related("tenant", "unit").order_by("-start_date")[:5]
        ctx["recent_bookings"] = Booking.objects.filter(
            unit__block__property=prop
        ).select_related("guest", "unit").order_by("-created_at")[:5]
        # Include the owner's payment profile for tenants/guests to see
        try:
            ctx["owner_profile"] = OwnerProfile.objects.get(owner=prop.owner)
        except OwnerProfile.DoesNotExist:
            ctx["owner_profile"] = None
        return ctx


class PropertyCreateView(OwnerRequiredMixin, CreateView):
    model = Property
    fields = ["name", "location", "description", "image", "logo"]
    template_name = "properties/property_form.html"
    success_url = reverse_lazy("properties:property_list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if "owner" in form.fields:
            del form.fields["owner"]
        return form

    def form_valid(self, form):
        form.instance.owner = self.request.user
        messages.success(self.request, "Property created successfully.")
        return super().form_valid(form)


class PropertyUpdateView(OwnerRequiredMixin, UpdateView):
    model = Property
    fields = ["name", "location", "description", "image", "logo", "is_active"]
    template_name = "properties/property_form.html"
    success_url = reverse_lazy("properties:property_list")

    def get_queryset(self):
        return Property.objects.filter(owner=self.request.user)

    def form_valid(self, form):
        messages.success(self.request, "Property updated successfully.")
        return super().form_valid(form)


class PropertyDeleteView(PropertyAccessMixin, OwnerRequiredMixin, DeleteView):
    model = Property
    template_name = "properties/property_confirm_delete.html"
    success_url = reverse_lazy("properties:property_list")
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        return self.get_property_queryset()

    def form_valid(self, form):
        messages.success(self.request, "Property deleted successfully.")
        return super().form_valid(form)


# ---------- Blocks ----------

class BlockListView(PropertiesViewMixin, PropertyAccessMixin, ListView):
    model = Block
    template_name = "properties/block_list.html"
    context_object_name = "object_list"
    paginate_by = 10

    def get_queryset(self):
        qs = self.get_block_queryset().prefetch_related("units")
        property_id = self.request.GET.get("property")
        if property_id:
            qs = qs.filter(property_id=property_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["properties"] = self.get_property_queryset()
        ctx["current_property"] = self.request.GET.get("property", "")
        for block in ctx["object_list"]:
            units = list(block.units.all())
            block.unit_count = len(units)
            block.occupied_count = sum(
                1 for u in units if not u.is_available
            )
        return ctx


class BlockCreateView(PropertiesManageMixin, PropertyAccessMixin, CreateView):
    model = Block
    fields = [
        "property", "name", "description", "location", "building_type",
        "water_meter_number", "electricity_meter_number", "image",
    ]
    template_name = "properties/block_form.html"
    success_url = reverse_lazy("properties:block_list")

    def get_initial(self):
        initial = super().get_initial()
        prop_id = self.request.GET.get("property")
        if prop_id:
            initial["property"] = prop_id
        return initial

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["property"].queryset = self.get_property_queryset()
        return form

    def form_valid(self, form):
        messages.success(self.request, "Block created successfully.")
        return super().form_valid(form)


class BlockUpdateView(PropertiesManageMixin, PropertyAccessMixin, UpdateView):
    model = Block
    fields = [
        "property", "name", "description", "location", "building_type",
        "water_meter_number", "electricity_meter_number", "image", "is_active",
    ]
    template_name = "properties/block_form.html"
    success_url = reverse_lazy("properties:block_list")

    def get_queryset(self):
        return self.get_block_queryset()

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["property"].queryset = self.get_property_queryset()
        return form

    def form_valid(self, form):
        messages.success(self.request, "Block updated successfully.")
        return super().form_valid(form)


class BlockDeleteView(PropertiesManageMixin, PropertyAccessMixin, DeleteView):
    model = Block
    template_name = "properties/block_confirm_delete.html"
    context_object_name = "block_obj"
    success_url = reverse_lazy("properties:block_list")

    def get_queryset(self):
        return self.get_block_queryset()

    def form_valid(self, form):
        messages.success(self.request, "Block deleted successfully.")
        return super().form_valid(form)


class BlockDetailView(PropertiesViewMixin, PropertyAccessMixin, DetailView):
    model = Block
    template_name = "properties/block_detail.html"
    context_object_name = "block_obj"

    def get_queryset(self):
        return self.get_block_queryset().prefetch_related("units__amenities")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        block = self.object
        units = block.units.prefetch_related("amenities").all()
        ctx["units"] = units
        total = units.count()
        occupied = sum(1 for u in units if u.status == "occupied")
        ctx["occupied_count"] = occupied
        ctx["vacant_count"] = total - occupied
        ctx["occupancy_rate"] = (occupied / total * 100) if total > 0 else 0
        return ctx


# ---------- Units ----------

class UnitListView(PropertiesViewMixin, PropertyAccessMixin, ListView):
    model = Unit
    template_name = "properties/unit_list.html"
    context_object_name = "object_list"
    paginate_by = 10

    def get_queryset(self):
        qs = self.get_unit_queryset().select_related("block__property")
        rental_type = self.request.GET.get("rental_type")
        block = self.request.GET.get("block")
        property_id = self.request.GET.get("property")
        if rental_type:
            qs = qs.filter(rental_type=rental_type)
        if block:
            qs = qs.filter(block_id=block)
        if property_id:
            qs = qs.filter(block__property_id=property_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["properties"] = self.get_property_queryset()
        ctx["blocks"] = self.get_block_queryset()
        ctx["current_rental_type"] = self.request.GET.get("rental_type", "")
        ctx["current_block"] = self.request.GET.get("block", "")
        ctx["current_property"] = self.request.GET.get("property", "")
        return ctx


class UnitDetailView(PropertiesViewMixin, PropertyAccessMixin, DetailView):
    model = Unit
    template_name = "properties/unit_detail.html"
    context_object_name = "unit"

    def get_queryset(self):
        return self.get_unit_queryset().select_related("block__property")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        unit = self.get_object()
        ctx["leases"] = unit.leases.select_related("tenant").all()
        ctx["bookings"] = unit.bookings.select_related("guest").all()
        # Include the owner's payment profile for tenants/guests to see
        try:
            ctx["owner_profile"] = OwnerProfile.objects.get(owner=unit.block.property.owner)
        except OwnerProfile.DoesNotExist:
            ctx["owner_profile"] = None
        return ctx


class UnitCreateView(PropertiesManageMixin, PropertyAccessMixin, CreateView):
    model = Unit
    fields = [
        "block", "unit_number", "rental_type", "unit_type", "status",
        "description", "image", "amenities", "square_feet",
        "bedrooms", "bathrooms",
        "monthly_rent", "deposit_amount",
        "nightly_rate", "weekly_rate", "cleaning_fee",
        "max_guests", "is_available", "notes",
        "water_meter_number", "electricity_meter_number",
    ]
    template_name = "properties/unit_form.html"
    success_url = reverse_lazy("properties:unit_list")

    def get_initial(self):
        initial = super().get_initial()
        block_id = self.request.GET.get("block")
        if block_id:
            initial["block"] = block_id
        return initial

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["block"].queryset = self.get_block_queryset()
        return form

    def form_valid(self, form):
        messages.success(self.request, "Unit created successfully.")
        return super().form_valid(form)


class UnitUpdateView(PropertiesManageMixin, PropertyAccessMixin, UpdateView):
    model = Unit
    fields = [
        "block", "unit_number", "rental_type", "unit_type", "status",
        "description", "image", "amenities", "square_feet",
        "bedrooms", "bathrooms",
        "monthly_rent", "deposit_amount",
        "nightly_rate", "weekly_rate", "cleaning_fee",
        "max_guests", "is_available", "notes",
        "water_meter_number", "electricity_meter_number",
    ]
    template_name = "properties/unit_form.html"
    success_url = reverse_lazy("properties:unit_list")

    def get_queryset(self):
        return self.get_unit_queryset()

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["block"].queryset = self.get_block_queryset()
        return form

    def form_valid(self, form):
        messages.success(self.request, "Unit updated successfully.")
        return super().form_valid(form)


class UnitDeleteView(PropertiesManageMixin, PropertyAccessMixin, DeleteView):
    model = Unit
    template_name = "properties/unit_confirm_delete.html"
    success_url = reverse_lazy("properties:unit_list")

    def get_queryset(self):
        return self.get_unit_queryset()

    def form_valid(self, form):
        messages.success(self.request, "Unit deleted successfully.")
        return super().form_valid(form)


# ---------- Property Staff ----------

class StaffForm(forms.Form):
    """Create a user and assign them to one or more properties."""

    first_name = forms.CharField(max_length=30, required=True, label="First Name",
                                 widget=forms.TextInput(attrs={"class": "form-control"}))
    last_name = forms.CharField(max_length=30, required=True, label="Last Name",
                                widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(required=True, label="Email Address",
                             widget=forms.EmailInput(attrs={"class": "form-control"}))
    mobile = forms.CharField(max_length=20, required=False, label="Mobile / Phone",
                             widget=forms.TextInput(attrs={"class": "form-control"}))
    password = forms.CharField(max_length=128, required=True, label="Password",
                               widget=forms.PasswordInput(attrs={"class": "form-control"}))
    role = forms.ChoiceField(choices=PropertyStaff.STAFF_ROLES, label="Role",
                             widget=forms.Select(attrs={"class": "form-select"}))
    properties = forms.ModelMultipleChoiceField(
        queryset=Property.objects.none(),
        label="Properties",
        widget=forms.CheckboxSelectMultiple,
        required=True,
    )

    def __init__(self, *args, allowed_roles=None, **kwargs):
        self.user_pk = kwargs.pop("user_pk", None)
        super().__init__(*args, **kwargs)

        if allowed_roles is not None:
            # Restrict the roles the acting user may grant (e.g. managers can
            # only add accountants/receptionists). Because this narrows the
            # field's choices, an out-of-scope POST is rejected as invalid.
            allowed_codes = {code for code, _label in allowed_roles}
            self.fields["role"].choices = [
                (value, label)
                for value, label in PropertyStaff.STAFF_ROLES
                if value in allowed_codes
            ]

        if self.user_pk:
            try:
                user = User.objects.get(pk=self.user_pk)
                staff_records = PropertyStaff.objects.filter(user=user)
                self.fields["first_name"].initial = user.first_name
                self.fields["last_name"].initial = user.last_name
                self.fields["email"].initial = user.email
                self.fields["mobile"].initial = staff_records.first().mobile if staff_records.exists() else ""
                self.fields["password"].required = False
                self.fields["password"].help_text = "Leave blank to keep current password"
                self.fields["role"].initial = staff_records.first().role if staff_records.exists() else ""
                self.fields["properties"].initial = staff_records.values_list("property_id", flat=True)
            except User.DoesNotExist:
                pass

    def clean_email(self):
        email = self.cleaned_data["email"]
        qs = User.objects.filter(email=email)
        if self.user_pk:
            qs = qs.exclude(pk=self.user_pk)
        if qs.exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def save(self, properties_queryset, commit=True):
        properties = self.cleaned_data["properties"]
        role = self.cleaned_data["role"]
        mobile = self.cleaned_data.get("mobile", "")

        if self.user_pk:
            # Update existing user
            user = User.objects.get(pk=self.user_pk)
            user.first_name = self.cleaned_data["first_name"]
            user.last_name = self.cleaned_data["last_name"]
            user.email = self.cleaned_data["email"]
            user.username = self.cleaned_data["email"]
            if self.cleaned_data.get("password"):
                user.set_password(self.cleaned_data["password"])
            if commit:
                user.save()

            # Update group
            group, _ = Group.objects.get_or_create(name=role)
            user.groups.clear()
            user.groups.add(group)

            # Sync property assignments — but only within the properties the
            # acting user was allowed to choose, so assignments outside their
            # scope are never modified.
            in_scope = PropertyStaff.objects.filter(
                user=user, property__in=properties_queryset
            )
            existing = set(in_scope.values_list("property_id", flat=True))
            selected = set(p.id for p in properties)

            # Remove unselected properties (within scope)
            in_scope.filter(property_id__in=(existing - selected)).delete()

            # Add new properties
            for prop_id in (selected - existing):
                prop = properties_queryset.get(pk=prop_id)
                PropertyStaff.objects.create(user=user, property=prop, role=role, mobile=mobile)

            # Update existing records
            in_scope.filter(property_id__in=(existing & selected)).update(role=role, mobile=mobile)
        else:
            # Create new user
            user = User.objects.create_user(
                username=self.cleaned_data["email"],
                email=self.cleaned_data["email"],
                password=self.cleaned_data["password"],
                first_name=self.cleaned_data["first_name"],
                last_name=self.cleaned_data["last_name"],
            )
            group, _ = Group.objects.get_or_create(name=role)
            user.groups.add(group)

            # Create PropertyStaff records for each selected property
            for prop in properties:
                PropertyStaff.objects.create(user=user, property=prop, role=role, mobile=mobile)

        return user


class StaffListView(StaffManageCapabilityMixin, PropertyAccessMixin, ListView):
    model = PropertyStaff
    template_name = "properties/staff_list.html"
    context_object_name = "staff_list"
    paginate_by = 10

    def get_queryset(self):
        user = self.request.user
        # Owners, superusers and property managers see every staff record they
        # are allowed to administer (managers only accountants/receptionists on
        # their own properties). Everyone else only sees their own records.
        if can_manage_staff(user):
            return get_manageable_staff(user)
        return PropertyStaff.objects.filter(
            user=user
        ).select_related("user", "property")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["properties"] = self.get_property_queryset()
        ctx["can_manage_staff"] = can_manage_staff(self.request.user)
        # Group staff records by user
        staff_qs = ctx.get("staff_list", [])
        grouped = {}
        for s in staff_qs:
            uid = s.user_id
            if uid not in grouped:
                grouped[uid] = {
                    "user": s.user,
                    "records": [],
                }
            grouped[uid]["records"].append(s)
        ctx["staff_by_user"] = list(grouped.values())
        return ctx


class StaffCreateView(StaffManageMixin, TemplateView):
    template_name = "properties/staff_form.html"

    def get_success_url(self):
        return reverse_lazy("properties:staff_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if "form" not in ctx:
            ctx["form"] = self.build_staff_form()
        ctx["can_manage_staff"] = can_manage_staff(self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
        form = self.build_staff_form(request.POST)
        if form.is_valid():
            form.save(self.get_managed_properties())
            messages.success(request, f"Staff member '{form.cleaned_data['first_name']} {form.cleaned_data['last_name']}' created and assigned successfully.")
            return redirect(self.get_success_url())
        return self.render_to_response(self.get_context_data(form=form))


class StaffUpdateView(StaffManageMixin, TemplateView):
    template_name = "properties/staff_form.html"

    def get_success_url(self):
        return reverse_lazy("properties:staff_list")

    def get_user(self, *args, **kwargs):
        staff = get_object_or_404(get_manageable_staff(self.request.user), pk=kwargs["pk"])
        return staff.user

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.get_user(**kwargs)
        if "form" not in ctx:
            ctx["form"] = self.build_staff_form(user_pk=user.pk)
        ctx["is_edit"] = True
        ctx["edit_user"] = user
        ctx["can_manage_staff"] = can_manage_staff(self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
        user = self.get_user(**kwargs)
        form = self.build_staff_form(request.POST, user_pk=user.pk)
        if form.is_valid():
            form.save(self.get_managed_properties())
            messages.success(request, f"Staff member '{form.cleaned_data['first_name']} {form.cleaned_data['last_name']}' updated successfully.")
            return redirect(self.get_success_url())
        return self.render_to_response(self.get_context_data(form=form, pk=kwargs["pk"]))


class StaffToggleActiveView(StaffManageMixin, TemplateView):
    """Toggle the is_active status for all of a staff user's assignments."""

    def post(self, request, *args, **kwargs):
        staff = get_object_or_404(get_manageable_staff(request.user), pk=kwargs["pk"])
        user = staff.user
        new_status = not staff.is_active
        # Only flip the assignments this user is allowed to administer.
        PropertyStaff.objects.filter(
            user=user, property__in=get_managed_properties(request.user)
        ).update(is_active=new_status)
        status = "enabled" if new_status else "disabled"
        messages.success(request, f"Staff member '{user.get_full_name() or user.username}' {status} across all properties successfully.")
        return redirect("properties:staff_list")


class StaffDeleteView(StaffManageMixin, TemplateView):
    template_name = "properties/staff_confirm_delete.html"
    success_url = reverse_lazy("properties:staff_list")

    def get_user(self, *args, **kwargs):
        staff = get_object_or_404(get_manageable_staff(self.request.user), pk=kwargs["pk"])
        return staff.user

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.get_user(**kwargs)
        name = user.get_full_name() or user.username
        ctx["staff_name"] = name
        ctx["staff_user"] = user
        return ctx

    def post(self, request, *args, **kwargs):
        user = self.get_user(**kwargs)
        name = user.get_full_name() or user.username
        # Only remove the assignments this user is allowed to administer.
        PropertyStaff.objects.filter(
            user=user, property__in=get_managed_properties(request.user)
        ).delete()
        # Also remove the user from any remaining property staff groups to prevent login
        remaining = PropertyStaff.objects.filter(user=user)
        if not remaining.exists():
            user.groups.clear()
            user.is_active = False
            user.save()
        messages.success(request, f"Staff member '{name}' removed from all properties successfully.")
        return redirect(self.success_url)


# ---------- Maintenance Requests ----------

class MaintenanceRequestListView(MaintenanceViewMixin, PropertyAccessMixin, ListView):
    model = MaintenanceRequest
    template_name = "properties/maintenance_request_list.html"
    context_object_name = "request_list"
    paginate_by = 10

    def get_queryset(self):
        qs = MaintenanceRequest.objects.filter(
            property__in=self.get_property_queryset()
        ).select_related(
            "property", "unit", "reported_by", "assigned_to"
        )
        status = self.request.GET.get("status")
        priority = self.request.GET.get("priority")
        property_id = self.request.GET.get("property")
        if status:
            qs = qs.filter(status=status)
        if priority:
            qs = qs.filter(priority=priority)
        if property_id:
            qs = qs.filter(property_id=property_id)
        return qs.order_by("-priority", "-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["properties"] = self.get_property_queryset()
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["current_priority"] = self.request.GET.get("priority", "")
        ctx["current_property"] = self.request.GET.get("property", "")
        ctx["status_counts"] = MaintenanceRequest.objects.filter(
            property__in=self.get_property_queryset()
        ).values("status").annotate(count=Count("id")).order_by("status")
        return ctx


class MaintenanceRequestCreateView(MaintenanceManageMixin, PropertyAccessMixin, CreateView):
    model = MaintenanceRequest
    fields = [
        "property", "unit", "title", "description",
        "priority", "assigned_to", "notes",
    ]
    template_name = "properties/maintenance_request_form.html"

    def get_success_url(self):
        return reverse_lazy("properties:maintenance_list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["property"].queryset = self.get_property_queryset()
        form.fields["unit"].queryset = self.get_unit_queryset()
        # Only show users that could be assignees
        form.fields["assigned_to"].queryset = form.fields["assigned_to"].queryset.filter(
            groups__name__in=["manager", "receptionist", "accountant"]
        )
        return form

    def form_valid(self, form):
        form.instance.reported_by = self.request.user
        messages.success(self.request, "Maintenance request created successfully.")
        return super().form_valid(form)


class MaintenanceRequestUpdateView(MaintenanceManageMixin, PropertyAccessMixin, UpdateView):
    model = MaintenanceRequest
    fields = [
        "title", "description", "unit", "priority", "status",
        "assigned_to", "notes", "resolution_notes", "cost",
    ]
    template_name = "properties/maintenance_request_form.html"

    def get_queryset(self):
        return MaintenanceRequest.objects.filter(
            property__in=self.get_property_queryset()
        )

    def get_success_url(self):
        return reverse_lazy("properties:maintenance_detail", kwargs={"pk": self.object.pk})

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["unit"].queryset = self.get_unit_queryset()
        form.fields["assigned_to"].queryset = form.fields["assigned_to"].queryset.filter(
            groups__name__in=["manager", "receptionist", "accountant"]
        )
        return form

    def form_valid(self, form):
        messages.success(self.request, "Maintenance request updated successfully.")
        return super().form_valid(form)


class MaintenanceRequestDetailView(MaintenanceViewMixin, PropertyAccessMixin, DetailView):
    model = MaintenanceRequest
    template_name = "properties/maintenance_request_detail.html"
    context_object_name = "request"

    def get_queryset(self):
        return MaintenanceRequest.objects.filter(
            property__in=self.get_property_queryset()
        ).select_related("property", "unit", "reported_by", "assigned_to")


class MaintenanceRequestDeleteView(PropertyAccessMixin, OwnerRequiredMixin, DeleteView):
    model = MaintenanceRequest
    template_name = "properties/maintenance_request_confirm_delete.html"
    success_url = reverse_lazy("properties:maintenance_list")

    def get_queryset(self):
        return MaintenanceRequest.objects.filter(
            property__in=self.get_property_queryset()
        )

    def form_valid(self, form):
        messages.success(self.request, "Maintenance request deleted successfully.")
        return super().form_valid(form)

