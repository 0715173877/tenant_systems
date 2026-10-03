"""Generate monthly rent invoices for active leases (arrears tracking).

Examples::

    # Invoices for the current month
    python manage.py generate_rent_invoices

    # Backfill January through March 2026
    python manage.py generate_rent_invoices --start 2026-01 --end 2026-03

    # Preview without writing anything
    python manage.py generate_rent_invoices --start 2026-03 --dry-run
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from tenants.models import Lease
from tenants.services import generate_rent_invoices, iter_months


def parse_month(value):
    """Parse a ``YYYY-MM`` string into the first day of that month."""
    try:
        year, month = value.split("-")
        return date(int(year), int(month), 1)
    except (AttributeError, ValueError):
        raise CommandError(f"Invalid month '{value}', expected format YYYY-MM")


class Command(BaseCommand):
    help = "Generate monthly rent invoices for active leases (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            help="First billing month as YYYY-MM (default: current month).",
        )
        parser.add_argument(
            "--end",
            help="Last billing month as YYYY-MM (default: same as --start).",
        )
        parser.add_argument(
            "--due-day",
            type=int,
            default=5,
            help="Day of the month rent is due (default: 5).",
        )
        parser.add_argument(
            "--lease-id",
            type=int,
            help="Only generate for this lease id.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing to the database.",
        )

    def handle(self, *args, **options):
        today = date.today()
        start = parse_month(options["start"]) if options["start"] else today.replace(day=1)
        end = parse_month(options["end"]) if options["end"] else start
        if end < start:
            raise CommandError("--end cannot be earlier than --start")

        due_day = options["due_day"]
        if not 1 <= due_day <= 31:
            raise CommandError("--due-day must be between 1 and 31")

        leases = Lease.objects.filter(status="active").select_related("tenant")
        if options["lease_id"]:
            leases = leases.filter(pk=options["lease_id"])
            if not leases.exists():
                raise CommandError(f"No active lease with id {options['lease_id']}")

        dry_run = options["dry_run"]
        total_created = total_skipped = 0
        for month in iter_months(start, end):
            created, skipped = generate_rent_invoices(
                month, leases=leases, due_day=due_day, dry_run=dry_run
            )
            total_created += created
            total_skipped += skipped
            verb = "Would create" if dry_run else "Created"
            self.stdout.write(
                f"{month.strftime('%b %Y')}: {verb} {created} invoice(s), "
                f"skipped {skipped} existing."
            )

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Done. {total_created} created, {total_skipped} skipped."
        ))
