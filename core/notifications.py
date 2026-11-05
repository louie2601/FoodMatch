from django.contrib.auth.models import User
from django.db.models import Q
from django.urls import reverse

from .models import AdminModuleAccess, Notification


def notify(recipients, category, title, message="", url_name="", exclude=None):
    """Create one in-app notification per recipient. `exclude` is the acting user,
    who never needs to be told about their own action."""
    link = reverse(url_name) if url_name else ""
    seen = set()
    rows = []
    for user in recipients:
        if user is None or user.pk in seen or (exclude is not None and user.pk == exclude.pk):
            continue
        seen.add(user.pk)
        rows.append(Notification(recipient=user, category=category, title=title, message=message, link=link))
    Notification.objects.bulk_create(rows)


def staff_with_module(module):
    """Active Super Admins plus active Admins granted `module`."""
    granted_ids = AdminModuleAccess.objects.filter(module=module).values("user_id")
    return User.objects.filter(is_active=True, is_staff=True).filter(
        Q(is_superuser=True) | Q(pk__in=granted_ids)
    )


def super_admins():
    return User.objects.filter(is_active=True, is_superuser=True)
