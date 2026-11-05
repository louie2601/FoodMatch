import re

from django import forms
from django.forms import BaseFormSet, formset_factory
from django.contrib.auth import password_validation
from django.contrib.auth.models import User

from .models import (
    FoodCategory,
    GroupMember,
    LoginAs,
    MAX_GROUP_MEMBERS,
    PendingUserInvite,
    Program,
    active_college_names,
    active_program_names,
    ResearchSubmission,
)
from .text_rules import list_rule_error, normalize_text_input, rule_error
from .utils import DOCUMENT_UPLOAD_EXTENSIONS

DOCUMENT_UPLOAD_ACCEPT = ",".join(DOCUMENT_UPLOAD_EXTENSIONS)
DOCUMENT_UPLOAD_HELP_TEXT = "Complete food research only (with Results, Conclusions, Recommendations, and References). PDF, DOCX, TXT, JPG, or PNG (scanned/photographed pages are read via OCR)."

# Similarity Check skips OCR entirely to stay fast even with hundreds of
# repository documents (see extract_text_from_uploaded_file(use_ocr=False) /
# extract_text_from_stored_document in utils.py), and only accepts PDF — kept
# deliberately to one format, so DOCX/TXT/JPG/PNG aren't offered here either.
SIMILARITY_CHECK_UPLOAD_EXTENSIONS = (".pdf",)
SIMILARITY_CHECK_UPLOAD_ACCEPT = ",".join(SIMILARITY_CHECK_UPLOAD_EXTENSIONS)
SIMILARITY_CHECK_UPLOAD_HELP_TEXT = "Food research only. PDF only."


def _validate_document_extension(uploaded_file):
    file_name = uploaded_file.name.lower()
    if not file_name.endswith(DOCUMENT_UPLOAD_EXTENSIONS):
        raise forms.ValidationError("Only PDF, DOCX, TXT, JPG, or PNG files are allowed.")
    return uploaded_file


def _validate_similarity_check_extension(uploaded_file):
    file_name = uploaded_file.name.lower()
    if not file_name.endswith(SIMILARITY_CHECK_UPLOAD_EXTENSIONS):
        raise forms.ValidationError("Only PDF files are allowed for Similarity Check.")
    return uploaded_file


INPUT_CLASSES = (
    "w-full rounded-2xl border border-slate-200 bg-white/90 px-4 py-3 text-lg "
    "text-slate-900 shadow-sm outline-none transition duration-200 "
    "placeholder:text-slate-400 hover:border-slate-300 focus:border-emerald-600 "
    "focus:bg-white focus:ring-4 focus:ring-emerald-100"
)

SELECT_CLASSES = INPUT_CLASSES + " appearance-none"

REGISTER_INPUT_CLASSES = (
    "w-full rounded-xl border border-slate-200 bg-white/90 px-3.5 py-2.5 text-base "
    "text-slate-900 shadow-sm outline-none transition duration-200 "
    "placeholder:text-slate-400 hover:border-slate-300 focus:border-emerald-600 "
    "focus:bg-white focus:ring-4 focus:ring-emerald-100"
)

REGISTER_SELECT_CLASSES = REGISTER_INPUT_CLASSES + " appearance-none"

NAME_LETTERS_PATTERN = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ\s]+$")
DOUBLE_SPACE_PATTERN = re.compile(r"\s{2,}")
REPEATED_CHAR_PATTERN = re.compile(r"(.)\1{2,}", re.IGNORECASE)
DIGIT_PATTERN = re.compile(r"\d")
SPECIAL_CHAR_PATTERN = re.compile(r"[^A-Za-zÀ-ÖØ-öø-ÿ\s\d]")


def clean_name_field(value, label):
    """Standard name validation: auto-capitalizes each word, rejects double
    spaces, 3+ repeated characters in a row, numbers, and special characters.
    """
    value = value.strip()
    if not value:
        return value

    if DOUBLE_SPACE_PATTERN.search(value):
        raise forms.ValidationError(f"{label} cannot contain double spaces.")

    if REPEATED_CHAR_PATTERN.search(value):
        raise forms.ValidationError(
            f"{label} cannot contain the same letter repeated 3 or more times in a row."
        )

    has_digit = bool(DIGIT_PATTERN.search(value))
    has_special = bool(SPECIAL_CHAR_PATTERN.search(value))

    if has_digit and has_special:
        raise forms.ValidationError(f"{label} cannot contain numbers or special characters.")
    if has_digit:
        raise forms.ValidationError(f"{label} cannot contain numbers.")
    if has_special:
        raise forms.ValidationError(f"{label} cannot contain special characters.")

    return " ".join(word[:1].upper() + word[1:].lower() for word in value.split(" "))


