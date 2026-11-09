from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class LoginAs(models.TextChoices):
    STUDENT = "Student", "Student"


class College(models.Model):
    """A college offered on the sign-up forms. Managed from Settings."""

    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Program(models.Model):
    """A program or course offered on the sign-up forms. Managed from Settings."""

    name = models.CharField(max_length=255, unique=True)
    college = models.ForeignKey(
        College, on_delete=models.SET_NULL, null=True, blank=True, related_name="programs"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def active_college_names():
    return list(College.objects.filter(is_active=True).values_list("name", flat=True))


def active_program_names():
    return list(Program.objects.filter(is_active=True).values_list("name", flat=True))


class FoodItem(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class FoodCategory(models.Model):
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subcategories",
    )
    # Optional photo shown on the landing page's "Browse by food category" cards.
    image = models.ImageField(upload_to="landing/categories/", blank=True)
    image_alt = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["name", "parent"], name="unique_category_name_per_parent"),
        ]

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} › {self.name}"
        return self.name


class ResearchPaper(models.Model):
    MONTH_CHOICES = [
        ("January", "January"), ("February", "February"), ("March", "March"), ("April", "April"),
        ("May", "May"), ("June", "June"), ("July", "July"), ("August", "August"),
        ("September", "September"), ("October", "October"), ("November", "November"), ("December", "December"),
    ]

    title = models.CharField(max_length=200)
    authors = models.CharField(max_length=500)
    adviser = models.CharField(max_length=255, blank=True, default="")
    abstract = models.TextField()
    keywords = models.CharField(max_length=255, blank=True)
    food_category = models.ForeignKey(
        FoodCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    published_date = models.DateField(null=True, blank=True)
    published_month = models.CharField(max_length=12, null=True, blank=True, choices=MONTH_CHOICES)
    published_year = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class ResearchSubmissionStatus(models.TextChoices):
    PENDING = "Pending", "Pending"
    APPROVED = "Approved", "Approved"
    REJECTED = "Rejected", "Rejected"


class SystemLogType(models.TextChoices):
    LOGIN = "Login", "Login"
    LOGOUT = "Logout", "Logout"
    ACTIVITY = "Activity", "Activity"


class SystemLog(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="system_logs",
    )
    log_type = models.CharField(
        max_length=20,
        choices=SystemLogType.choices,
        default=SystemLogType.ACTIVITY,
    )
    action = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["log_type"]),
        ]

    def user_role_label(self):
        if not self.user:
            return "N/A"
        if self.user.is_superuser:
            return "Super Admin"
        if self.user.is_staff:
            return "Admin"
        profile = getattr(self.user, "registration_profile", None)
        return profile.login_as if profile else "N/A"

    def user_display_name(self):
        if not self.user:
            # Failed sign-ins for a username that doesn't exist have no account.
            return "Unknown user" if self.action.startswith("Failed sign-in attempt") else "System"
        return account_display_name(self.user)

    def __str__(self):
        return f"[{timezone.localtime(self.created_at):%Y-%m-%d %H:%M}] {self.log_type} - {self.user_display_name()}"


class ResearchSubmission(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="research_submissions")
    title = models.CharField(max_length=255)
    authors = models.CharField(max_length=500, blank=True)
    adviser = models.CharField(max_length=255, blank=True)
    abstract = models.TextField(blank=True)
    keywords = models.CharField(max_length=255, blank=True)
    food_category = models.ForeignKey(
        FoodCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    published_date = models.DateField(null=True, blank=True)
    published_month = models.CharField(max_length=12, null=True, blank=True, choices=ResearchPaper.MONTH_CHOICES)
    published_year = models.IntegerField(null=True, blank=True)
    document = models.FileField(upload_to="research_submissions/")
    # SHA-256 of the uploaded file, used to block uploading the same file twice.
    document_hash = models.CharField(max_length=64, blank=True, db_index=True)
    # Similarity Check used to re-extract this document's text (PyPDF2) on
    # every single check, for every approved submission -- with real thesis
    # PDFs running several MB each, that added up to minutes per check. NULL
    # means "not extracted yet"; an empty string is a legitimate cached result
    # (e.g. a scan-only PDF, since Similarity Check doesn't OCR). Populated
    # lazily, once, the first time a check needs it (see
    # build_repository_documents_from_submissions in utils.py).
    cached_document_text = models.TextField(null=True, blank=True, default=None)
    # Meaning vectors of the document's passages from the AI model (see
    # core/semantic.py), saved once so a Similarity Check only embeds the
    # uploaded file. The version says which model/passage settings made them.
    semantic_index = models.BinaryField(null=True, blank=True, editable=False)
    semantic_index_version = models.CharField(max_length=60, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=ResearchSubmissionStatus.choices,
        default=ResearchSubmissionStatus.PENDING,
    )
    admin_notes = models.TextField(blank=True)
    drive_file_id = models.CharField(max_length=255, blank=True)
    drive_file_url = models.URLField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.title} - {self.student.get_full_name().strip() or self.student.username}"


