"""
Management command to populate the database with sample data:
- Creates a sample property with Block A (long-term), Block B (short-term)
- Sample tenants, leases, guests, bookings, and payments
"""
from decimal import Decimal
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from properties.models import Property, Block, Unit, MaintenanceRequest, OwnerProfile
from properties.models import PropertyStaff
from tenants.models import Tenant, Lease
from bookings.models import Guest, Booking
from payments.models import Payment


class Command(BaseCommand):
    help = "Seed the database with sample data"

    def handle(self, *args, **options):
        self._create_property_and_blocks()
        self._create_tenants_and_leases()
        self._create_guests_and_bookings()
        self._create_payments()
        self.stdout.write(self.style.SUCCESS("Database seeded successfully!"))

    # ----- Property, Blocks & Units -----

    def _create_property_and_blocks(self):
        # Ensure the "owner" group exists
        from django.contrib.auth.models import Group
        owner_group, _ = Group.objects.get_or_create(name="owner")

        # Create a default owner if none exists
        owner, _ = User.objects.get_or_create(
            username="owner1",
            defaults={
                "email": "owner@example.com",
                "is_staff": True,
            },
        )
        if not owner.password:
            owner.set_password("owner123")
            owner.save()
        # Add owner to the "owner" group so the dashboard can find their properties
        owner.groups.add(owner_group)

        # Create sample property
        prop, _ = Property.objects.get_or_create(
            name="Mwema Apartments",
            defaults={
                "owner": owner,
                "location": "Dar es Salaam, Tanzania",
                "description": "A beautiful apartment complex with both long-term and short-term rental options",
            },
        )

        block_a, _ = Block.objects.get_or_create(
            property=prop,
            name="A",
            defaults={
                "description": "Block A - 10 traditional long-term rental units",
                "location": "North Wing",
            },
        )
        block_b, _ = Block.objects.get_or_create(
            property=prop,
            name="B",
            defaults={
                "description": "Block B - 9 short-term rental units (Airbnb-style)",
                "location": "South Wing",
            },
        )

        # 10 long-term units for Block A
        for i in range(1, 11):
            unit, created = Unit.objects.get_or_create(
                block=block_a,
                unit_number=f"A-{i:02d}",
                defaults={
                    "rental_type": "long_term",
                    "unit_type": "two_bedroom" if i <= 6 else "one_bedroom",
                    "monthly_rent": Decimal("450000") if i <= 6 else Decimal("350000"),
                    "deposit_amount": Decimal("450000") if i <= 6 else Decimal("350000"),
                    "is_available": True,
                },
            )

        # 9 short-term units for Block B
        for i in range(1, 10):
            Unit.objects.get_or_create(
                block=block_b,
                unit_number=f"B-{i:02d}",
                defaults={
                    "rental_type": "short_term",
                    "unit_type": "studio" if i <= 5 else "one_bedroom",
                    "nightly_rate": Decimal("65000") if i <= 5 else Decimal("85000"),
                    "weekly_rate": Decimal("350000") if i <= 5 else Decimal("500000"),
                    "cleaning_fee": Decimal("25000"),
                    "max_guests": 2 if i <= 5 else 3,
                    "is_available": True,
                },
            )

        # Create sample owner payment profile
        OwnerProfile.objects.get_or_create(
            owner=owner,
            defaults={
                "phone": "+255712000000",
                "email": "owner@example.com",
                "bank_name": "CRDB Bank",
                "bank_account_name": "Mwema Properties Ltd",
                "bank_account_number": "0150123456789",
                "bank_branch": "Mlimani City",
                "bank_currency": "TZS",
                "mpesa_number": "0712000000",
                "mpesa_account_name": "Mwema Apartments",
                "payment_instructions": "Please use your lease/booking number as the payment reference.",
            },
        )

        self.stdout.write(
            self.style.SUCCESS("✓ Created sample property with Block A (10 units) and Block B (9 units)")
        )

    # ----- Tenants & Leases -----

    def _create_tenants_and_leases(self):
        prop = Property.objects.first()
        if not prop:
            return
        block_a_units = Unit.objects.filter(block__property=prop, block__name="A")
        tenants_data = [
            ("John Mwangi", "+255712000001", "john@email.com"),
            ("Sarah Joseph", "+255712000002", "sarah@email.com"),
            ("Peter Kamau", "+255712000003", "peter@email.com"),
            ("Grace Lema", "+255712000004", "grace@email.com"),
            ("David Nkya", "+255712000005", "david@email.com"),
            ("Esther Mushi", "+255712000006", "esther@email.com"),
            ("James Ochieng", "+255712000007", "james@email.com"),
            ("Ruth Nyagah", "+255712000008", "ruth@email.com"),
            ("Samuel Kilonzo", "+255712000009", "samuel@email.com"),
            ("Mary Malema", "+255712000010", "mary@email.com"),
        ]

        today = date.today()

        for idx, (name, phone, email) in enumerate(tenants_data):
            tenant, created = Tenant.objects.get_or_create(
                phone_number=phone,
                defaults={
                    "full_name": name,
                    "email": email,
                    "property": prop,
                    "is_active": True,
                },
            )
            if created or not Lease.objects.filter(tenant=tenant).exists():
                unit = block_a_units[idx]
                Lease.objects.create(
                    tenant=tenant,
                    unit=unit,
                    start_date=today + timedelta(days=-30 * idx),
                    end_date=today + timedelta(days=335 - 30 * idx),
                    monthly_rent=unit.monthly_rent,
                    deposit_paid=True,
                    deposit_amount=unit.deposit_amount,
                    status="active",
                )

        self.stdout.write(
            self.style.SUCCESS("✓ Created 10 tenants with active leases")
        )

    # ----- Guests & Bookings -----

    def _create_guests_and_bookings(self):
        prop = Property.objects.first()
        if not prop:
            return
        block_b_units = list(Unit.objects.filter(block__property=prop, block__name="B"))
        if not block_b_units:
            self.stdout.write(self.style.WARNING("No Block B units found, creating them..."))
            block_b = Block.objects.get(property=prop, name="B")
            for i in range(1, 10):
                unit, _ = Unit.objects.get_or_create(
                    block=block_b,
                    unit_number=f"B-{i:02d}",
                    defaults={
                        "rental_type": "short_term",
                        "unit_type": "studio" if i <= 5 else "one_bedroom",
                        "nightly_rate": Decimal("65000") if i <= 5 else Decimal("85000"),
                        "weekly_rate": Decimal("350000") if i <= 5 else Decimal("500000"),
                        "cleaning_fee": Decimal("25000"),
                        "max_guests": 2 if i <= 5 else 3,
                        "is_available": True,
                    },
                )
            block_b_units = list(Unit.objects.filter(block__property=prop, block__name="B"))

        guests_data = [
            ("Alice Mwenda", "+255713000001"),
            ("Bob Mushi", "+255713000002"),
            ("Carol Daudi", "+255713000003"),
            ("Daniel Mushi", "+255713000004"),
            ("Eve Sanga", "+255713000005"),
            ("Frank Ndosi", "+255713000006"),
            ("Grace Mwita", "+255713000007"),
            ("Henry Kalala", "+255713000008"),
        ]

        today = date.today()
        guests = []
        for name, phone in guests_data:
            guest, _ = Guest.objects.get_or_create(
                phone_number=phone,
                defaults={"full_name": name, "property": prop, "is_active": True},
            )
            guests.append(guest)

        booking_statuses = ["confirmed", "checked_in", "checked_out", "pending"]
        for idx, guest in enumerate(guests):
            unit = block_b_units[idx % len(block_b_units)]
            days_offset = idx * 7
            Booking.objects.get_or_create(
                guest=guest,
                unit=unit,
                check_in=today + timedelta(days=days_offset),
                check_out=today + timedelta(days=days_offset + 3),
                defaults={
                    "number_of_guests": 2,
                    "status": booking_statuses[idx % len(booking_statuses)],
                },
            )

        self.stdout.write(
            self.style.SUCCESS("✓ Created 8 guests with sample bookings")
        )

    # ----- Payments -----

    def _create_payments(self):
        leases = Lease.objects.filter(status="active")[:5]
        for lease in leases:
            Payment.objects.get_or_create(
                lease=lease,
                payment_date=lease.start_date,
                payment_type="deposit",
                defaults={
                    "amount": lease.deposit_amount or lease.monthly_rent,
                    "payment_method": "mpesa",
                    "status": "completed",
                },
            )
            Payment.objects.get_or_create(
                lease=lease,
                payment_date=date.today() - timedelta(days=5),
                payment_type="rent",
                defaults={
                    "amount": lease.monthly_rent,
                    "payment_method": "cash",
                    "status": "completed",
                },
            )

        bookings = Booking.objects.filter(status="confirmed")[:3]
        for booking in bookings:
            Payment.objects.get_or_create(
                booking=booking,
                payment_date=booking.check_in,
                payment_type="booking",
                defaults={
                    "amount": booking.total_amount or Decimal("195000"),
                    "payment_method": "mpesa",
                    "status": "completed",
                },
            )

        self.stdout.write(
            self.style.SUCCESS("✓ Created sample payments")
        )