USERNAME_PATTERN = re.compile(r"^[A-Z][a-z]+\.[A-Z][a-z]+$")

PUBLISHED_MONTH_CHOICES = [("", "— Select month —")] + [
    (m, m)
    for m in [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
]

# Colleges and programs come only from Settings > Programs & Colleges (Super
# Admin); nothing is listed in the code. They're read each time a form opens,
# so changes there show at once.
def program_choices():
    return [("", "Select Program"), *[(name, name) for name in active_program_names()]]


def college_choices():
    return [("", "Select College"), *[(name, name) for name in active_college_names()]]


def program_college_map():
    """{college name: [program names]} for programs on offer. The "" key holds
    programs with no college, which every college may pick."""
    mapping = {"": []}
    for name, college in Program.objects.filter(is_active=True).values_list("name", "college__name"):
        mapping.setdefault(college or "", []).append(name)
    return mapping


def _refresh_program_college_choices(form):
    form.fields["program"].choices = program_choices()
    form.fields["college"].choices = college_choices()
    # Read by the template so the Program list follows the chosen College.
    form.program_college_map = program_college_map()


def _check_program_matches_college(form, cleaned_data):
    program, college = _cleaned_text(cleaned_data, "program"), _cleaned_text(cleaned_data, "college")
    if not program or not college or "program" in form.errors:
        return
    offered = form.program_college_map
    if program not in offered.get(college, []) and program not in offered.get("", []):
        form.add_error("program", "This program is not offered by the selected college.")


def _cleaned_text(cleaned_data, key):
    return (cleaned_data.get(key) or "").strip()


class LoginForm(forms.Form):
    username = forms.CharField(
        label="Username",
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASSES,
                "placeholder": "Enter your Username",
                "autocomplete": "username",
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "class": INPUT_CLASSES + " pr-12",
                "placeholder": "Enter your Password",
                "autocomplete": "current-password",
                "data-password-input": "true",
            }
        ),
    )
    remember_me = forms.BooleanField(
        required=False,
        label="remember me",
        widget=forms.CheckboxInput(
            attrs={
                "class": "h-4 w-4 rounded border-slate-400 text-green-700 focus:ring-green-600"
            }
        ),
    )


class AdminUserCreationForm(forms.Form):
    def __init__(self, *args, is_super_admin=False, **kwargs):
        super().__init__(*args, **kwargs)
        if is_super_admin:
            self.fields["login_as"].choices = [
                ("", "Select Role"),
                ("Student", "Student"),
                ("Admin", "Admin"),
                ("Super Admin", "Super Admin"),
            ]
        else:
            self.fields["login_as"].choices = [
                ("Student", "Student"),
            ]

    username = forms.CharField(
        label="Username",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES,
                "placeholder": "e.g. Juan.Delacruz",
                "autocomplete": "username",
            }
        ),
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES,
                "placeholder": "Enter email address",
                "autocomplete": "email",
            }
        ),
    )
    login_as = forms.ChoiceField(
        label="Role",
        choices=[
            ("", "Select Role"),
            ("Student", "Student"),
            ("Admin", "Admin"),
        ],
        widget=forms.Select(
            attrs={
                "class": REGISTER_SELECT_CLASSES,
                "data-role-selector": "true",
            }
        ),
    )
    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not USERNAME_PATTERN.match(username):
            raise forms.ValidationError(
                "Username must be in the format Word.Word (e.g. Juan.Delacruz)."
            )
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken.")
        if PendingUserInvite.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("There is already a pending invite with this username.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        if PendingUserInvite.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("There is already a pending invite with this email.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        login_as = cleaned_data.get("login_as")

        if not login_as and "login_as" not in self.errors:
            self.add_error("login_as", "Role is required.")

        if login_as == "Super Admin" and "login_as" not in self.errors:
            choices = [c[0] for c in self.fields["login_as"].choices]
            if "Super Admin" not in choices:
                self.add_error("login_as", "Only Super Admins can create Super Admin accounts.")

        return cleaned_data


class MemberForm(forms.Form):
    """One person in a student account (a research group)."""

    first_name = forms.CharField(
        label="First Name",
        min_length=2,
        max_length=100,
        widget=forms.TextInput(
            attrs={"class": REGISTER_INPUT_CLASSES, "placeholder": "First name", "autocomplete": "off"}
        ),
    )
    middle_name = forms.CharField(
        label="Middle Name",
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={"class": REGISTER_INPUT_CLASSES, "placeholder": "Middle name (optional)", "autocomplete": "off"}
        ),
    )
    last_name = forms.CharField(
        label="Last Name",
        min_length=2,
        max_length=100,
        widget=forms.TextInput(
            attrs={"class": REGISTER_INPUT_CLASSES, "placeholder": "Last name", "autocomplete": "off"}
        ),
    )

    def clean_first_name(self):
        return clean_name_field(self.cleaned_data.get("first_name", ""), "First name")

    def clean_middle_name(self):
        return clean_name_field(self.cleaned_data.get("middle_name", ""), "Middle name")

    def clean_last_name(self):
        return clean_name_field(self.cleaned_data.get("last_name", ""), "Last name")


