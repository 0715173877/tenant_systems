"""
Management command to create the user groups and permissions for the tenant system.

Creates groups: owner, manager, receptionist, accountant
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.apps import apps


class Command(BaseCommand):
    help = "Create user groups (owner, manager, receptionist, accountant) and assign permissions"

    def handle(self, *args, **options):
        # Create groups
        owner_group, created = Group.objects.get_or_create(name="owner")
        if created:
            self.stdout.write(self.style.SUCCESS('Created "owner" group'))
        else:
            self.stdout.write('"owner" group already exists')

        manager_group, created = Group.objects.get_or_create(name="manager")
        if created:
            self.stdout.write(self.style.SUCCESS('Created "manager" group'))
        else:
            self.stdout.write('"manager" group already exists')

        receptionist_group, created = Group.objects.get_or_create(name="receptionist")
        if created:
            self.stdout.write(self.style.SUCCESS('Created "receptionist" group'))
        else:
            self.stdout.write('"receptionist" group already exists')

        accountant_group, created = Group.objects.get_or_create(name="accountant")
        if created:
            self.stdout.write(self.style.SUCCESS('Created "accountant" group'))
        else:
            self.stdout.write('"accountant" group already exists')

        # Get content types for models
        models_to_permit = [
            "property", "block", "unit", "unitamenity", "propertystaff", "maintenancerequest"
        ]

        # Owner gets full access to all property-related models
        owner_perms = []
        for model_name in models_to_permit:
            try:
                ct = ContentType.objects.get(app_label="properties", model=model_name)
                perms = Permission.objects.filter(content_type=ct)
                owner_perms.extend(perms)
            except ContentType.DoesNotExist:
                pass

        owner_group.permissions.add(*owner_perms)
        self.stdout.write(self.style.SUCCESS(f"Assigned {len(owner_perms)} permissions to 'owner' group"))

        # Manager gets view, change, add permissions (not delete for top-level)
        manager_perms = []
        for model_name in models_to_permit:
            try:
                ct = ContentType.objects.get(app_label="properties", model=model_name)
                perms = Permission.objects.filter(
                    content_type=ct,
                    codename__in=[
                        f"view_{model_name}",
                        f"change_{model_name}",
                        f"add_{model_name}",
                    ]
                )
                manager_perms.extend(perms)
            except ContentType.DoesNotExist:
                pass

        # Also add tenant, lease, booking, payment view permissions
        for app_label, model_names in [
            ("tenants", ["tenant", "lease"]),
            ("bookings", ["booking", "guest"]),
            ("payments", ["payment"]),
        ]:
            for model_name in model_names:
                try:
                    ct = ContentType.objects.get(app_label=app_label, model=model_name)
                    perms = Permission.objects.filter(
                        content_type=ct,
                        codename__in=[f"view_{model_name}", f"add_{model_name}", f"change_{model_name}"]
                    )
                    manager_perms.extend(perms)
                except ContentType.DoesNotExist:
                    pass

        manager_group.permissions.add(*manager_perms)
        self.stdout.write(self.style.SUCCESS(f"Assigned {len(manager_perms)} permissions to 'manager' group"))

        # Receptionist gets view and add on bookings, guests, tenants; view on units
        receptionist_perms = []
        receptionist_models = [
            ("properties", ["unit"]),
            ("tenants", ["tenant", "lease"]),
            ("bookings", ["booking", "guest"]),
        ]
        for app_label, model_names in receptionist_models:
            for model_name in model_names:
                try:
                    ct = ContentType.objects.get(app_label=app_label, model=model_name)
                    perms = Permission.objects.filter(
                        content_type=ct,
                        codename__in=[f"view_{model_name}", f"add_{model_name}", f"change_{model_name}"]
                    )
                    receptionist_perms.extend(perms)
                except ContentType.DoesNotExist:
                    pass

        receptionist_group.permissions.add(*receptionist_perms)
        self.stdout.write(self.style.SUCCESS(f"Assigned {len(receptionist_perms)} permissions to 'receptionist' group"))

        # Accountant gets view and change on payments, view on properties/blocks/units
        accountant_perms = []
        accountant_models = [
            ("properties", ["property", "block", "unit"]),
            ("payments", ["payment"]),
        ]
        for app_label, model_names in accountant_models:
            for model_name in model_names:
                try:
                    ct = ContentType.objects.get(app_label=app_label, model=model_name)
                    perms = Permission.objects.filter(
                        content_type=ct,
                        codename__in=[f"view_{model_name}"]
                    )
                    accountant_perms.extend(perms)
                except ContentType.DoesNotExist:
                    pass

        # Add payment change permission for accountants
        try:
            ct = ContentType.objects.get(app_label="payments", model="payment")
            change_perms = Permission.objects.filter(
                content_type=ct,
                codename__in=["change_payment", "add_payment"]
            )
            accountant_perms.extend(change_perms)
        except ContentType.DoesNotExist:
            pass

        accountant_group.permissions.add(*accountant_perms)
        self.stdout.write(self.style.SUCCESS(f"Assigned {len(accountant_perms)} permissions to 'accountant' group"))

        self.stdout.write(self.style.SUCCESS("\nAll groups created and permissions assigned successfully!"))
        self.stdout.write("\nGroups summary:")
        self.stdout.write("  - owner: Full access to property management")
        self.stdout.write("  - manager: Can manage properties, tenants, bookings and payments")
        self.stdout.write("  - receptionist: Handles bookings, guests, and tenant check-ins")
        self.stdout.write("  - accountant: Views properties, manages payments")
        self.stdout.write("\nAssign users to groups via Django admin or the assign_staff_to_property command.")
