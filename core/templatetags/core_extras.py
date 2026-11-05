from datetime import date, datetime

from django import template
from django.utils import timezone

from core.models import account_display_name

register = template.Library()


@register.filter
def account_name(user):
    return account_display_name(user)


@register.filter
def local_datetime(value):
    """Turns a stored ISO date or date-time string into a value for |date,
    shown in the site's time zone (Philippine time). None if unreadable."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        return value
    else:
        text = str(value or "").strip()
        try:
            if len(text) == 10:  # a plain date, e.g. "2025-01-15"
                return date.fromisoformat(text)
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    return parsed if timezone.is_naive(parsed) else timezone.localtime(parsed)