def _name_key(value):
    return " ".join((value or "").replace(".", " ").split()).lower()


def same_person(a, b):
    """Whether two (first, middle, last) names are the same person: the same
    first and last name, and middle names that agree when both are given
    (an initial matches the full middle name: "D" = "Dela")."""
    if _name_key(a[0]) != _name_key(b[0]) or _name_key(a[2]) != _name_key(b[2]):
        return False
    middle_a, middle_b = _name_key(a[1]), _name_key(b[1])
    if not middle_a or not middle_b or middle_a == middle_b:
        return True
    short, full = sorted((middle_a, middle_b), key=len)
    return len(short) == 1 and full.startswith(short)


def _full_name(person):
    return " ".join(part for part in (person[0], person[1], person[2]) if part)


class BaseMemberFormSet(BaseFormSet):
    default_error_messages = {
        **BaseFormSet.default_error_messages,
        "too_few_forms": "Add at least %(num)d member.",
        "too_many_forms": "A group can have at most %(num)d members.",
    }
    # The account being edited, if it already exists.
    owner_id = None

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        people = [(form.cleaned_data["first_name"], form.cleaned_data.get("middle_name", ""), form.cleaned_data["last_name"])
                  for form in self.forms]
        for index, person in enumerate(people):
            if any(same_person(person, earlier) for earlier in people[:index]):
                raise forms.ValidationError("The same member is listed more than once.")

        # A student can belong to only one group (one student account). If a person
        # is listed in two groups (from before this rule), the group that listed
        # them first keeps them; any other group must remove them before saving.
        others = GroupMember.objects.select_related("user__registration_profile")
        own = []
        if self.owner_id:
            others = others.exclude(user_id=self.owner_id)
            own = list(GroupMember.objects.filter(user_id=self.owner_id))
        taken = []
        for person in people:
            elsewhere = [
                member
                for member in others.filter(last_name__iexact=person[2].strip(), first_name__iexact=person[0].strip()).order_by("pk")
                if same_person(person, (member.first_name, member.middle_name, member.last_name))
            ]
            if not elsewhere:
                continue
            listed_here = [m.pk for m in own if same_person(person, (m.first_name, m.middle_name, m.last_name))]
            if listed_here and min(listed_here) < elsewhere[0].pk:
                continue
            profile = getattr(elsewhere[0].user, "registration_profile", None)
            group = (getattr(profile, "group_name", "") or "").strip() or elsewhere[0].user.username
            taken.append(f"{_full_name(person)} (already in {group})")
        if taken:
            raise forms.ValidationError(
                "These people are already members of another group, and a student can belong to only one group: "
                + "; ".join(taken) + "."
            )


MemberFormSet = formset_factory(
    MemberForm,
    formset=BaseMemberFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
    max_num=MAX_GROUP_MEMBERS,
    validate_max=True,
)