class SimilarityCheckRecord(models.Model):
    """One run of the Similarity Check tool, by any role. Students see only
    their own records; a staff Admin sees only their own; a Super Admin sees
    every record (Admin, Super Admin, and Student) in one combined view."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="similarity_check_records")
    file_name = models.CharField(max_length=255, blank=True)
    top_score_percent = models.FloatField(default=0.0)
    top_match_title = models.CharField(max_length=255, blank=True)
    similarity_level = models.CharField(max_length=20, blank=True)
    similarity_label = models.CharField(max_length=40, blank=True)
    total_compared = models.PositiveIntegerField(default=0)
    # Top few matches at the time of the check (title, score_percent,
    # similarity_label, metadata_only) -- kept for a detail view later without
    # needing to re-run the comparison.
    results_snapshot = models.JSONField(default=list, blank=True)
    # SHA-256 of the checked file, and whether that exact file may now be
    # submitted (low similarity and a finished paper). My Submissions only
    # accepts a file with such a record -- see student_submissions_view.
    file_hash = models.CharField(max_length=64, blank=True, db_index=True)
    upload_allowed = models.BooleanField(default=False)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-checked_at"]

    def role_label(self):
        if self.user.is_superuser:
            return "Super Admin"
        if self.user.is_staff:
            return "Admin"
        return "Student"

    def __str__(self):
        return f"[{timezone.localtime(self.checked_at):%Y-%m-%d %H:%M}] {self.file_name} by {account_display_name(self.user)}"


class RegistrationStatus(models.TextChoices):
    PENDING = "Pending", "Waiting for approval"
    APPROVED = "Approved", "Approved"


class RegistrationProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="registration_profile")
    middle_name = models.CharField(max_length=100, blank=True)
    login_as = models.CharField(max_length=20, choices=LoginAs.choices)
    program = models.CharField(max_length=255, blank=True)
    college = models.CharField(max_length=120, blank=True)
    group_name = models.CharField(max_length=150, blank=True)
    # A group that signs up on the Registration page waits here (and cannot
    # log in) until an Admin or Super Admin approves it. Accounts made any
    # other way are approved from the start.
    approval_status = models.CharField(
        max_length=20, choices=RegistrationStatus.choices, default=RegistrationStatus.APPROVED
    )
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return account_display_name(self.user)


class AdminModule(models.TextChoices):
    MANAGE_USERS = "manage_users", "Manage Users"
    MANAGE_SUBMISSIONS = "manage_submissions", "Manage Submissions"
    RESEARCH_REPOSITORY = "research_repository", "Research Repository"
    ADD_RESEARCH = "add_research", "Add Research to Repository"
    MANAGE_CATEGORIES = "manage_categories", "Manage Categories"
    SIMILARITY_CHECK = "similarity_check", "Similarity Check"
    SIMILARITY_RECORDS = "similarity_records", "Similarity Check Records"
    SYSTEM_LOGS = "system_logs", "System Logs"
    REPORTS = "reports", "Reports & Export"
    LANDING_PAGE = "landing_page", "Landing Page Settings"
    PROGRAMS_COURSES = "programs_courses", "Programs & Colleges"


class AdminModuleAccess(models.Model):
    """A module a Super Admin has granted to an Admin. No row means no access
    (least privilege); Super Admins bypass this table entirely."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="module_access")
    module = models.CharField(max_length=40, choices=AdminModule.choices)
    granted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "module"], name="unique_admin_module_access"),
        ]

    def __str__(self):
        return f"{account_display_name(self.user)} → {self.get_module_display()}"


