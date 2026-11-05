from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import FoodItem, RegistrationProfile, ResearchPaper, ResearchSubmission, SystemLog


def _safe_unregister(model):
    try:
        admin.site.unregister(model)
    except admin.sites.NotRegistered:
        pass


_safe_unregister(User)
_safe_unregister(RegistrationProfile)
_safe_unregister(FoodItem)


class RegistrationProfileInline(admin.StackedInline):
    model = RegistrationProfile
    can_delete = False
    verbose_name_plural = "Profile"
    fk_name = "user"
    fields = ("middle_name", "login_as", "program", "college")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = (RegistrationProfileInline,)
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "get_role",
        "is_staff",
        "is_superuser",
        "is_active",
        "date_joined",
    )
    list_filter = (
        "is_staff",
        "is_superuser",
        "is_active",
        "date_joined",
        "registration_profile__login_as",
    )
    search_fields = (
        "username",
        "email",
        "first_name",
        "last_name",
        "registration_profile__middle_name",
    )
    ordering = ("-date_joined",)

    def get_role(self, obj):
        if obj.is_superuser:
            return "Super Admin"
        if obj.is_staff:
            return "Admin"
        profile = getattr(obj, "registration_profile", None)
        return profile.login_as if profile else "N/A"

    get_role.short_description = "Role"

    def get_inline_instances(self, request, obj=None):
        if not obj:
            return list()
        return super().get_inline_instances(request, obj)


@admin.register(FoodItem)
class FoodItemAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "created_at", "updated_at")
    search_fields = ("name", "description")
    list_filter = ("created_at",)
    ordering = ("-created_at",)


@admin.register(ResearchPaper)
class ResearchPaperAdmin(admin.ModelAdmin):
    list_display = ("title", "authors", "keywords", "published_date", "created_at")
    search_fields = ("title", "authors", "abstract", "keywords")
    list_filter = ("published_date", "created_at")
    ordering = ("-created_at",)


@admin.register(ResearchSubmission)
class ResearchSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "student",
        "get_student_role",
        "status",
        "submitted_at",
        "reviewed_at",
    )
    search_fields = (
        "title",
        "abstract",
        "keywords",
        "admin_notes",
        "student__username",
        "student__first_name",
        "student__last_name",
    )
    list_filter = ("status", "submitted_at", "reviewed_at")
    ordering = ("-submitted_at",)
    list_select_related = ("student",)
    raw_id_fields = ("student",)

    def get_student_role(self, obj):
        profile = getattr(obj.student, "registration_profile", None)
        return profile.login_as if profile else "N/A"

    get_student_role.short_description = "Role"


@admin.register(SystemLog)
class SystemLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "get_user_name",
        "get_user_role",
        "log_type",
        "action_summary",
        "ip_address",
    )
    list_filter = ("log_type", "created_at", "user__is_staff", "user__is_superuser")
    search_fields = (
        "action",
        "ip_address",
        "user_agent",
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
    )
    ordering = ("-created_at",)
    list_select_related = ("user",)
    readonly_fields = (
        "user",
        "log_type",
        "action",
        "ip_address",
        "user_agent",
        "created_at",
    )
    list_per_page = 50

    def get_user_name(self, obj):
        return obj.user_display_name()

    get_user_name.short_description = "User"

    def get_user_role(self, obj):
        return obj.user_role_label()

    get_user_role.short_description = "Role"

    def action_summary(self, obj):
        return (obj.action or "")[:100]

    action_summary.short_description = "Action"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.site_header = "FoodHub Super Admin"
admin.site.site_title = "FoodHub Super Admin Portal"
admin.site.index_title = "All System Controls"