def build_member_formset(data=None, user=None):
    """Bound formset from POST data, or one pre-filled with the account's current
    members. `user` is the account being edited, if it already exists."""
    if data is not None:
        formset = MemberFormSet(data, prefix="members")
        formset.owner_id = user.pk if user is not None and user.pk else None
        return formset
    initial = []
    if user is not None and user.pk:
        initial = [
            {"first_name": m.first_name, "middle_name": m.middle_name, "last_name": m.last_name}
            for m in user.group_members.all()
        ]
        if not initial and (user.first_name or user.last_name):
            profile = getattr(user, "registration_profile", None)
            initial = [{"first_name": user.first_name, "middle_name": getattr(profile, "middle_name", ""), "last_name": user.last_name}]
    return MemberFormSet(initial=initial or None, prefix="members")


class ProfileCompletionForm(forms.Form):
    group_name = forms.CharField(
        label="Group Name",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={"class": REGISTER_INPUT_CLASSES, "placeholder": "e.g. Team FoodTech (optional)", "autocomplete": "off"}
        ),
    )
    first_name = forms.CharField(
        label="First Name",
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES,
                "placeholder": "Enter first name",
                "autocomplete": "given-name",
            }
        ),
    )
    middle_name = forms.CharField(
        label="Middle Name",
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES,
                "placeholder": "Enter middle name",
                "autocomplete": "additional-name",
            }
        ),
    )
    last_name = forms.CharField(
        label="Last Name",
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES,
                "placeholder": "Enter last name",
                "autocomplete": "family-name",
            }
        ),
    )
    program = forms.ChoiceField(
        label="Program",
        required=False,
        choices=[],
        widget=forms.Select(
            attrs={
                "class": REGISTER_SELECT_CLASSES,
                "data-student-field": "true",
            }
        ),
    )
    college = forms.ChoiceField(
        label="College",
        required=False,
        choices=[],
        widget=forms.Select(
            attrs={
                "class": REGISTER_SELECT_CLASSES,
                "data-student-field": "true",
            }
        ),
    )
    new_password = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES + " pr-12",
                "placeholder": "Enter new permanent password",
                "autocomplete": "new-password",
                "data-password-input": "true",
            }
        ),
    )
    confirm_new_password = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES + " pr-12",
                "placeholder": "Confirm new permanent password",
                "autocomplete": "new-password",
                "data-password-input": "true",
            }
        ),
    )

    def __init__(self, *args, require_student_fields=False, **kwargs):
        super().__init__(*args, **kwargs)
        _refresh_program_college_choices(self)
        self._require_student_fields = require_student_fields
        if require_student_fields:
            # Student accounts are research groups: names come from the members formset.
            for name in ("first_name", "middle_name", "last_name"):
                del self.fields[name]
        else:
            del self.fields["group_name"]

    def clean(self):
        cleaned_data = super().clean()
        program = cleaned_data.get("program")
        college = cleaned_data.get("college")
        new_pw = cleaned_data.get("new_password")
        confirm_pw = cleaned_data.get("confirm_new_password")

        if self._require_student_fields:
            if not program and "program" not in self.errors:
                self.add_error("program", "Program is required for student accounts.")
            if not college and "college" not in self.errors:
                self.add_error("college", "College is required for student accounts.")
        else:
            cleaned_data["program"] = ""
            cleaned_data["college"] = ""

        if new_pw and len(new_pw) < 8:
            self.add_error("new_password", "Password must be at least 8 characters long.")

        if new_pw and confirm_pw and new_pw != confirm_pw:
            self.add_error("confirm_new_password", "Passwords do not match.")

        _check_program_matches_college(self, cleaned_data)
        return cleaned_data


