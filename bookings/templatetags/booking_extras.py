from django import template
from django.template.defaultfilters import stringfilter
from datetime import date, timedelta

register = template.Library()

CURRENCY_SYMBOLS = {
    "TZS": "TSh",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "KES": "KSh",
    "UGX": "USh",
}


@register.filter
@stringfilter
def currency_symbol(value):
    """Return the currency symbol for a given currency code (e.g. TZS -> TSh, USD -> $)."""
    return CURRENCY_SYMBOLS.get(value.upper(), value)


@register.filter
def range_days(start_date, end_date):
    """Generate a list of dates from start_date to end_date (inclusive)."""
    delta = end_date - start_date
    return [start_date + timedelta(days=i) for i in range(delta.days + 1)]


@register.filter
def get_availability(bookings_dict, day):
    """Given a dict mapping date->status and a day number, return the status for that day."""
    for d, status in bookings_dict.items():
        if d.day == day:
            return status
    return "available"


@register.filter
def days_between(start, end):
    """Return the number of days between two dates."""
    return (end - start).days
