from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from config.test_factories import (
    TwoLandlordFixtureMixin,
    make_staff_user,
    make_tenant,
)
from .models import PropertyStaff
from .access import (
    ALL_CAPABILITIES,
    PropertyScopedMixin,
    assignable_roles,
    can_manage_staff,
    describe_roles,
    get_accessible_properties,
    get_accessible_property_ids,
    get_capabilities,
    get_manageable_staff,
    get_managed_properties,
    get_user_roles,
    is_manager,
    is_owner,
    user_can,
)

User = get_user_model()



class AccessHelperTests(TwoLandlordFixtureMixin, TestCase):
    def test_is_owner(self):
        self.assertTrue(is_owner(self.owner_a))
        plain = self.owner_a.__class__.objects.create_user(
            username="plain", password="pass12345"
        )
        self.assertFalse(is_owner(plain))

    def test_owner_sees_only_own_properties(self):
        ids = get_accessible_property_ids(self.owner_a)
        self.assertEqual(ids, [self.property_a.id])

    def test_superuser_sees_all_properties(self):
        superuser = self.owner_a.__class__.objects.create_superuser(
            username="root", password="pass12345", email="root@example.com"
        )
        ids = set(get_accessible_property_ids(superuser))
        self.assertEqual(ids, {self.property_a.id, self.property_b.id})

    def test_user_without_group_has_no_properties(self):
        outsider = self.owner_a.__class__.objects.create_user(
            username="outsider", password="pass12345"
        )
        self.assertFalse(get_accessible_properties(outsider).exists())

    def test_anonymous_has_no_properties(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(get_accessible_properties(AnonymousUser()).exists())


class PropertyScopedMixinTests(TwoLandlordFixtureMixin, TestCase):
    def test_scoped_mixin_filters_by_property(self):
        from .models import Block

        class _Base:
            def get_queryset(self):
                return Block.objects.all()

        class _View(PropertyScopedMixin, _Base):
            pass

        view = _View()
        view.request = type("Req", (), {"user": self.owner_a})()
        self.assertEqual(list(view.get_queryset()), [self.block_a])


class PropertyListViewIsolationTests(TwoLandlordFixtureMixin, TestCase):
    def test_owner_only_sees_their_properties(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("properties:property_list"))
        self.assertEqual(response.status_code, 200)
        object_list = list(response.context["object_list"])
        self.assertIn(self.property_a, object_list)
        self.assertNotIn(self.property_b, object_list)

    def test_owner_cannot_open_other_property_detail(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("properties:property_detail", args=[self.property_b.slug])
        )
        self.assertEqual(response.status_code, 404)


class StaffAccessHelperTests(TwoLandlordFixtureMixin, TestCase):
    """Unit tests for the manager-aware staff helpers in ``properties.access``."""

    def setUp(self):
        super().setUp()
        self.manager_a = make_staff_user("manager_a", self.property_a, "manager")
        self.receptionist_a = make_staff_user(
            "receptionist_a", self.property_a, "receptionist"
        )

    def test_is_manager(self):
        self.assertTrue(is_manager(self.manager_a))
        self.assertFalse(is_manager(self.receptionist_a))
        self.assertFalse(is_manager(self.owner_a))

    def test_can_manage_staff(self):
        self.assertTrue(can_manage_staff(self.owner_a))
        self.assertTrue(can_manage_staff(self.manager_a))
        self.assertFalse(can_manage_staff(self.receptionist_a))

    def test_get_managed_properties(self):
        manager_ids = set(
            get_managed_properties(self.manager_a).values_list("id", flat=True)
        )
        self.assertEqual(manager_ids, {self.property_a.id})
        owner_ids = set(
            get_managed_properties(self.owner_a).values_list("id", flat=True)
        )
        self.assertEqual(owner_ids, {self.property_a.id})
        self.assertFalse(get_managed_properties(self.receptionist_a).exists())

    def test_assignable_roles(self):
        self.assertEqual(
            {role[0] for role in assignable_roles(self.owner_a)},
            {"manager", "receptionist", "accountant"},
        )
        # Managers may only grant day-to-day staff roles.
        self.assertEqual(
            {role[0] for role in assignable_roles(self.manager_a)},
            {"receptionist", "accountant"},
        )
        self.assertEqual(assignable_roles(self.receptionist_a), [])

    def test_manageable_staff_excludes_managers_and_owners(self):
        user_ids = set(
            get_manageable_staff(self.manager_a).values_list("user_id", flat=True)
        )
        self.assertIn(self.receptionist_a.id, user_ids)
        self.assertNotIn(self.manager_a.id, user_ids)
        self.assertNotIn(self.owner_a.id, user_ids)

    def test_manager_cannot_manage_staff_assigned_outside_their_scope(self):
        # A receptionist who also works on owner_b's property is off-limits.
        shared = make_staff_user("shared", self.property_a, "receptionist")
        PropertyStaff.objects.create(
            user=shared, property=self.property_b, role="receptionist"
        )
        user_ids = set(
            get_manageable_staff(self.manager_a).values_list("user_id", flat=True)
        )
        self.assertNotIn(shared.id, user_ids)

class DescribeRolesTests(TwoLandlordFixtureMixin, TestCase):
    """``describe_roles`` powers the role badge / 403 page."""

    def test_owner_group_is_described(self):
        self.assertEqual(describe_roles(self.owner_a), ["Owner"])

    def test_superuser_is_described_first(self):
        superuser = self.owner_a.__class__.objects.create_superuser(
            username="root", password="pass12345", email="root@example.com"
        )
        self.assertEqual(describe_roles(superuser), ["Superuser"])

    def test_staff_role_is_described_from_property_staff(self):
        manager = make_staff_user("mgr", self.property_a, "manager")
        self.assertEqual(describe_roles(manager), ["Manager"])

    def test_role_survives_missing_group(self):
        # The PropertyStaff row alone must be enough to describe the user.
        recp = make_staff_user("recp", self.property_a, "receptionist")
        recp.groups.clear()
        self.assertEqual(describe_roles(recp), ["Receptionist"])

    def test_user_without_a_role_gets_an_empty_list(self):
        plain = self.owner_a.__class__.objects.create_user(
            username="plain", password="pass12345"
        )
        self.assertEqual(describe_roles(plain), [])

    def test_anonymous_has_no_roles(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(describe_roles(AnonymousUser()), [])





class StaffManagementViewTests(TwoLandlordFixtureMixin, TestCase):
    """Managers may add/manage accountants & receptionists on their properties."""

    def setUp(self):
        super().setUp()
        self.manager_a = make_staff_user("manager_a", self.property_a, "manager")
        self.receptionist_a = make_staff_user(
            "receptionist_a", self.property_a, "receptionist"
        )
        self.receptionist_b = make_staff_user(
            "receptionist_b", self.property_b, "receptionist"
        )

    def _post_data(self, role="receptionist", properties=None,
                   email="newstaff@example.com"):
        return {
            "first_name": "New",
            "last_name": "Staff",
            "email": email,
            "mobile": "+255700000000",
            "password": "pass12345",
            "role": role,
            "properties": [p.id for p in (properties or [self.property_a])],
        }

    def test_manager_can_open_form_and_only_sees_lower_roles(self):
        self.client.force_login(self.manager_a)
        response = self.client.get(reverse("properties:staff_create"))
        self.assertEqual(response.status_code, 200)
        choices = {c[0] for c in response.context["form"].fields["role"].choices}
        self.assertEqual(choices, {"receptionist", "accountant"})
        offered = {p.id for p in response.context["form"].fields["properties"].queryset}
        self.assertEqual(offered, {self.property_a.id})

    def test_manager_can_create_a_receptionist(self):
        self.client.force_login(self.manager_a)
        response = self.client.post(
            reverse("properties:staff_create"), self._post_data(role="receptionist")
        )
        self.assertRedirects(response, reverse("properties:staff_list"))
        user = User.objects.get(email="newstaff@example.com")
        self.assertTrue(user.groups.filter(name="receptionist").exists())
        self.assertTrue(
            PropertyStaff.objects.filter(
                user=user, property=self.property_a, role="receptionist"
            ).exists()
        )

    def test_manager_can_create_an_accountant(self):
        self.client.force_login(self.manager_a)
        response = self.client.post(
            reverse("properties:staff_create"),
            self._post_data(role="accountant", email="acct@example.com"),
        )
        self.assertRedirects(response, reverse("properties:staff_list"))
        user = User.objects.get(email="acct@example.com")
        self.assertTrue(user.groups.filter(name="accountant").exists())

    def test_manager_cannot_grant_the_manager_role(self):
        self.client.force_login(self.manager_a)
        response = self.client.post(
            reverse("properties:staff_create"), self._post_data(role="manager")
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="newstaff@example.com").exists())

    def test_manager_cannot_assign_a_property_they_do_not_manage(self):
        self.client.force_login(self.manager_a)
        response = self.client.post(
            reverse("properties:staff_create"),
            self._post_data(properties=[self.property_b]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="newstaff@example.com").exists())

    def test_receptionist_cannot_open_staff_create(self):
        self.client.force_login(self.receptionist_a)
        response = self.client.get(reverse("properties:staff_create"))
        self.assertEqual(response.status_code, 403)

    def test_manager_list_only_shows_their_own_staff(self):
        self.client.force_login(self.manager_a)
        response = self.client.get(reverse("properties:staff_list"))
        self.assertEqual(response.status_code, 200)
        listed_ids = {entry["user"].id for entry in response.context["staff_by_user"]}
        self.assertIn(self.receptionist_a.id, listed_ids)
        self.assertNotIn(self.manager_a.id, listed_ids)
        self.assertNotIn(self.receptionist_b.id, listed_ids)

    def test_manager_can_edit_receptionist_but_not_another_manager(self):
        self.client.force_login(self.manager_a)
        receptionist_record = PropertyStaff.objects.get(
            user=self.receptionist_a, property=self.property_a
        )
        manager_record = PropertyStaff.objects.get(
            user=self.manager_a, property=self.property_a
        )
        ok = self.client.get(
            reverse("properties:staff_update", args=[receptionist_record.pk])
        )
        forbidden = self.client.get(
            reverse("properties:staff_update", args=[manager_record.pk])
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(forbidden.status_code, 404)

    def test_owner_can_still_assign_the_manager_role(self):
        self.client.force_login(self.owner_a)
        response = self.client.post(
            reverse("properties:staff_create"), self._post_data(role="manager")
        )
        self.assertRedirects(response, reverse("properties:staff_list"))
        user = User.objects.get(email="newstaff@example.com")
        self.assertTrue(user.groups.filter(name="manager").exists())



class RoleCapabilityMatrixTests(TwoLandlordFixtureMixin, TestCase):
    """Every role only holds the sections it actually needs.

    Guards the matrix in ``properties.access.ROLE_CAPABILITIES``: a receptionist
    must no longer reach Finance/Reports, and an accountant must not reach the
    front-desk sections.
    """

    def setUp(self):
        super().setUp()
        self.manager = make_staff_user("mgr", self.property_a, "manager")
        self.accountant = make_staff_user("acct", self.property_a, "accountant")
        self.receptionist = make_staff_user("recp", self.property_a, "receptionist")

    def _superuser(self):
        return User.objects.create_superuser(
            username="root", password="pass12345", email="root@example.com"
        )

    def test_owner_holds_every_capability(self):
        self.assertEqual(get_capabilities(self.owner_a), set(ALL_CAPABILITIES))

    def test_superuser_holds_every_capability(self):
        self.assertEqual(get_capabilities(self._superuser()), set(ALL_CAPABILITIES))

    def test_manager_holds_every_capability(self):
        self.assertEqual(get_capabilities(self.manager), set(ALL_CAPABILITIES))

    def test_accountant_holds_the_money_sections(self):
        caps = get_capabilities(self.accountant)
        for capability in (
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
        ):
            with self.subTest(capability=capability):
                self.assertIn(capability, caps)

    def test_accountant_is_kept_out_of_operations(self):
        caps = get_capabilities(self.accountant)
        for capability in (
            "properties_manage",
            "staff_manage",
            "maintenance_view",
            "maintenance_manage",
            "tenants_manage",
            "leases_manage",
            "bookings_view",
            "bookings_manage",
            "sms_settings",
        ):
            with self.subTest(capability=capability):
                self.assertNotIn(capability, caps)

    def test_receptionist_holds_the_front_desk_sections(self):
        caps = get_capabilities(self.receptionist)
        for capability in (
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
        ):
            with self.subTest(capability=capability):
                self.assertIn(capability, caps)

    def test_receptionist_is_kept_out_of_the_money_sections(self):
        caps = get_capabilities(self.receptionist)
        for capability in (
            "properties_manage",
            "staff_manage",
            "rent_view",
            "rent_manage",
            "payments_report",
            "finance_view",
            "finance_manage",
            "sms_settings",
        ):
            with self.subTest(capability=capability):
                self.assertNotIn(capability, caps)

    def test_receptionist_and_accountant_do_not_share_the_same_surface(self):
        self.assertNotEqual(
            get_capabilities(self.receptionist), get_capabilities(self.accountant)
        )

    def test_user_can_follows_the_matrix(self):
        self.assertTrue(user_can(self.owner_a, "finance_view"))
        self.assertTrue(user_can(self.accountant, "finance_view"))
        self.assertFalse(user_can(self.receptionist, "finance_view"))
        self.assertFalse(user_can(self.accountant, "bookings_view"))
        self.assertTrue(user_can(self.receptionist, "bookings_view"))
        self.assertTrue(user_can(self.accountant, "rent_view"))
        self.assertFalse(user_can(self.receptionist, "staff_manage"))

    def test_anonymous_and_roleless_users_hold_nothing(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(get_capabilities(AnonymousUser()), set())
        self.assertFalse(user_can(AnonymousUser(), "payments_view"))

        roleless = User.objects.create_user(username="roleless", password="pass12345")
        self.assertEqual(get_user_roles(roleless), set())
        self.assertEqual(get_capabilities(roleless), set())
        self.assertFalse(user_can(roleless, "properties_view"))

    def test_active_property_staff_row_grants_the_role_without_a_group(self):
        # The role may live on the PropertyStaff row alone (group rows drift).
        self.receptionist.groups.clear()
        self.assertEqual(get_user_roles(self.receptionist), {"receptionist"})
        self.assertTrue(user_can(self.receptionist, "bookings_view"))

    def test_removing_group_and_assignment_revokes_everything(self):
        self.receptionist.groups.clear()
        PropertyStaff.objects.filter(user=self.receptionist).delete()
        self.assertEqual(get_user_roles(self.receptionist), set())
        self.assertEqual(get_capabilities(self.receptionist), set())
        self.assertFalse(user_can(self.receptionist, "bookings_view"))

    def test_tenant_group_is_not_a_back_office_role(self):
        from django.contrib.auth.models import Group

        tenant_group, _ = Group.objects.get_or_create(name="tenant")
        self.receptionist.groups.clear()
        PropertyStaff.objects.filter(user=self.receptionist).delete()
        self.receptionist.groups.add(tenant_group)
        self.assertEqual(get_user_roles(self.receptionist), set())
        self.assertEqual(get_capabilities(self.receptionist), set())


class SectionEnforcementTests(TwoLandlordFixtureMixin, TestCase):
    """Views reject a role that lacks the section capability (friendly 403)."""

    def setUp(self):
        super().setUp()
        self.accountant = make_staff_user("acct_a", self.property_a, "accountant")
        self.receptionist = make_staff_user("recp_a", self.property_a, "receptionist")

    def _assert_denied(self, user, url_name):
        self.client.force_login(user)
        response = self.client.get(reverse(url_name))
        self.assertEqual(response.status_code, 403, url_name)
        self.assertTemplateUsed(response, "403.html")

    def test_accountant_cannot_open_the_front_desk_sections(self):
        for url_name in (
            "bookings:booking_list",
            "bookings:guest_list",
            "bookings:calendar",
            "properties:unit_create",
            "properties:staff_list",
            "properties:maintenance_list",
            "tenants:tenant_create",
        ):
            with self.subTest(url_name=url_name):
                self._assert_denied(self.accountant, url_name)

    def test_accountant_can_open_the_money_sections(self):
        self.client.force_login(self.accountant)
        for url_name in (
            "properties:property_list",
            "tenants:tenant_list",
            "tenants:lease_list",
            "tenants:rent_list",
            "payments:payment_list",
            "payments:report",
            "finance:expense_list",
            "finance:purchase_list",
            "finance:stock_list",
            "finance:report",
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200, url_name)

    def test_receptionist_cannot_open_the_money_sections(self):
        for url_name in (
            "tenants:rent_list",
            "payments:report",
            "finance:expense_list",
            "finance:purchase_list",
            "finance:stock_list",
            "finance:report",
            "notifications:settings",
            "properties:staff_list",
            "properties:unit_create",
        ):
            with self.subTest(url_name=url_name):
                self._assert_denied(self.receptionist, url_name)

    def test_receptionist_can_open_the_front_desk_sections(self):
        self.client.force_login(self.receptionist)
        for url_name in (
            "properties:property_list",
            "properties:unit_list",
            "tenants:tenant_list",
            "tenants:lease_list",
            "bookings:booking_list",
            "bookings:guest_list",
            "bookings:calendar",
            "payments:payment_list",
            "properties:maintenance_list",
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200, url_name)

    def test_403_page_explains_which_section_and_role(self):
        self.client.force_login(self.receptionist)
        response = self.client.get(reverse("finance:report"))
        html = response.content.decode()
        self.assertIn("Receptionist", html)
        self.assertIn("Finance section", html)

    def test_receptionist_dashboard_hides_money_and_sms_widgets(self):
        self.client.force_login(self.receptionist)
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertNotIn('href="/finance/expenses/"', html)
        self.assertNotIn('href="/payments/report/"', html)
        self.assertNotIn('id="dashboardSmsForm"', html)
        self.assertIn('href="/bookings/"', html)
        self.assertIn('href="/tenants/"', html)

    def test_accountant_dashboard_hides_front_desk_widgets(self):
        self.client.force_login(self.accountant)
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertNotIn('href="/bookings/"', html)
        self.assertNotIn("Recent Bookings", html)
        self.assertIn('href="/finance/expenses/"', html)
        self.assertIn('href="/payments/report/"', html)

    def test_anonymous_visitor_is_redirected_to_login(self):
        response = self.client.get(reverse("finance:report"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_read_only_roles_can_render_the_property_pages(self):
        """Read-only roles see the pages but no manage buttons (no dead 403s)."""
        read_only_urls = (
            ("properties:property_list", ()),
            ("properties:property_detail", (self.property_a.slug,)),
            ("properties:block_list", ()),
            ("properties:block_detail", (self.block_a.pk,)),
            ("properties:unit_list", ()),
            ("properties:unit_detail", (self.long_unit_a.pk,)),
        )
        for user in (self.accountant, self.receptionist):
            self.client.force_login(user)
            for url_name, args in read_only_urls:
                with self.subTest(role=user.username, url_name=url_name):
                    response = self.client.get(reverse(url_name, args=args))
                    self.assertEqual(response.status_code, 200, url_name)
                    html = response.content.decode()
                    self.assertNotIn("Add Block", html)
                    self.assertNotIn("Add Unit", html)

    def test_read_only_accountant_can_render_tenant_and_lease_pages(self):
        from datetime import date, timedelta

        from tenants.models import Lease

        tenant = make_tenant(
            self.property_a, full_name="Ada Tenant", phone="+255712345678"
        )
        lease = Lease.objects.create(
            tenant=tenant,
            unit=self.long_unit_a,
            start_date=date.today() - timedelta(days=30),
            end_date=date.today() + timedelta(days=335),
            monthly_rent="500000.00",
            status="active",
        )

        self.client.force_login(self.accountant)
        for url_name, args in (
            ("tenants:tenant_list", ()),
            ("tenants:tenant_detail", (tenant.pk,)),
            ("tenants:lease_list", ()),
            ("tenants:lease_detail", (lease.pk,)),
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name, args=args))
                self.assertEqual(response.status_code, 200, url_name)

        # ...but the accountant gets no write actions on those pages.
        html = self.client.get(
            reverse("tenants:lease_detail", args=[lease.pk])
        ).content.decode()
        self.assertIn("Download PDF", html)
        self.assertNotIn("Renew Lease", html)
        self.assertNotIn("Send Expiry Reminder", html)