class ProfileUpdateForm(forms.Form):
    group_name = forms.CharField(
        label="Group Name",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={"class": REGISTER_INPUT_CLASSES, "placeholder": "e.g. Team FoodTech (optional)", "autocomplete": "off"}
        ),
    )
    first_name = forms.CharField(
        label="First Name",
        min_length=2,
        max_length=100,
        widget=forms.TextInput(attrs={"class": REGISTER_INPUT_CLASSES, "autocomplete": "given-name"}),
    )
    middle_name = forms.CharField(
        label="Middle Name",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": REGISTER_INPUT_CLASSES, "autocomplete": "additional-name"}),
    )
    last_name = forms.CharField(
        label="Last Name",
        min_length=2,
        max_length=100,
        widget=forms.TextInput(attrs={"class": REGISTER_INPUT_CLASSES, "autocomplete": "family-name"}),
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"class": REGISTER_INPUT_CLASSES, "autocomplete": "email"}),
    )
    program = forms.ChoiceField(
        label="Program",
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": REGISTER_SELECT_CLASSES}),
    )
    college = forms.ChoiceField(
        label="College",
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": REGISTER_SELECT_CLASSES}),
    )
    current_password = forms.CharField(
        label="Current Password",
        required=False,
        widget=forms.PasswordInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES + " pr-12",
                "autocomplete": "current-password",
                "data-password-input": "true",
            }
        ),
    )

    def __init__(self, *args, user=None, require_student_fields=False, **kwargs):
        super().__init__(*args, **kwargs)
        _refresh_program_college_choices(self)
        self._user = user
        self._require_student_fields = require_student_fields
        if require_student_fields:
            for name in ("first_name", "middle_name", "last_name"):
                del self.fields[name]
        else:
            del self.fields["group_name"]

    def clean_first_name(self):
        return clean_name_field(self.cleaned_data.get("first_name", ""), "First name")

    def clean_middle_name(self):
        return clean_name_field(self.cleaned_data.get("middle_name", ""), "Middle name")

    def clean_last_name(self):
        return clean_name_field(self.cleaned_data.get("last_name", ""), "Last name")

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        others = User.objects.filter(email__iexact=email)
        if self._user is not None and self._user.pk:
            others = others.exclude(pk=self._user.pk)
        if others.exists():
            raise forms.ValidationError("An account with this email already exists.")
        if PendingUserInvite.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("There is already a pending invite with this email.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        if self._require_student_fields:
            if not cleaned_data.get("program") and "program" not in self.errors:
                self.add_error("program", "Program is required for student accounts.")
            if not cleaned_data.get("college") and "college" not in self.errors:
                self.add_error("college", "College is required for student accounts.")
        else:
            cleaned_data["program"] = ""
            cleaned_data["college"] = ""

        email = cleaned_data.get("email")
        if (
            email
            and self._user is not None
            and email.lower() != (self._user.email or "").lower()
            and not cleaned_data.get("current_password")
        ):
            self.add_error("current_password", "Enter your current password to change your email.")
        _check_program_matches_college(self, cleaned_data)
        return cleaned_data


class AdminUserEditForm(ProfileUpdateForm):
    """An Admin/Super Admin editing someone else's account. Same rules as the
    profile page, plus the username; no current-password step (that guards a
    person's own email, not staff changes)."""

    username = forms.CharField(
        label="Username",
        max_length=150,
        help_text="Format: Word.Word, e.g. Juan.Delacruz",
        widget=forms.TextInput(attrs={"class": REGISTER_INPUT_CLASSES, "autocomplete": "off"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields["current_password"]
        self.order_fields(["username", "email", "group_name", "first_name", "middle_name", "last_name", "program", "college"])

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not USERNAME_PATTERN.match(username):
            raise forms.ValidationError("Username must be in the format Word.Word (e.g. Juan.Delacruz).")
        others = User.objects.filter(username__iexact=username)
        if self._user is not None and self._user.pk:
            others = others.exclude(pk=self._user.pk)
        if others.exists():
            raise forms.ValidationError("This username is already taken.")
        if PendingUserInvite.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("There is already a pending invite with this username.")
        return username

    def clean(self):
        cleaned_data = super(ProfileUpdateForm, self).clean()
        if self._require_student_fields:
            if not cleaned_data.get("program") and "program" not in self.errors:
                self.add_error("program", "Program is required for student accounts.")
            if not cleaned_data.get("college") and "college" not in self.errors:
                self.add_error("college", "College is required for student accounts.")
        else:
            cleaned_data["program"] = ""
            cleaned_data["college"] = ""
        return cleaned_data


class ChangePasswordVerifyForm(forms.Form):
    current_password = forms.CharField(
        label="Current Password",
        widget=forms.PasswordInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES + " pr-12",
                "placeholder": "Enter your current password",
                "autocomplete": "current-password",
                "data-password-input": "true",
            }
        ),
    )


class ForgotPasswordUsernameForm(forms.Form):
    username = forms.CharField(
        label="Username",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASSES,
                "placeholder": "Enter your Username",
                "autocomplete": "username",
                "autofocus": "autofocus",
            }
        ),
    )


