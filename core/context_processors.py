from django.utils.functional import SimpleLazyObject

from .models import (
    AdminModule,
    AdminModuleAccess,
    DeletionRequestStatus,
    LandingSettings,
    RegistrationProfile,
    RegistrationStatus,
    UserDeletionRequest,
)


def pending_deletion_count(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_superuser:
        return {}
    return {
        "pending_deletion_count": UserDeletionRequest.objects.filter(
            status=DeletionRequestStatus.PENDING
        ).count()
    }


def registration_requests_nav(request):
    """Sidebar link to Registration Requests (Super Admins, and Admins with the
    Manage Users module) with the number of groups waiting for approval."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not (user.is_staff or user.is_superuser):
        return {}
    if not user.is_superuser and not AdminModuleAccess.objects.filter(user=user, module=AdminModule.MANAGE_USERS).exists():
        return {}
    return {
        "can_review_registrations": True,
        "pending_registration_count": RegistrationProfile.objects.filter(
            approval_status=RegistrationStatus.PENDING, user__is_staff=False, user__is_superuser=False
        ).count(),
    }


NOTIFICATIONS_SHOWN = 10


def notifications(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    qs = user.notifications.all()
    return {
        "notification_unread_count": qs.filter(is_read=False).count(),
        "notification_items": list(qs[:NOTIFICATIONS_SHOWN]),
    }


def landing_site(request):
    return {"landing_site": SimpleLazyObject(LandingSettings.load)}


SETTINGS_NAV_MODULES = (AdminModule.MANAGE_CATEGORIES, AdminModule.PROGRAMS_COURSES, AdminModule.LANDING_PAGE)


def admin_settings_access(request):
    """Which Settings pages the signed-in account may open, for the sidebar."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    if user.is_superuser:
        return {"settings_access": {m.value: True for m in SETTINGS_NAV_MODULES}}
    if not user.is_staff:
        return {}
    granted = set(
        AdminModuleAccess.objects.filter(user=user, module__in=SETTINGS_NAV_MODULES).values_list("module", flat=True)
    )
    return {"settings_access": {m.value: m.value in granted for m in SETTINGS_NAV_MODULES}}
