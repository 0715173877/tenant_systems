"""
Shared helpers for building multi-tenant fixtures in tests.

Two landlords (``owner_a`` / ``owner_b``) each get their own property, block
and units so tests can assert that one landlord never sees the other's data.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from properties.models import Property, Block, Unit

User = get_user_model()


def make_owner(username="owner", password="pass12345"):
    """Create a user in the ``owner`` group (a landlord)."""
    user = User.objects.create_user(username=username, password=password)
    group, _ = Group.objects.get_or_create(name="owner")
    user.groups.add(group)
    return user


def make_property(owner, name):
    return Property.objects.create(owner=owner, name=name)


def make_block(prop, name="Block A"):
    return Block.objects.create(property=prop, name=name)


def make_unit(block, number, rental_type="long_term", **kwargs):
    defaults = {
        "monthly_rent": "500000.00",
        "deposit_amount": "500000.00",
        "nightly_rate": "50000.00",
        "is_available": True,
    }
    defaults.update(kwargs)
    return Unit.objects.create(
        block=block,
        unit_number=number,
        rental_type=rental_type,
        **defaults,
    )


class TwoLandlordFixtureMixin:
    """Mixin that builds two isolated landlords, each with a property/block/units."""

    def setUp(self):
        super().setUp()
        self.owner_a = make_owner("owner_a")
        self.owner_b = make_owner("owner_b")

        self.property_a = make_property(self.owner_a, "Property A")
        self.property_b = make_property(self.owner_b, "Property B")

        self.block_a = make_block(self.property_a, "Block A")
        self.block_b = make_block(self.property_b, "Block B")

        self.long_unit_a = make_unit(self.block_a, "A1", "long_term")
        self.long_unit_b = make_unit(self.block_b, "B1", "long_term")
        self.short_unit_a = make_unit(self.block_a, "A2", "short_term")
        self.short_unit_b = make_unit(self.block_b, "B2", "short_term")