class ForgotPasswordOTPForm(forms.Form):
    code = forms.CharField(
        label="Verification Code",
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASSES + " text-center text-2xl font-bold tracking-[0.5em]",
                "placeholder": "••••••",
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "maxlength": "6",
                "pattern": "[0-9]*",
                "autofocus": "autofocus",
            }
        ),
    )

    def clean_code(self):
        code = self.cleaned_data.get("code", "").strip().replace(" ", "")
        if not re.fullmatch(r"\d{6}", code):
            raise forms.ValidationError("Enter the 6-digit code from your email.")
        return code


class ForgotPasswordResetForm(forms.Form):
    new_password = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(
            attrs={
                "class": INPUT_CLASSES + " pr-12",
                "placeholder": "Enter your new password",
                "autocomplete": "new-password",
                "data-password-input": "true",
            }
        ),
    )
    confirm_new_password = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput(
            attrs={
                "class": INPUT_CLASSES + " pr-12",
                "placeholder": "Re-enter your new password",
                "autocomplete": "new-password",
                "data-password-input": "true",
            }
        ),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user

    def clean_new_password(self):
        new_password = self.cleaned_data.get("new_password", "")
        if new_password:
            password_validation.validate_password(new_password, user=self._user)
            if self._user.check_password(new_password):
                raise forms.ValidationError("Your new password must be different from your old one.")
        return new_password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm = cleaned_data.get("confirm_new_password")
        if new_password and confirm and new_password != confirm:
            self.add_error("confirm_new_password", "Passwords do not match.")
        return cleaned_data


class ChangePasswordNewForm(ForgotPasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = REGISTER_INPUT_CLASSES + " pr-12"


class ResearchSimilarityForm(forms.Form):
    proposal_file = forms.FileField(
        label="Research File",
        widget=forms.ClearableFileInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES,
                "accept": SIMILARITY_CHECK_UPLOAD_ACCEPT,
            }
        ),
        help_text=f"Upload a research document for similarity checking. {SIMILARITY_CHECK_UPLOAD_HELP_TEXT}",
    )

    def clean_proposal_file(self):
        return _validate_similarity_check_extension(self.cleaned_data["proposal_file"])


def _rule_attrs(rule, label):
    """Lets core/js/field-rules.js block disallowed characters while typing."""
    return {"data-field-rule": rule, "data-field-label": label}


class ResearchTextRulesMixin:
    """No numbers or special characters in the typed research fields; see
    core/text_rules.py for what each field allows."""

    def _checked(self, field, label, rule):
        value = normalize_text_input(self.cleaned_data.get(field) or "").strip()
        error = rule_error(label, value, rule)
        if error:
            raise forms.ValidationError(error)
        return value

    def clean_title(self):
        return self._checked("title", "Research Title", "title")

    def clean_adviser(self):
        return self._checked("adviser", "Adviser", "name")

    def clean_abstract(self):
        return self._checked("abstract", "Abstract", "abstract")

    def clean_keywords(self):
        raw = normalize_text_input(self.cleaned_data.get("keywords") or "")
        keywords = [part.strip() for part in raw.split(",") if part.strip()]
        error = list_rule_error("Keywords", keywords, "keyword")
        if error:
            raise forms.ValidationError(error)
        return ", ".join(keywords)