class NotificationCategory(models.TextChoices):
    SUBMISSION = "submission", "Submission"
    REVIEW = "review", "Review"
    ACCOUNT = "account", "Account"
    DELETION = "deletion", "Deletion Request"
    PRIVILEGE = "privilege", "Privilege"


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    category = models.CharField(max_length=20, choices=NotificationCategory.choices)
    title = models.CharField(max_length=150)
    message = models.TextField(blank=True)
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read"])]

    def __str__(self):
        return f"{self.title} → {account_display_name(self.recipient)}"


MAX_GROUP_MEMBERS = 5


class GroupMember(models.Model):
    """A person registered under a student account. One student account is a
    research group and can hold up to MAX_GROUP_MEMBERS members (leader first)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="group_members")
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]

    def display_name(self):
        middle = f" {self.middle_name.strip()[:1]}." if self.middle_name.strip() else ""
        return f"{self.first_name.strip()}{middle} {self.last_name.strip()}".strip()

    def __str__(self):
        return self.display_name()


class DeletionRequestStatus(models.TextChoices):
    PENDING = "Pending", "Pending"
    APPROVED = "Approved", "Approved"
    REJECTED = "Rejected", "Rejected"


class AccountDeactivation(models.Model):
    """Why an account is currently deactivated. Exists only while the account
    is inactive; removed when it is activated again."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="deactivation")
    reason = models.TextField()
    deactivated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    deactivated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{account_display_name(self.user)} deactivated"


class UserDeletionRequest(models.Model):
    target_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        related_name="deletion_requests",
    )
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="deletion_requests_made",
    )
    reason = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=DeletionRequestStatus.choices,
        default=DeletionRequestStatus.PENDING,
    )
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deletion_requests_reviewed",
    )
    review_notes = models.TextField(blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["-requested_at"]),
        ]

    def target_display_name(self):
        if not self.target_user:
            return "Unknown"
        full_name = self.target_user.get_full_name().strip()
        return full_name or self.target_user.username

    def requester_display_name(self):
        if not self.requested_by:
            return "System"
        full_name = self.requested_by.get_full_name().strip()
        return full_name or self.requested_by.username

    def reviewer_display_name(self):
        if not self.reviewed_by:
            return "N/A"
        full_name = self.reviewed_by.get_full_name().strip()
        return full_name or self.reviewed_by.username

    def __str__(self):
        return f"{self.status} | Delete request for {self.target_display_name()} by {self.requester_display_name()} ({timezone.localtime(self.requested_at):%Y-%m-%d %H:%M})"


class PendingUserInviteRole(models.TextChoices):
    STUDENT = "Student", "Student"
    ADMIN = "Admin", "Admin"
    SUPER_ADMIN = "Super Admin", "Super Admin"


class PendingUserInvite(models.Model):
    """An account created via Admin/Super Admin 'Add User' that has not been
    written to the User table yet. It only becomes a real User (with a
    RegistrationProfile) once the invited person logs in with these
    credentials and completes their onboarding profile.
    """

    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255)
    login_as = models.CharField(max_length=20, choices=PendingUserInviteRole.choices)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_invites",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def creator_display_name(self):
        if not self.created_by:
            return "System"
        full_name = self.created_by.get_full_name().strip()
        return full_name or self.created_by.username

    def __str__(self):
        return f"Pending invite: {self.username} ({self.login_as})"


class PasswordResetOTP(models.Model):
    """One-time code emailed to a user during the Forgot Password flow. Only a
    hash of the code is stored."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_reset_otps")
    purpose = models.CharField(max_length=10, default="reset")  # "reset" (forgot password) or "change"
    code_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    verified_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Password reset OTP for {self.user.username} ({timezone.localtime(self.created_at):%Y-%m-%d %H:%M})"


def group_member_names(user):
    """Display names of the members under a student account, leader first."""
    if not getattr(user, "pk", None) or user.pk < 0:
        return []
    return [member.display_name() for member in user.group_members.all()]


def account_display_name(user):
    """How an account is shown to other people: staff by personal name, student
    accounts (research groups) by group name, else the leader's name (+ others)."""
    if user is None:
        return "System"
    personal = user.get_full_name().strip() or user.username
    if user.is_staff or user.is_superuser:
        return personal
    profile = getattr(user, "registration_profile", None)
    group_name = (getattr(profile, "group_name", "") or "").strip()
    if group_name:
        return group_name
    members = group_member_names(user)
    if len(members) > 1:
        return f"{members[0]} +{len(members) - 1}"
    return members[0] if members else personal


