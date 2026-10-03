from django.test import TestCase
from django.urls import reverse

from config.test_factories import TwoLandlordFixtureMixin
from .access import (
    PropertyScopedMixin,
    get_accessible_properties,
    get_accessible_property_ids,
    is_owner,
)


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