class ResearchSubmissionForm(ResearchTextRulesMixin, forms.ModelForm):
    category = forms.ModelChoiceField(
        label="Food Category",
        queryset=FoodCategory.objects.filter(parent__isnull=True),
        empty_label="— Select category —",
        widget=forms.Select(
            attrs={
                "class": REGISTER_SELECT_CLASSES,
                "id": "id_category",
            }
        ),
    )
    authors_json = forms.CharField(
        label="Authors",
        required=False,
        max_length=2000,
        widget=forms.HiddenInput(
            attrs={
                "id": "id_authors_json",
                "data-authors-json": "1",
            }
        ),
    )
    adviser = forms.CharField(
        label="Adviser",
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES,
                "placeholder": "e.g. Dr. Juanita P. Reyes, Ms. Ana S. Villanueva",
                "autocomplete": "off",
                "id": "id_adviser",
                **_rule_attrs("name", "Adviser"),
            }
        ),
        help_text="Name of the research adviser.",
    )
    abstract = forms.CharField(
        label="Abstract",
        widget=forms.Textarea(
            attrs={
                "class": REGISTER_INPUT_CLASSES,
                "placeholder": "Enter abstract or short summary",
                "rows": 5,
                **_rule_attrs("abstract", "Abstract"),
            }
        ),
    )
    published_month = forms.ChoiceField(
        label="Published Month",
        required=False,
        choices=PUBLISHED_MONTH_CHOICES,
        widget=forms.Select(
            attrs={
                "class": REGISTER_SELECT_CLASSES,
                "id": "id_published_month",
            }
        ),
        help_text="Month published, used for school-year grouping.",
    )
    published_year = forms.IntegerField(
        label="Published Year",
        required=False,
        min_value=1990,
        max_value=2199,
        widget=forms.NumberInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES,
                "placeholder": "e.g. 2026",
                "id": "id_published_year",
                "min": 1990,
                "max": 2199,
            }
        ),
        help_text="Year published (YYYY) to identify school year.",
    )

    def __init__(self, *args, include_document_field=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not include_document_field:
            del self.fields["document"]

    class Meta:
        model = ResearchSubmission
        fields = ["title", "adviser", "abstract", "keywords", "published_month", "published_year", "document"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": REGISTER_INPUT_CLASSES,
                    "placeholder": "Enter research title",
                    **_rule_attrs("title", "Research Title"),
                }
            ),
            "keywords": forms.HiddenInput(
                attrs={
                    "id": "id_keywords",
                    "data-keywords-input": "1",
                }
            ),
            "document": forms.ClearableFileInput(
                attrs={
                    "class": REGISTER_INPUT_CLASSES,
                    "accept": DOCUMENT_UPLOAD_ACCEPT,
                }
            ),
        }
        help_texts = {
            "keywords": "Auto-generated from the title — add or remove as needed.",
            "document": DOCUMENT_UPLOAD_HELP_TEXT,
        }

    def clean_document(self):
        document = self.cleaned_data.get("document")
        if not document:
            return document
        return _validate_document_extension(document)


REPOSITORY_INPUT_CLASSES = (
    "w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-base "
    "text-slate-900 shadow-sm outline-none transition duration-200 "
    "placeholder:text-slate-400 hover:border-slate-300 focus:border-emerald-500 "
    "focus:bg-white focus:ring-4 focus:ring-emerald-100"
)


class RepositoryResearchAddForm(ResearchTextRulesMixin, forms.Form):
    title = forms.CharField(
        label="Research Title",
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": REPOSITORY_INPUT_CLASSES,
                "placeholder": "e.g. Feasibility of Banana Peel Flour as a Nutritious Supplement",
                "autocomplete": "off",
                **_rule_attrs("title", "Research Title"),
            }
        ),
    )
    category = forms.ModelChoiceField(
        label="Food Category",
        queryset=FoodCategory.objects.filter(parent__isnull=True),
        empty_label="— Select category —",
        widget=forms.Select(
            attrs={
                "class": REPOSITORY_INPUT_CLASSES,
                "id": "id_category",
            }
        ),
    )
    authors_json = forms.CharField(
        label="Authors",
        required=False,
        max_length=2000,
        widget=forms.HiddenInput(
            attrs={
                "id": "id_authors_json",
                "data-authors-json": "1",
            }
        ),
    )
    adviser = forms.CharField(
        label="Adviser",
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": REPOSITORY_INPUT_CLASSES,
                "placeholder": "e.g. Dr. Juanita P. Reyes, Ms. Ana S. Villanueva",
                "autocomplete": "off",
                "id": "id_adviser",
                **_rule_attrs("name", "Adviser"),
            }
        ),
        help_text="Name of the research adviser.",
    )
    abstract = forms.CharField(
        label="Abstract",
        widget=forms.Textarea(
            attrs={
                "class": REPOSITORY_INPUT_CLASSES,
                "placeholder": "Provide a concise summary of the research objectives, methodology, findings, and conclusions.",
                "rows": 7,
                **_rule_attrs("abstract", "Abstract"),
            }
        ),
    )
    keywords = forms.CharField(
        label="Keywords",
        required=False,
        max_length=255,
        widget=forms.HiddenInput(
            attrs={
                "id": "id_keywords",
                "data-keywords-input": "1",
            }
        ),
        help_text="Auto-generated from the title — add or remove as needed.",
    )
    published_month = forms.ChoiceField(
        label="Published Month",
        required=False,
        choices=PUBLISHED_MONTH_CHOICES,
        widget=forms.Select(
            attrs={
                "class": REPOSITORY_INPUT_CLASSES,
                "id": "id_published_month",
            }
        ),
        help_text="Month published, used for school-year grouping.",
    )
    published_year = forms.IntegerField(
        label="Published Year",
        required=False,
        min_value=1990,
        max_value=2199,
        widget=forms.NumberInput(
            attrs={
                "class": REPOSITORY_INPUT_CLASSES,
                "placeholder": "e.g. 2026",
                "id": "id_published_year",
                "min": 1990,
                "max": 2199,
            }
        ),
        help_text="Year published (YYYY) to identify school year.",
    )
    document = forms.FileField(
        label="Research Document",
        required=True,
        widget=forms.ClearableFileInput(
            attrs={
                "class": REPOSITORY_INPUT_CLASSES,
                "accept": DOCUMENT_UPLOAD_ACCEPT,
            }
        ),
        help_text=(
            "Upload the full research document so it can be matched on its full content, not just its title "
            f"and abstract. {DOCUMENT_UPLOAD_HELP_TEXT}"
        ),
    )

    def clean_document(self):
        document = self.cleaned_data.get("document")
        if not document:
            return document
        return _validate_document_extension(document)


class RegistrationForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _refresh_program_college_choices(self)

    group_name = forms.CharField(
        label="Group Name",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={"class": REGISTER_INPUT_CLASSES, "placeholder": "e.g. Team FoodTech (optional)", "autocomplete": "off"}
        ),
    )
    program = forms.ChoiceField(
        label="Program",
        required=True,
        choices=[],
        widget=forms.Select(
            attrs={
                "class": REGISTER_SELECT_CLASSES,
            }
        ),
    )
    college = forms.ChoiceField(
        label="College",
        required=True,
        choices=[],
        widget=forms.Select(
            attrs={
                "class": REGISTER_SELECT_CLASSES,
            }
        ),
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES,
                "placeholder": "Enter your Email",
                "autocomplete": "email",
            }
        ),
    )
    username = forms.CharField(
        label="Username",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES,
                "placeholder": "e.g. Juan.Delacruz",
                "autocomplete": "username",
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES + " pr-12",
                "placeholder": "Enter your Password",
                "autocomplete": "new-password",
                "data-password-input": "true",
            }
        ),
    )
    confirm_password = forms.CharField(
        label="Re-Enter Password",
        widget=forms.PasswordInput(
            attrs={
                "class": REGISTER_INPUT_CLASSES + " pr-12",
                "placeholder": "Re-Enter your Password",
                "autocomplete": "new-password",
                "data-password-input": "true",
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not USERNAME_PATTERN.match(username):
            raise forms.ValidationError(
                "Username must be in the format Word.Word (e.g. Juan.Delacruz)."
            )
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_password(self):
        password = self.cleaned_data.get("password", "")
        if password:
            temp_user = User(
                username=self.cleaned_data.get("username", ""),
                email=self.cleaned_data.get("email", ""),
                first_name=self.data.get("members-0-first_name", ""),
                last_name=self.data.get("members-0-last_name", ""),
            )
            password_validation.validate_password(password, user=temp_user)
        return password

    def clean(self):
        cleaned_data = super().clean()
        program = cleaned_data.get("program")
        college = cleaned_data.get("college")
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        cleaned_data["login_as"] = LoginAs.STUDENT

        if not program and "program" not in self.errors:
            self.add_error("program", "Program is required for student registration.")
        if not college and "college" not in self.errors:
            self.add_error("college", "College is required for student registration.")

        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")

        _check_program_matches_college(self, cleaned_data)
        return cleaned_data


class ContactForm(forms.Form):
    name = forms.CharField(max_length=100, label="Your Name")
    email = forms.EmailField(label="Your Email")
    message = forms.CharField(widget=forms.Textarea, label="Your Message")