# ---------------------------------------------------------------------------
# Landing page content (edited in Landing Page Settings)
# ---------------------------------------------------------------------------

class LandingIcon(models.TextChoices):
    SEARCH = "search", "Search"
    UPLOAD = "upload", "Upload"
    CHECK = "check", "Check mark"
    SHIELD = "shield", "Shield"
    CHART = "chart", "Chart"
    USERS = "users", "Users"
    BOOK = "book", "Book"
    CLIPBOARD = "clipboard", "Clipboard"
    SPARKLES = "sparkles", "Sparkles"
    BELL = "bell", "Bell"


class LandingSettings(models.Model):
    """Single-row settings for the public landing page; always use load()."""

    hero_headline = models.CharField(max_length=150, default="Discover, Compare & Publish Food Research")
    hero_subtitle = models.CharField(
        max_length=300,
        default="FOOD MATCH helps students check their food research for similarity against the repository before they submit, and helps the college keep every approved study in one place.",
    )
    footer_about = models.CharField(
        max_length=300,
        default="FOOD MATCH is the college's food research repository and similarity checking system.",
    )
    contact_email = models.EmailField(blank=True, default="info@foodhub.com")
    contact_phone = models.CharField(max_length=50, blank=True, default="+1 234 567 8900")
    contact_address = models.CharField(max_length=255, blank=True, default="123 Food Street, City")
    facebook_url = models.URLField(blank=True)
    website_url = models.URLField(blank=True)

    show_hero = models.BooleanField(default=True)
    show_stats = models.BooleanField(default=True)
    show_announcements = models.BooleanField(default=True)
    show_how_it_works = models.BooleanField(default=True)
    show_features = models.BooleanField(default=True)
    show_recent_research = models.BooleanField(default=True)
    show_categories = models.BooleanField(default=True)
    show_gallery = models.BooleanField(default=True)
    show_colleges = models.BooleanField(default=True)
    show_faq = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Landing settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Landing page settings"


class HeroSlide(models.Model):
    image = models.ImageField(upload_to="landing/hero/")
    alt_text = models.CharField(max_length=150)
    headline = models.CharField(max_length=150)
    subtitle = models.CharField(max_length=300, blank=True)
    button_text = models.CharField(max_length=40, blank=True)
    button_link = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.headline


class Announcement(models.Model):
    title = models.CharField(max_length=150)
    body = models.TextField()
    publish_date = models.DateField()
    expiry_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-publish_date", "-id"]

    def __str__(self):
        return self.title


MAX_ANNOUNCEMENT_IMAGES = 10


class AnnouncementImage(models.Model):
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="landing/announcements/")
    alt_text = models.CharField(max_length=150, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.alt_text or self.image.name


class HowItWorksStep(models.Model):
    title = models.CharField(max_length=80)
    description = models.CharField(max_length=255)
    icon = models.CharField(max_length=20, choices=LandingIcon.choices, default=LandingIcon.CHECK)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


class LandingFeature(models.Model):
    title = models.CharField(max_length=80)
    description = models.CharField(max_length=255)
    icon = models.CharField(max_length=20, choices=LandingIcon.choices, default=LandingIcon.SPARKLES)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


class GalleryImage(models.Model):
    image = models.ImageField(upload_to="landing/gallery/")
    alt_text = models.CharField(max_length=150)
    caption = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "-id"]

    def __str__(self):
        return self.caption or self.alt_text


class PartnerCollege(models.Model):
    name = models.CharField(max_length=150)
    logo = models.ImageField(upload_to="landing/colleges/", blank=True)
    alt_text = models.CharField(max_length=150, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.name


class FaqItem(models.Model):
    question = models.CharField(max_length=200)
    answer = models.TextField()
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.question
