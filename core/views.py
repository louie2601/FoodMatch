import csv
import hashlib
import json
import logging
import math
import mimetypes
import os
import re
import secrets
import threading
import time
from datetime import date, datetime
from urllib.parse import urlencode
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.core.files.base import File
from django.core.cache import cache
from django.core.exceptions import NON_FIELD_ERRORS
from django.core.files.storage import default_storage
from django.core.mail import EmailMultiAlternatives
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import Avg, Case, Count, IntegerField, Q, Value, When
from django.db.models.functions import TruncMonth
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import escape
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie

from .auth_backends import is_emergency_user, verify_user_password
from .duplicates import duplicate_file_error, duplicate_title_error, file_sha256
from . import semantic
from .food_relevance import assess_food_relevance, check_uploaded_research, not_food_research_error
from .text_rules import list_rule_error, normalize_text_input, rule_error, tidy_to_rule
from .completeness import (
    UNVERIFIED_RESEARCH_ERROR,
    assess_document,
    incomplete_research_error,
    read_text_layer,
)
from .notifications import notify, staff_with_module, super_admins
from .landing_forms import (
    AnnouncementForm,
    CategoryImageForm,
    FaqItemForm,
    GalleryImageForm,
    HeroSlideForm,
    HowItWorksStepForm,
    LandingFeatureForm,
    LandingSettingsForm,
    PartnerCollegeForm,
)
from .forms import (
    AdminUserCreationForm,
    AdminUserEditForm,
    ChangePasswordNewForm,
    ChangePasswordVerifyForm,
    ForgotPasswordOTPForm,
    ForgotPasswordResetForm,
    ForgotPasswordUsernameForm,
    build_member_formset,
    same_person,
    LoginForm,
    ProfileCompletionForm,
    ProfileUpdateForm,
    RegistrationForm,
    RepositoryResearchAddForm,
    ResearchSimilarityForm,
    ResearchSubmissionForm,
)
from .models import (
    AccountDeactivation,
    AdminModule,
    AdminModuleAccess,
    Announcement,
    FaqItem,
    GalleryImage,
    HeroSlide,
    HowItWorksStep,
    LandingFeature,
    LandingSettings,
    PartnerCollege,
    Notification,
    NotificationCategory,
    College,
    DeletionRequestStatus,
    FoodCategory,
    FoodItem,
    GroupMember,
    LoginAs,
    MAX_GROUP_MEMBERS,
    account_display_name,
    group_member_names,
    PasswordResetOTP,
    PendingUserInvite,
    PendingUserInviteRole,
    Program,
    RegistrationProfile,
    RegistrationStatus,
    ResearchPaper,
    ResearchSubmission,
    ResearchSubmissionStatus,
    SimilarityCheckRecord,
    SystemLog,
    SystemLogType,
    UserDeletionRequest,
)
from .utils import (
    DOCUMENT_UPLOAD_EXTENSIONS,
    SIMILARITY_LEVELS,
    SIMILARITY_RANGES,
    SIMILARITY_WEIGHTS,
    similarity_level_for_percent,
    build_repository_documents_from_submissions,
    deduplicate_repository_documents,
    explain_similarity_match,
    extract_text_from_uploaded_file,
    extract_food_research_sections,
    extract_research_metadata_from_text,
    normalize_text,
    rank_similar_documents_weighted,
)

SYSTEM_LOGS_PAGE_SIZE = 20
# Failed sign-ins are recorded as Login logs starting with this text, so the
# dashboard can count them and System Logs can search for them.
FAILED_SIGNIN_LOG_PREFIX = "Failed sign-in attempt"
SIMILARITY_RECORDS_PAGE_SIZE = 10
REPOSITORY_SEARCH_PAGE_SIZE = 10
REPOSITORY_ADMIN_PAGE_SIZE = 20
MANAGE_SUBMISSIONS_PAGE_SIZE = 20
# Manage Submissions tabs -> the status each one shows (None = every status).
SUBMISSION_STATUS_TABS = {
    "all": None,
    "pending": ResearchSubmissionStatus.PENDING,
    "approved": ResearchSubmissionStatus.APPROVED,
    "rejected": ResearchSubmissionStatus.REJECTED,
}
REPORTS_MONTHS_SHOWN = 12
LANDING_RECENT_STUDIES = 6
LANDING_BROWSE_CATEGORIES = 8
LANDING_ANNOUNCEMENTS = 3
REPORTS_TOP_CATEGORIES = 10
SIMILARITY_UPLOAD_ALLOWED_SESSION_KEY = "similarity_upload_allowed"
SIMILARITY_CHECKED_FILE_NAME_SESSION_KEY = "similarity_checked_file_name"
SIMILARITY_CHECKED_FILE_STORAGE_KEY = "similarity_checked_file_storage_path"
PROFILE_COMPLETE_SESSION_KEY = "profile_complete_override"


def _clear_pending_similarity_file(request):
    """Delete any temp file saved from a previous similarity check and clear its session key."""
    stored_path = request.session.get(SIMILARITY_CHECKED_FILE_STORAGE_KEY, "")
    if stored_path:
        try:
            if default_storage.exists(stored_path):
                default_storage.delete(stored_path)
        except Exception:
            pass
    request.session[SIMILARITY_CHECKED_FILE_STORAGE_KEY] = ""


def _parse_authors_list(authors_json_raw, request):
    """Parse the authors_json hidden field (a JSON array of names) into a clean list of strings."""
    author_list = []
    if authors_json_raw:
        try:
            parsed = json.loads(authors_json_raw)
            if isinstance(parsed, list):
                author_list = [str(a).strip() for a in parsed if isinstance(a, str) and str(a).strip()]
        except (json.JSONDecodeError, TypeError, ValueError):
            author_list = []
    if not author_list and request.POST.get("authors"):
        text = request.POST["authors"]
        author_list = [s.strip() for s in text.split(",") if s.strip()]
    return author_list


def _username_key(username):
    """Fixed-length, cache-safe stand-in for whatever was typed as a username."""
    return hashlib.sha256((username or "").strip().lower().encode("utf-8")).hexdigest()


def _get_client_ip(request):
    """The visitor's IP. X-Forwarded-For is only believed behind our own proxy
    (TRUST_X_FORWARDED_FOR), where nginx overwrites it with the real address."""
    if settings.TRUST_X_FORWARDED_FOR:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded.strip():
            return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


def _log_system_event(request, user, log_type, action):
    try:
        if is_emergency_user(user):
            # Virtual account, never a database row — log under user=None with
            # the identity embedded in the action text so break-glass usage
            # still leaves an audit trail instead of silently failing the FK.
            SystemLog.objects.create(
                user=None,
                log_type=log_type,
                action=f"[EMERGENCY SUPER ADMIN: {user.username}] {action}",
                ip_address=_get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
            )
        else:
            SystemLog.objects.create(
                user=user,
                log_type=log_type,
                action=action,
                ip_address=_get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
            )
    except Exception:
        pass


def _record_similarity_check(user, file_name, results, total_compared):
    """Persist one Similarity Check run so it shows up in the requesting
    role's history (see SimilarityCheckRecord). Best-effort, same as system
    logging -- never let a logging failure break the check itself."""
    if is_emergency_user(user):
        # Virtual account, no real DB row to attach the FK to.
        return
    try:
        top = results[0] if results else None
        SimilarityCheckRecord.objects.create(
            user=user,
            file_name=(file_name or "")[:255],
            top_score_percent=top.get("score_percent", 0.0) if top else 0.0,
            top_match_title=(top.get("title") or "")[:255] if top else "",
            similarity_level=(top.get("similarity_level") or "low") if top else "low",
            similarity_label=(top.get("similarity_label") or "Low Similarity") if top else "Low Similarity",
            total_compared=total_compared,
            results_snapshot=[
                {
                    "title": r.get("title", ""),
                    "score_percent": r.get("score_percent", 0),
                    "similarity_label": r.get("similarity_label", ""),
                    "metadata_only": r.get("metadata_only", False),
                }
                for r in results[:5]
            ],
        )
    except Exception:
        pass


def _effective_login_role_for_profile(user):
    if user.is_superuser:
        return "Super Admin"
    if user.is_staff:
        return "Admin"
    profile = getattr(user, "registration_profile", None)
    if profile:
        return profile.login_as
    return None


def _profile_is_complete(user):
    if not user.first_name.strip() or not user.last_name.strip():
        return False
    role = _effective_login_role_for_profile(user)
    if role == LoginAs.STUDENT:
        profile = getattr(user, "registration_profile", None)
        if not profile or not profile.program.strip() or not profile.college.strip():
            return False
        if not user.group_members.exists():
            return False
    return True


def _dashboard_name_for_user(user):
    if user.is_staff or user.is_superuser:
        return "admin_dashboard"

    profile = getattr(user, "registration_profile", None)
    if not profile:
        return None

    if profile.login_as == LoginAs.STUDENT:
        return "student_dashboard"
    return None


def _redirect_authenticated_user(user):
    if not _profile_is_complete(user):
        return redirect("complete_profile")
    dashboard_name = _dashboard_name_for_user(user)
    if dashboard_name:
        return redirect(dashboard_name)
    return None


def _admin_only_or_redirect(request):
    if not _profile_is_complete(request.user):
        return redirect("complete_profile")
    if request.user.is_staff or request.user.is_superuser:
        return None

    redirect_response = _redirect_authenticated_user(request.user)
    if redirect_response:
        return redirect_response
    return redirect("login")


ADMIN_MODULE_GROUPS = (
    ("User Management", (AdminModule.MANAGE_USERS,)),
    (
        "Research Management",
        (
            AdminModule.MANAGE_SUBMISSIONS,
            AdminModule.RESEARCH_REPOSITORY,
            AdminModule.ADD_RESEARCH,
            AdminModule.SIMILARITY_CHECK,
            AdminModule.SIMILARITY_RECORDS,
        ),
    ),
    ("System", (AdminModule.SYSTEM_LOGS, AdminModule.REPORTS)),
    ("Settings", (AdminModule.MANAGE_CATEGORIES, AdminModule.PROGRAMS_COURSES, AdminModule.LANDING_PAGE)),
)


def _admin_has_module(user, module):
    if user.is_superuser:
        return True
    if not user.is_staff:
        return False
    return AdminModuleAccess.objects.filter(user=user, module=module).exists()


def _render_access_denied(request, module_label, super_admin_only=False):
    context = {
        "page_title": "Access Denied",
        "is_super_admin": request.user.is_superuser,
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "admin_role": "Super Admin" if request.user.is_superuser else "Admin",
        "module_label": module_label,
        "super_admin_only": super_admin_only,
    }
    return render(request, "core/admin_access_denied.html", context, status=403)


def _admin_module_or_denied(request, *modules):
    """Admin-area guard: non-admins are redirected as before; Admins holding none
    of the given modules get the Access Denied page."""
    redirect_response = _admin_only_or_redirect(request)
    if redirect_response:
        return redirect_response
    if any(_admin_has_module(request.user, module) for module in modules):
        return None
    return _render_access_denied(request, AdminModule(modules[0]).label)


def _super_admin_module_or_denied(request, module_label):
    redirect_response = _admin_only_or_redirect(request)
    if redirect_response:
        return redirect_response
    if request.user.is_superuser:
        return None
    return _render_access_denied(request, module_label, super_admin_only=True)


def _student_only_or_redirect(request):
    if not _profile_is_complete(request.user):
        return redirect("complete_profile")
    if request.user.is_staff or request.user.is_superuser:
        return redirect("admin_dashboard")
    profile = getattr(request.user, "registration_profile", None)
    if profile and profile.login_as == LoginAs.STUDENT:
        return None

    redirect_response = _redirect_authenticated_user(request.user)
    if redirect_response:
        return redirect_response
    return redirect("login")


def home(request):
    site = LandingSettings.load()
    today = timezone.localdate()

    needs_repository = site.show_stats or site.show_recent_research or site.show_categories
    repository_rows = _all_repository_rows(request.user) if needs_repository else []

    stats = []
    if site.show_stats:
        stats = [
            {"label": "Studies in the repository", "value": len(repository_rows)},
            {
                "label": "Approved submissions",
                "value": ResearchSubmission.objects.filter(status=ResearchSubmissionStatus.APPROVED).count(),
            },
            {"label": "Similarity checks run", "value": SimilarityCheckRecord.objects.count()},
            {
                "label": "Research groups",
                "value": User.objects.filter(is_active=True, is_staff=False, registration_profile__isnull=False).count(),
            },
        ]

    # Public page: title, category, and year only -- no authors, abstracts, or files.
    recent_research = [
        {
            "title": row["title"],
            "category": row["category"].name if row["category"] else "",
            "year": row["published_year"] or "",
        }
        for row in sorted(repository_rows, key=lambda row: row["added_sort"], reverse=True)[:LANDING_RECENT_STUDIES]
    ]

    category_counts = {}
    for row in repository_rows:
        category = row["category"]
        if category is None:
            continue
        top = category.parent or category
        category_counts[top.pk] = category_counts.get(top.pk, 0) + 1
    browse_categories = []
    if category_counts:
        categories_by_pk = FoodCategory.objects.in_bulk(list(category_counts))
        ranked = sorted(category_counts.items(), key=lambda item: (-item[1], categories_by_pk[item[0]].name))
        browse_categories = [
            {"category": categories_by_pk[pk], "count": count} for pk, count in ranked[:LANDING_BROWSE_CATEGORIES]
        ]

    context = {
        "page_title": "FOOD MATCH",
        "site": site,
        "slides": list(HeroSlide.objects.filter(is_active=True)),
        "stats": stats,
        "announcements": list(
            Announcement.objects.prefetch_related("images")
            .filter(is_active=True, publish_date__lte=today)
            .filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today))[:LANDING_ANNOUNCEMENTS]
        ),
        "steps": list(HowItWorksStep.objects.all()),
        "features": list(LandingFeature.objects.all()),
        "recent_research": recent_research,
        "browse_categories": browse_categories,
        "gallery": list(GalleryImage.objects.filter(is_active=True)),
        "colleges": list(PartnerCollege.objects.all()),
        "faqs": list(FaqItem.objects.filter(is_active=True)),
    }
    return render(request, "core/home.html", context)


def dashboard_redirect_view(request):
    if not request.user.is_authenticated:
        return redirect("login")

    redirect_response = _redirect_authenticated_user(request.user)
    if redirect_response:
        return redirect_response

    return redirect("home")


@login_required(login_url="login")
def research_similarity_view(request):
    redirect_response = _student_only_or_redirect(request)
    if redirect_response:
        return redirect_response

    form = ResearchSimilarityForm(request.POST or None, request.FILES or None)
    semantic.warm_up_in_background()
    similarity_results = []
    comparison_submitted = False
    repository_error = ""
    uploaded_file_name = ""
    total_repository_documents = 0
    can_submit_for_review = False
    # "ready" (may upload), "unfinished" (low similarity but not a complete
    # paper yet) or "blocked" (moderate/high similarity).
    similarity_outcome = ""
    paper_status = ""
    paper_missing = []
    query_title_guess = ""
    query_abstract_guess = ""
    query_ingredients_guess = ""
    query_general_guess = ""
    similarity_weights_used = {}
    semantic_used = False

    if request.method == "POST" and form.is_valid():
        comparison_submitted = True
        proposal_file = form.cleaned_data["proposal_file"]
        uploaded_file_name = proposal_file.name
        _clear_pending_similarity_file(request)
        request.session[SIMILARITY_UPLOAD_ALLOWED_SESSION_KEY] = False
        request.session[SIMILARITY_CHECKED_FILE_NAME_SESSION_KEY] = ""

        try:
            query_text = extract_text_from_uploaded_file(proposal_file, use_ocr=False)
            (
                query_title_guess,
                query_abstract_guess,
                query_ingredients_guess,
                query_general_guess,
            ) = extract_food_research_sections(query_text)
            approved_submissions = ResearchSubmission.objects.select_related("student").filter(
                status=ResearchSubmissionStatus.APPROVED
            )
            submission_docs = build_repository_documents_from_submissions(approved_submissions)
            submission_docs = deduplicate_repository_documents(submission_docs)

            paper_metadata_docs = []
            for paper in ResearchPaper.objects.all():
                combined = normalize_text(
                    paper.title or "",
                    paper.abstract or "",
                    paper.keywords or "",
                )
                if not combined.strip():
                    continue
                published_str = ""
                try:
                    if paper.published_date:
                        published_str = paper.published_date.isoformat()
                except Exception:
                    published_str = ""
                created_str = ""
                try:
                    if paper.created_at:
                        created_str = timezone.localtime(paper.created_at).isoformat()
                except Exception:
                    created_str = ""
                paper_title_raw = (paper.title or "").strip() or "Untitled Repository Study"
                paper_authors_raw = (paper.authors or "").strip()
                dedup_title = paper_title_raw.lower()
                dedup_key = f"{dedup_title}|{paper_authors_raw.lower()}"
                paper_metadata_docs.append({
                    "id": f"paper-{paper.pk}",
                    "title": paper_title_raw,
                    "authors": paper_authors_raw,
                    "ingredients_text": normalize_text(paper.keywords or ""),
                    "general_text": "",
                    "has_document": False,
                    "submitter_name": "",
                    "submitter_email": "",
                    "submitter_program": "",
                    "submitter_college": "",
                    "submitter_login_as": "",
                    "adviser": getattr(paper, "adviser", "") or "",
                    "published_month": getattr(paper, "published_month", "") or "",
                    "published_year": getattr(paper, "published_year", "") or "",
                    "keywords": paper.keywords or "",
                    "abstract": paper.abstract or "",
                    "status": "Published",
                    "source_url": "",
                    "submitted_at": published_str or created_str,
                    "reviewed_at": published_str or created_str,
                    "modified_time": published_str or created_str,
                    "text": combined,
                    "dedup_title": dedup_title,
                    "dedup_key": dedup_key,
                })

            paper_metadata_docs = deduplicate_repository_documents(paper_metadata_docs)
            merged = list(submission_docs)
            merged.extend(paper_metadata_docs)
            repository_documents = deduplicate_repository_documents(merged)
            total_repository_documents = len(repository_documents)

            food_check = assess_food_relevance(query_title_guess, query_abstract_guess, "", query_text)
            if not query_text.strip():
                form.add_error("proposal_file", "The uploaded file does not contain readable text.")
            elif not food_check["is_food"]:
                form.add_error("proposal_file", not_food_research_error(food_check))
                _log_system_event(
                    request, request.user, SystemLogType.ACTIVITY,
                    f"Similarity check refused '{uploaded_file_name}': not food research.",
                )
            else:
                query_passages, query_semantic = semantic.query_vectors(query_text)
                semantic_used = query_semantic is not None
                similarity_results, similarity_weights_used = rank_similar_documents_weighted(
                    {
                        "ingredients": query_ingredients_guess,
                        "general": query_general_guess,
                        "title": query_title_guess,
                        "abstract": query_abstract_guess,
                    },
                    repository_documents,
                    threshold=0.0,
                    query_semantic=query_semantic,
                )
                similarity_results = similarity_results[:5]
                query_fields_raw = {
                    "title": query_title_guess,
                    "abstract": query_abstract_guess,
                    "ingredients": query_ingredients_guess,
                    "general": query_general_guess,
                }
                for result in similarity_results:
                    details = explain_similarity_match(query_fields_raw, result)
                    details.append(semantic.meaning_section(result, query_passages, result.get("document_text", "")))
                    result["match_details_json"] = json.dumps(details)
                _record_similarity_check(request.user, uploaded_file_name, similarity_results, total_repository_documents)
                can_submit_for_review = not any(result["score_percent"] > 30 for result in similarity_results)
                # Unfinished papers can still be checked (e.g. to test a topic early),
                # but upload is only offered for a complete paper, as Submit Research
                # refuses unfinished ones.
                paper_check = assess_document(read_text_layer(proposal_file))
                paper_status = paper_check["status"]
                paper_missing = paper_check["missing"]
                if not can_submit_for_review:
                    similarity_outcome = "blocked"
                elif paper_status == "incomplete":
                    similarity_outcome = "unfinished"
                else:
                    similarity_outcome = "ready"
                if similarity_outcome == "unfinished":
                    _log_system_event(
                        request,
                        request.user,
                        SystemLogType.ACTIVITY,
                        f"Ran similarity check on '{uploaded_file_name}' — low similarity, but the paper looks unfinished "
                        f"(missing: {', '.join(paper_missing)}); upload not offered.",
                    )
                elif can_submit_for_review:
                    stored_path = default_storage.save(
                        f"pending_similarity_uploads/{request.user.pk}/{uploaded_file_name}",
                        proposal_file,
                    )
                    request.session[SIMILARITY_UPLOAD_ALLOWED_SESSION_KEY] = True
                    request.session[SIMILARITY_CHECKED_FILE_NAME_SESSION_KEY] = uploaded_file_name
                    request.session[SIMILARITY_CHECKED_FILE_STORAGE_KEY] = stored_path
                    _log_system_event(
                        request,
                        request.user,
                        SystemLogType.ACTIVITY,
                        f"Ran similarity check on '{uploaded_file_name}' — low similarity result; upload allowed.",
                    )
                else:
                    top_score = max((r["score_percent"] for r in similarity_results), default=0)
                    _log_system_event(
                        request,
                        request.user,
                        SystemLogType.ACTIVITY,
                        f"Ran similarity check on '{uploaded_file_name}' — highest match {top_score}%; upload blocked due to moderate/high similarity.",
                    )
        except Exception as exc:
            repository_error = str(exc)

    context = {
        "page_title": "Research Similarity",
        "form": form,
        "similarity_results": similarity_results,
        "total_repository_documents": total_repository_documents,
        "comparison_submitted": comparison_submitted,
        "student_name": account_display_name(request.user),
        "student_role": "Student",
        "uploaded_file_name": uploaded_file_name,
        "repository_error": repository_error,
        "can_submit_for_review": can_submit_for_review,
        "similarity_outcome": similarity_outcome,
        "paper_status": paper_status,
        "paper_missing": paper_missing,
        "detected_title": query_title_guess,
        "detected_abstract": query_abstract_guess,
        "similarity_weights": similarity_weights_used,
        "similarity_base_weights": SIMILARITY_WEIGHTS,
        "semantic_used": semantic_used,
        "semantic_model_label": semantic.MODEL_LABEL,
        "framework_summary": (
            "This module applies Information Retrieval Theory by organizing research documents "
            "from approved research submissions stored in the system repository and PostgreSQL "
            "records for search and comparison. It uses the TF-IDF "
            "mathematical method for text representation and cosine similarity for document "
            "comparison, weighted 30% ingredients & process, 30% the rest of the paper, "
            "20% title, and 20% abstract, implemented through the scikit-learn library. "
            "A pre-trained Sentence-BERT language model (all-MiniLM-L6-v2) also compares the "
            "meaning of passages, so reworded copying is found. The AI score decides the result; "
            "TF-IDF also counts for a near-exact copy (80%+), and decides alone if the model is off."
        ),
    }
    return render(request, "core/research_similarity.html", context)


@login_required(login_url="login")
def student_similarity_records_view(request):
    """Standalone module: every Similarity Check the logged-in student has
    ever run, filterable by date. A Student only ever sees their own role, so
    unlike the Admin/Super Admin version of this page, there's no role filter."""
    redirect_response = _student_only_or_redirect(request)
    if redirect_response:
        return redirect_response

    date_from_raw = request.GET.get("date_from", "").strip()
    date_to_raw = request.GET.get("date_to", "").strip()
    date_from = parse_date(date_from_raw)
    date_to = parse_date(date_to_raw)

    records = SimilarityCheckRecord.objects.filter(user=request.user)
    if date_from:
        records = records.filter(checked_at__date__gte=date_from)
    if date_to:
        records = records.filter(checked_at__date__lte=date_to)

    paginator = Paginator(records, SIMILARITY_RECORDS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "page_title": "Similarity Check Records",
        "student_name": account_display_name(request.user),
        "student_role": "Student",
        "similarity_history": page_obj,
        "page_obj": page_obj,
        "date_from": date_from_raw if date_from else "",
        "date_to": date_to_raw if date_to else "",
    }
    return render(request, "core/student_similarity_records.html", context)


# Role filter on System Logs: key -> (label, which log owners it keeps).
LOG_ROLE_FILTERS = {
    "super_admin": ("Super Admin", Q(user__is_superuser=True)),
    "admin": ("Admin", Q(user__is_staff=True, user__is_superuser=False)),
    "student": ("Student", Q(user__isnull=False, user__is_staff=False, user__is_superuser=False)),
}


def _log_filters(params, allowed_roles=()):
    """Search, role and date range for the log pages, plus the query string
    that keeps them when switching tabs or pages."""
    search = (params.get("q") or "").strip()[:200]
    role = (params.get("role") or "").strip()
    if role not in allowed_roles:
        role = ""
    date_from = _parse_date_param(params.get("date_from"))
    date_to = _parse_date_param(params.get("date_to"))
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
    kept = {
        "q": search,
        "role": role,
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
    }
    kept = {key: value for key, value in kept.items() if value}
    return {"q": search, "role": role, "date_from": date_from, "date_to": date_to,
            "active": bool(kept), "params": urlencode(kept)}


def _apply_log_role_and_dates(logs, filters):
    if filters["role"]:
        logs = logs.filter(LOG_ROLE_FILTERS[filters["role"]][1])
    if filters["date_from"]:
        logs = logs.filter(created_at__date__gte=filters["date_from"])
    if filters["date_to"]:
        logs = logs.filter(created_at__date__lte=filters["date_to"])
    return logs


def _page_links(page_obj):
    """Page numbers for the pager, with None where pages are skipped (…)."""
    return [number if isinstance(number, int) else None
            for number in page_obj.paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1)]


def _log_page_context(filters, page_obj):
    return {
        "search_query": filters["q"],
        "role_filter": filters["role"],
        "date_from": filters["date_from"].isoformat() if filters["date_from"] else "",
        "date_to": filters["date_to"].isoformat() if filters["date_to"] else "",
        "filters_active": filters["active"],
        "filter_params": filters["params"],
        "page_links": _page_links(page_obj),
    }


@login_required(login_url="login")
def student_logs_view(request):
    """My Logs: the student's own Login/Logout and Activity events, shown as
    two separate tables that are never both on screen at once -- picking one
    tab swaps the table entirely, rather than showing both (as the Admin
    System Logs page does) with one left empty by the filter."""
    redirect_response = _student_only_or_redirect(request)
    if redirect_response:
        return redirect_response

    log_type = request.GET.get("type", "login").strip().lower()
    if log_type not in ("login", "activity"):
        log_type = "login"

    filters = _log_filters(request.GET)
    base_logs = _apply_log_role_and_dates(SystemLog.objects.filter(user=request.user), filters)
    if filters["q"]:
        base_logs = base_logs.filter(action__icontains=filters["q"])
    login_log_types = (SystemLogType.LOGIN, SystemLogType.LOGOUT)
    login_logs = base_logs.filter(log_type__in=login_log_types)
    activity_logs = base_logs.filter(log_type=SystemLogType.ACTIVITY)

    logs = login_logs if log_type == "login" else activity_logs
    paginator = Paginator(logs, SYSTEM_LOGS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    events = [
        {
            "timestamp": timezone.localtime(log.created_at).strftime("%b %d, %Y %I:%M:%S %p"),
            "log_type": log.log_type,
            "action": log.action,
            "ip_address": log.ip_address or "N/A",
        }
        for log in page_obj
    ]

    context = {
        "page_title": "My Logs",
        "student_name": account_display_name(request.user),
        "student_role": "Student",
        "active_type": log_type,
        "events": events,
        "page_obj": page_obj,
        "login_count": login_logs.count(),
        "activity_count": activity_logs.count(),
        **_log_page_context(filters, page_obj),
    }
    return render(request, "core/student_logs.html", context)


def _document_type_label(document):
    """Matches the exact doc-type lookup used by the admin repository view's
    research-details modal (admin_repository_add_research.html), so the
    student version shows the same 'PDF'/'DOCX'/'TXT' label, never the file
    itself for entries that aren't the viewer's own."""
    if not document:
        return ""
    lower = document.name.lower()
    if lower.endswith(".pdf"):
        return "PDF"
    if lower.endswith(".docx"):
        return "DOCX"
    if lower.endswith(".txt"):
        return "TXT"
    return "Document"


def _repository_search_row_from_paper(paper):
    """Plain, template-safe dict for a metadata-only ResearchPaper entry —
    never has a document, so never anything to redact."""
    return {
        "source": "paper",
        "pk": f"paper-{paper.pk}",
        "title": (paper.title or "").strip(),
        "authors": (paper.authors or "").strip(),
        "abstract": paper.abstract or "",
        "keywords": paper.keywords or "",
        "adviser": paper.adviser or "",
        "category": paper.food_category,
        "published_date": paper.published_date.strftime("%b %d, %Y") if paper.published_date else "",
        "published_month": paper.published_month or "",
        "published_year": paper.published_year,
        "added_at": timezone.localtime(paper.created_at).strftime("%b %d, %Y"),
        "added_sort": paper.created_at,
        "sort_date": paper.published_date or timezone.localdate(paper.created_at),
        "is_mine": False,
        "has_document": False,
        "doc_type": "",
        "document_url": "",
    }


def _repository_search_row_from_submission(submission, user):
    """Plain, template-safe dict for an approved ResearchSubmission. This is
    the ONLY place `document_url` is ever set — it stays blank unless the
    entry belongs to the viewing student, so another student's uploaded file
    is never exposed through Repository Search. `has_document`/`doc_type`
    stay visible either way -- they're just a status label (e.g. "PDF" /
    "Metadata-only"), not the file itself."""
    is_mine = submission.student_id == user.id
    has_document = bool(submission.document)
    return {
        "source": "submission",
        "pk": f"submission-{submission.pk}",
        "title": (submission.title or "").strip(),
        "authors": (submission.authors or "").strip(),
        "abstract": submission.abstract or "",
        "keywords": submission.keywords or "",
        "adviser": submission.adviser or "",
        "category": submission.food_category,
        "published_date": submission.published_date.strftime("%b %d, %Y") if submission.published_date else "",
        "published_month": submission.published_month or "",
        "published_year": submission.published_year,
        "added_at": timezone.localtime(submission.submitted_at).strftime("%b %d, %Y"),
        "added_sort": submission.submitted_at,
        "sort_date": submission.published_date or timezone.localdate(submission.submitted_at),
        "is_mine": is_mine,
        "has_document": has_document,
        "doc_type": _document_type_label(submission.document) if has_document else "",
        "document_url": reverse("open_submission_document", args=[submission.pk]) if (is_mine and submission.document) else "",
    }


def _all_repository_rows(user):
    """Every repository study (papers + approved submissions), deduped the same
    way the student search does."""
    rows = [
        _repository_search_row_from_paper(paper)
        for paper in ResearchPaper.objects.select_related("food_category", "food_category__parent")
    ]
    rows += [
        _repository_search_row_from_submission(submission, user)
        for submission in ResearchSubmission.objects.select_related("food_category", "food_category__parent").filter(
            status=ResearchSubmissionStatus.APPROVED
        )
    ]
    return _dedupe_repository_search_rows(rows)


def _dedupe_repository_search_rows(rows):
    """A ResearchPaper and an approved ResearchSubmission can describe the
    same study (one's the admin-entered metadata twin of the other, often
    created independently -- e.g. the paper has the adviser on record but the
    matching submission's adviser field was left blank, or vice versa). Keep
    one row per (title, authors), preferring the submission-derived row's
    identity since it carries ownership/file info the paper twin never has,
    but backfill any field the winning row left blank from the other row
    rather than silently discarding data the loser actually had."""
    best_by_key = {}
    order = []
    backfill_fields = (
        "adviser", "keywords", "category", "abstract",
        "published_date", "published_month", "published_year",
    )
    for row in rows:
        key = (row["title"].lower(), row["authors"].lower())
        if key not in best_by_key:
            best_by_key[key] = row
            order.append(key)
            continue
        existing = best_by_key[key]
        if row["source"] == "submission" and existing["source"] != "submission":
            winner, loser = row, existing
        else:
            winner, loser = existing, row
        for field in backfill_fields:
            if not winner.get(field) and loser.get(field):
                winner[field] = loser[field]
        best_by_key[key] = winner
    return [best_by_key[key] for key in order]


def _sort_repository_search_rows(rows, search_query):
    """No query: most-recent-first. With a query: a simple relevance score —
    title match counts more than a keywords match, which counts more than an
    authors/adviser match, which counts more than matching only in the
    abstract. Deliberately not TF-IDF/sklearn -- that's for comparing whole
    documents (Similarity Check), not scoring a short query against a few
    short fields."""
    query = (search_query or "").strip().lower()
    if not query:
        return sorted(rows, key=lambda r: r["sort_date"], reverse=True)

    def relevance(row):
        score = _repository_relevance(
            query, row["title"], row["keywords"], row["authors"], row["adviser"], row["abstract"]
        )
        return (score, row["sort_date"])

    return sorted(rows, key=relevance, reverse=True)


def _repository_text_filter(query):
    """What the repository search bar matches: title, authors, abstract,
    keywords, or adviser (used by the student dashboard and the Admin /
    Super Admin Research Repository alike)."""
    return (
        Q(title__icontains=query)
        | Q(authors__icontains=query)
        | Q(abstract__icontains=query)
        | Q(keywords__icontains=query)
        | Q(adviser__icontains=query)
    )


def _repository_relevance(query, title, keywords, authors, adviser, abstract):
    """Title match counts more than keywords, which counts more than
    authors/adviser, which counts more than the abstract."""
    query = (query or "").strip().lower()
    score = 0
    if query in (title or "").lower():
        score += 5
    if query in (keywords or "").lower():
        score += 3
    if query in (authors or "").lower() or query in (adviser or "").lower():
        score += 2
    if query in (abstract or "").lower():
        score += 1
    return score


def _parse_date_param(value):
    """A YYYY-MM-DD query parameter as a date, or None when blank/invalid."""
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _repository_search_published_years():
    paper_years = ResearchPaper.objects.exclude(published_year__isnull=True).values_list(
        "published_year", flat=True
    ).distinct()
    submission_years = ResearchSubmission.objects.filter(
        status=ResearchSubmissionStatus.APPROVED
    ).exclude(published_year__isnull=True).values_list("published_year", flat=True).distinct()
    return sorted(set(paper_years) | set(submission_years), reverse=True)


def _repository_search_suggestions(limit=60, rows_per_source=40):
    """Distinct titles + individual keywords drawn from the FULL repository
    (every ResearchPaper plus every approved ResearchSubmission) for the
    search bar's typeahead -- matches what the search itself can actually
    find, not just the viewing student's own submissions.

    Pulled in round-robin between the two sources (one row from each per
    round) rather than one source fully then the other -- otherwise, since
    a handful of ResearchPaper rows can easily carry enough keywords to fill
    the whole cap on their own, approved student submissions would never get
    a chance to appear in suggestions at all."""
    suggestions = []
    seen = set()

    def add(value):
        cleaned = (value or "").strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            suggestions.append(cleaned)

    paper_rows = list(
        ResearchPaper.objects.order_by("-created_at").values_list("title", "keywords")[:rows_per_source]
    )
    submission_rows = list(
        ResearchSubmission.objects.filter(status=ResearchSubmissionStatus.APPROVED)
        .order_by("-submitted_at")
        .values_list("title", "keywords")[:rows_per_source]
    )

    for i in range(max(len(paper_rows), len(submission_rows))):
        for rows in (paper_rows, submission_rows):
            if i >= len(rows):
                continue
            title, keywords = rows[i]
            add(title)
            for keyword in (keywords or "").split(","):
                add(keyword)
        if len(suggestions) >= limit:
            break
    return suggestions[:limit]


def _split_text_into_paragraphs(raw_text, max_len=600):
    text = (raw_text or "").strip()
    if not text:
        return []
    double_split = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    paragraphs = []
    for chunk in double_split:
        current = ""
        for sentence in re.split(r"(?<=[.!?])\s+", chunk):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(current) + len(sentence) + 1 <= max_len:
                current = (current + " " + sentence).strip() if current else sentence
            else:
                if current:
                    paragraphs.append(current)
                current = sentence
        if current:
            paragraphs.append(current)
    return paragraphs or [text]


def _docx_paragraph_to_formatted_html(paragraph):
    run_html = []
    for run in paragraph.runs:
        text = (run.text or "")
        if not text:
            continue
        escaped = (
            text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
        )
        classes = []
        open_tags = []
        close_tags = []
        if getattr(run, "bold", False):
            open_tags.append("<strong>")
            close_tags.insert(0, "</strong>")
        if getattr(run, "italic", False):
            open_tags.append("<em>")
            close_tags.insert(0, "</em>")
        if getattr(run, "underline", False) and str(run.underline) != "None":
            open_tags.append('<span style="text-decoration: underline;">')
            close_tags.insert(0, "</span>")
        try:
            style_name = paragraph.style.name if paragraph.style else ""
        except Exception:
            style_name = ""
        if "Heading 1" in style_name:
            classes.append("font-extrabold text-2xl leading-tight mt-6 mb-3 text-slate-900")
        elif "Heading 2" in style_name:
            classes.append("font-bold text-xl leading-snug mt-5 mb-2 text-slate-900")
        elif "Heading 3" in style_name:
            classes.append("font-bold text-lg leading-snug mt-4 mb-2 text-slate-900")
        elif "Title" in style_name:
            classes.append("font-black text-3xl leading-tight mt-8 mb-4 text-slate-950")
        class_attr = f' class="{" ".join(classes)}"' if classes else ""
        run_html.append(f'<span{class_attr}>{"".join(open_tags)}{escaped}{"".join(close_tags)}</span>')

    combined = "".join(run_html).strip()
    if not combined:
        return ""

    try:
        style_name = paragraph.style.name if paragraph.style else ""
    except Exception:
        style_name = ""

    style_html = ""
    alignment = getattr(paragraph, "alignment", None)
    if alignment is not None:
        # WD_PARAGRAPH_ALIGNMENT: 0=Left, 1=Center, 2=Right, 3=Justify
        try:
            align_val = int(alignment)
        except Exception:
            align_val = -1
        if align_val == 1:
            style_html = ' style="text-align: center;"'
        elif align_val == 2:
            style_html = ' style="text-align: right;"'
        elif align_val == 3:
            style_html = ' style="text-align: justify;"'

    if "Heading 1" in style_name:
        return f'<h1 class="font-extrabold text-2xl leading-tight mt-6 mb-3 text-slate-900"{style_html}>{combined}</h1>'
    if "Heading 2" in style_name:
        return f'<h2 class="font-bold text-xl leading-snug mt-5 mb-2 text-slate-900"{style_html}>{combined}</h2>'
    if "Heading 3" in style_name:
        return f'<h3 class="font-bold text-lg leading-snug mt-4 mb-2 text-slate-900"{style_html}>{combined}</h3>'
    if "Title" in style_name:
        return f'<h1 class="font-black text-3xl leading-tight mt-8 mb-4 text-slate-950"{style_html}>{combined}</h1>'

    try:
        list_type = ""
        if paragraph.style and "List Bullet" in style_name:
            list_type = "bullet"
        elif paragraph.style and "List Number" in style_name:
            list_type = "number"
        if list_type == "bullet":
            return f'<li class="ml-5 list-disc marker:text-slate-400 py-0.5">{combined}</li>'
        if list_type == "number":
            return f'<li class="ml-5 list-decimal marker:font-bold marker:text-slate-600 py-0.5">{combined}</li>'
    except Exception:
        pass

    return f'<p class="leading-8 text-[15.5px] text-slate-800 py-1"{style_html}>{combined}</p>'


def _docx_extract_basic_formatted_html(file_bytes):
    from docx import Document
    document = Document(BytesIO(file_bytes))
    html_parts = []
    last_was_li = False
    list_html_open = False
    close_list = False

    for paragraph in document.paragraphs:
        line_html = _docx_paragraph_to_formatted_html(paragraph)
        if not line_html:
            if list_html_open:
                html_parts.append("</ul>")
                list_html_open = False
                last_was_li = False
            else:
                html_parts.append('<div class="h-3"></div>')
            continue

        current_is_li = line_html.startswith("<li")

        try:
            style_name = paragraph.style.name if paragraph.style else ""
        except Exception:
            style_name = ""
        current_is_num = line_html.startswith('<li class="ml-5 list-decimal')
        current_is_bullet = current_is_li and not current_is_num

        if list_html_open:
            if (current_is_num and last_was_li == "num") or (current_is_bullet and last_was_li == "bullet"):
                pass
            else:
                close_list = True

        if close_list:
            html_parts.append("</ul>")
            list_html_open = False
            close_list = False
            last_was_li = False

        if current_is_li and not list_html_open:
            list_html_open = True
            tag = "ol" if current_is_num else "ul"
            klass = "space-y-0 pl-1" if current_is_num else "space-y-0 pl-1"
            html_parts.append(f'<{tag} class="{klass}">')
            last_was_li = "num" if current_is_num else "bullet"

        html_parts.append(line_html)

    if list_html_open:
        html_parts.append("</ul>")

    raw_text = ""
    paragraphs_plain = []
    for p in document.paragraphs:
        t = p.text.strip()
        if t:
            paragraphs_plain.append(t)
    raw_text = "\n\n".join(paragraphs_plain)
    return "\n".join(html_parts), raw_text


def _docx_extract_mammoth_html(file_bytes):
    import mammoth
    result = mammoth.convert_to_html(BytesIO(file_bytes))
    html_body = result.value or ""
    messages = result.messages or []
    warnings = [str(m) for m in messages if m and "warning" in str(getattr(m, "type", "")).lower()]
    return html_body, warnings


def _txt_to_formatted_html(file_bytes):
    text = file_bytes.decode("utf-8", errors="replace")
    parts = []
    for raw_block in re.split(r"\n\s*\n", text):
        block = raw_block.strip()
        if not block:
            parts.append('<div class="h-3"></div>')
            continue
        lines = block.splitlines()
        if len(lines) == 1 and len(lines[0]) < 80 and not lines[0].endswith((".", "?", "!", ",", ";", ":")):
            first_words = lines[0].split()
            if len(first_words) <= 12:
                title_escaped = (
                    lines[0]
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                parts.append(f'<h3 class="font-bold text-lg leading-snug mt-5 mb-2 text-slate-900">{title_escaped}</h3>')
                continue
        escaped = (
            block
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        lines_joined = "<br>".join(
            ln for ln in escaped.splitlines()
        )
        parts.append(f'<p class="leading-8 text-[15.5px] text-slate-800 py-1 whitespace-pre-wrap">{lines_joined}</p>')
    return "\n".join(parts), text


@login_required(login_url="login")
def admin_preview_submission_document(request, submission_id):
    redirect_response = _admin_module_or_denied(request, AdminModule.MANAGE_SUBMISSIONS, AdminModule.SIMILARITY_CHECK)
    if redirect_response:
        return redirect_response

    submission = get_object_or_404(ResearchSubmission, pk=submission_id)
    if not submission.document:
        raise Http404("No document attached to this submission.")

    file_name = os.path.basename(submission.document.name)
    ext = os.path.splitext(file_name)[1].lower()

    is_super_admin = request.user.is_superuser
    admin_role = "Super Admin" if is_super_admin else "Admin"
    page_title = f"Document Preview — {submission.title[:70]}"
    admin_name = request.user.get_full_name().strip() or request.user.username

    file_size = None
    try:
        file_size = submission.document.size
    except Exception:
        pass

    native_viewer_url = reverse("admin_view_submission_raw", args=[submission_id])
    download_url = reverse("admin_download_submission_document", args=[submission_id])
    back_url = reverse("admin_similarity_check")

    formatted_html = ""
    raw_text = ""
    text_error = ""
    conversion_warnings = []
    conversion_method = ""
    viewer_mode = "iframe"

    try:
        with submission.document.open("rb") as fh:
            file_bytes = fh.read()
    except Exception as e:
        file_bytes = b""
        text_error = f"Error reading stored file: {e}"

    if file_bytes and ext == ".pdf":
        viewer_mode = "iframe"
    elif file_bytes and ext == ".docx":
        try:
            formatted_html, warnings = _docx_extract_mammoth_html(file_bytes)
            if formatted_html.strip():
                conversion_warnings = warnings or []
                conversion_method = "mammoth"
                try:
                    raw_text = re.sub(r"<[^>]+>", " ", formatted_html)
                    raw_text = re.sub(r"\s+", " ", raw_text).strip()
                except Exception:
                    raw_text = ""
        except Exception:
            formatted_html = ""

        if not formatted_html.strip():
            try:
                formatted_html, raw_text = _docx_extract_basic_formatted_html(file_bytes)
                conversion_method = "python-docx"
            except Exception as ie:
                formatted_html = ""
                raw_text = ""
                text_error = f"Could not parse DOCX contents: {ie}"
    elif file_bytes and ext == ".txt":
        try:
            formatted_html, raw_text = _txt_to_formatted_html(file_bytes)
            conversion_method = "text"
        except Exception as ie:
            formatted_html = ""
            raw_text = ""
            text_error = f"Could not parse TXT contents: {ie}"
    elif file_bytes and ext == ".doc":
        text_error = ".doc (legacy Word) files cannot be rendered inline. Please use the Download button below or open the native viewer to open this file locally in Microsoft Word."
    elif file_bytes:
        text_error = f"File type '{ext}' may not render natively in the browser. Use the native viewer tab or Download button below."

    total_words = len(raw_text.split()) if raw_text else 0
    approx_pages = max(1, round(total_words / 300)) if total_words else 0
    text_paragraphs = _split_text_into_paragraphs(raw_text) if raw_text else []

    context = {
        "page_title": page_title,
        "is_super_admin": is_super_admin,
        "admin_role": admin_role,
        "admin_name": admin_name,
        "submission": submission,
        "file_name": file_name,
        "file_ext": ext,
        "file_size": file_size,
        "viewer_mode": viewer_mode,
        "native_viewer_url": native_viewer_url,
        "pdf_viewer_url": native_viewer_url,
        "formatted_html": formatted_html,
        "text_paragraphs": text_paragraphs,
        "text_error": text_error,
        "total_words": total_words,
        "approx_pages": approx_pages,
        "conversion_method": conversion_method,
        "conversion_warnings": conversion_warnings,
        "download_url": download_url,
        "back_url": back_url,
    }
    return render(request, "core/admin_document_preview.html", context)


def _inline_submission_file_response(submission):
    if not submission.document:
        raise Http404("No document attached to this submission.")

    file_name = os.path.basename(submission.document.name)
    ext = os.path.splitext(file_name)[1].lower()
    content_type, _ = mimetypes.guess_type(file_name)
    if not content_type:
        if ext == ".pdf":
            content_type = "application/pdf"
        elif ext == ".docx":
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif ext == ".doc":
            content_type = "application/msword"
        elif ext == ".txt":
            content_type = "text/plain; charset=utf-8"
        else:
            content_type = "application/octet-stream"

    try:
        file_handle = submission.document.open("rb")
    except Exception:
        raise Http404("Document file not found in storage.")

    response = FileResponse(
        file_handle,
        content_type=content_type,
        as_attachment=False,
        filename=file_name,
    )
    safe_name = file_name.replace('"', "")
    response["Content-Disposition"] = f'inline; filename="{safe_name}"; filename*=UTF-8\'\'{safe_name}'
    response["X-Content-Type-Options"] = "nosniff"
    # Pages stay X_FRAME_OPTIONS = "DENY"; only the file itself may be framed,
    # and only by our own pages (the Document Preview's built-in viewer).
    response["X-Frame-Options"] = "SAMEORIGIN"
    response["Accept-Ranges"] = "bytes"
    try:
        response["Content-Length"] = submission.document.size
    except Exception:
        pass
    return response


@login_required(login_url="login")
def open_submission_document(request, submission_id):
    """The one route to a submitted file: the group that submitted it, or staff
    with a module that works with submissions. Uploaded files are never linked
    by their storage path, so they can't be fetched without this check."""
    submission = get_object_or_404(ResearchSubmission, pk=submission_id)
    user = request.user
    if user.is_staff or user.is_superuser:
        allowed = any(
            _admin_has_module(user, module)
            for module in (AdminModule.MANAGE_SUBMISSIONS, AdminModule.RESEARCH_REPOSITORY, AdminModule.SIMILARITY_CHECK)
        )
        if not allowed:
            return _render_access_denied(request, "Submitted documents")
    elif submission.student_id != user.pk:
        raise Http404("Document not found.")
    return _inline_submission_file_response(submission)


@login_required(login_url="login")
def admin_view_submission_raw(request, submission_id):
    redirect_response = _admin_module_or_denied(request, AdminModule.MANAGE_SUBMISSIONS, AdminModule.SIMILARITY_CHECK)
    if redirect_response:
        return redirect_response

    submission = get_object_or_404(ResearchSubmission, pk=submission_id)
    return _inline_submission_file_response(submission)

@login_required(login_url="login")
def admin_download_submission_document(request, submission_id):
    redirect_response = _admin_module_or_denied(request, AdminModule.MANAGE_SUBMISSIONS, AdminModule.SIMILARITY_CHECK)
    if redirect_response:
        return redirect_response

    submission = get_object_or_404(ResearchSubmission, pk=submission_id)
    if not submission.document:
        raise Http404("No document attached to this submission.")

    file_name = os.path.basename(submission.document.name)
    ext = os.path.splitext(file_name)[1].lower()
    content_type, _ = mimetypes.guess_type(file_name)
    if not content_type:
        if ext == ".pdf":
            content_type = "application/pdf"
        elif ext == ".docx":
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif ext == ".doc":
            content_type = "application/msword"
        elif ext == ".txt":
            content_type = "text/plain; charset=utf-8"
        else:
            content_type = "application/octet-stream"

    try:
        file_handle = submission.document.open("rb")
    except Exception:
        raise Http404("Document file not found in storage.")

    response = FileResponse(
        file_handle,
        content_type=content_type,
        as_attachment=True,
        filename=file_name,
    )
    safe_name = file_name.replace('"', "")
    response["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    try:
        response["Content-Length"] = submission.document.size
    except Exception:
        pass
    return response


@login_required(login_url="login")
def admin_research_similarity_view(request):
    redirect_response = _admin_module_or_denied(request, AdminModule.SIMILARITY_CHECK)
    if redirect_response:
        return redirect_response

    semantic.warm_up_in_background()
    form = ResearchSimilarityForm()
    similarity_results = []
    comparison_submitted = False
    repository_error = ""
    uploaded_file_name = ""
    total_repository_documents = 0
    top_similarity_score = 0
    overall_level = ""
    overall_label = ""
    query_title_guess = ""
    query_abstract_guess = ""
    query_ingredients_guess = ""
    query_general_guess = ""
    similarity_weights_used = {}
    semantic_used = False

    if request.method == "POST":
        form = ResearchSimilarityForm(request.POST, request.FILES)
        if form.is_valid():
            comparison_submitted = True
            proposal_file = form.cleaned_data["proposal_file"]
            uploaded_file_name = proposal_file.name

            try:
                query_text = extract_text_from_uploaded_file(proposal_file, use_ocr=False)
                (
                    query_title_guess,
                    query_abstract_guess,
                    query_ingredients_guess,
                    query_general_guess,
                ) = extract_food_research_sections(query_text)
                approved_submissions = ResearchSubmission.objects.select_related("student").filter(
                    status=ResearchSubmissionStatus.APPROVED
                )
                submission_docs = build_repository_documents_from_submissions(approved_submissions)
                submission_docs = deduplicate_repository_documents(submission_docs)

                paper_metadata_docs = []
                for paper in ResearchPaper.objects.all():
                    combined = normalize_text(
                        paper.title or "",
                        paper.abstract or "",
                        paper.keywords or "",
                    )
                    if not combined.strip():
                        continue
                    published_str = ""
                    try:
                        if paper.published_date:
                            published_str = paper.published_date.isoformat()
                    except Exception:
                        published_str = ""
                    created_str = ""
                    try:
                        if paper.created_at:
                            created_str = timezone.localtime(paper.created_at).isoformat()
                    except Exception:
                        created_str = ""
                    paper_title_raw = (paper.title or "").strip() or "Untitled Repository Study"
                    paper_authors_raw = (paper.authors or "").strip()
                    dedup_title = paper_title_raw.lower()
                    dedup_key = f"{dedup_title}|{paper_authors_raw.lower()}"
                    paper_metadata_docs.append({
                        "id": f"paper-{paper.pk}",
                        "title": paper_title_raw,
                        "authors": paper_authors_raw,
                        "ingredients_text": normalize_text(paper.keywords or ""),
                        "general_text": "",
                        "has_document": False,
                        "submitter_name": "",
                        "submitter_email": "",
                        "submitter_program": "",
                        "submitter_college": "",
                        "submitter_login_as": "",
                        "adviser": getattr(paper, "adviser", "") or "",
                        "published_month": getattr(paper, "published_month", "") or "",
                        "published_year": getattr(paper, "published_year", "") or "",
                        "keywords": paper.keywords or "",
                        "abstract": paper.abstract or "",
                        "status": "Published",
                        "source_url": "",
                        "submitted_at": published_str or created_str,
                        "reviewed_at": published_str or created_str,
                        "modified_time": published_str or created_str,
                        "text": combined,
                        "dedup_title": dedup_title,
                        "dedup_key": dedup_key,
                    })

                paper_metadata_docs = deduplicate_repository_documents(paper_metadata_docs)
                merged = list(submission_docs)
                merged.extend(paper_metadata_docs)
                repository_documents = deduplicate_repository_documents(merged)
                total_repository_documents = len(repository_documents)

                food_check = assess_food_relevance(query_title_guess, query_abstract_guess, "", query_text)
                if not query_text.strip():
                    form.add_error("proposal_file", "The uploaded file does not contain readable text.")
                elif not food_check["is_food"]:
                    form.add_error("proposal_file", not_food_research_error(food_check))
                    _log_system_event(
                        request, request.user, SystemLogType.ACTIVITY,
                        f"Similarity check refused '{uploaded_file_name}': not food research.",
                    )
                else:
                    query_passages, query_semantic = semantic.query_vectors(query_text)
                    semantic_used = query_semantic is not None
                    raw_results, similarity_weights_used = rank_similar_documents_weighted(
                        {
                            "ingredients": query_ingredients_guess,
                            "general": query_general_guess,
                            "title": query_title_guess,
                            "abstract": query_abstract_guess,
                        },
                        repository_documents,
                        threshold=0.0,
                        query_semantic=query_semantic,
                    )
                    raw_results = raw_results[:10]
                    query_fields_raw = {
                        "title": query_title_guess,
                        "abstract": query_abstract_guess,
                        "ingredients": query_ingredients_guess,
                        "general": query_general_guess,
                    }
                    similarity_results = []
                    for r in raw_results:
                        result = dict(r)
                        details = explain_similarity_match(query_fields_raw, result)
                        details.append(semantic.meaning_section(result, query_passages, result.get("document_text", "")))
                        result["match_details_json"] = json.dumps(details)
                        result["view_url"] = ""
                        doc_id = result.get("id")
                        if isinstance(doc_id, int) or (isinstance(doc_id, str) and doc_id.isdigit()):
                            try:
                                sub_id = int(doc_id)
                                result["view_url"] = reverse("admin_preview_submission_document", args=[sub_id])
                            except Exception:
                                pass
                        similarity_results.append(result)
                    top_similarity_score = max((r["score_percent"] for r in similarity_results), default=0)
                    overall_level = similarity_level_for_percent(top_similarity_score)
                    overall_label = SIMILARITY_LEVELS[overall_level][0]
                    _log_system_event(
                        request,
                        request.user,
                        SystemLogType.ACTIVITY,
                        f"Super Admin ran similarity check on '{uploaded_file_name}' — top match {top_similarity_score}% ({overall_label}); corpus size {total_repository_documents}.",
                    )
                    _record_similarity_check(request.user, uploaded_file_name, similarity_results, total_repository_documents)
            except Exception as exc:
                repository_error = str(exc)

    total_approved_submissions = ResearchSubmission.objects.filter(
        status=ResearchSubmissionStatus.APPROVED
    ).count()
    total_papers = ResearchPaper.objects.count()

    context = {
        "page_title": "Similarity Check",
        "is_super_admin": request.user.is_superuser,
        "admin_role": "Super Admin" if request.user.is_superuser else "Admin",
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "form": form,
        "similarity_results": similarity_results,
        "total_repository_documents": total_repository_documents,
        "comparison_submitted": comparison_submitted,
        "uploaded_file_name": uploaded_file_name,
        "repository_error": repository_error,
        "top_similarity_score": top_similarity_score,
        "overall_level": overall_level,
        "overall_label": overall_label,
        "total_approved_submissions": total_approved_submissions,
        "total_papers": total_papers,
        "detected_title": query_title_guess,
        "detected_abstract": query_abstract_guess,
        "similarity_weights": similarity_weights_used,
        "similarity_base_weights": SIMILARITY_WEIGHTS,
        "semantic_used": semantic_used,
        "semantic_model_label": semantic.MODEL_LABEL,
        "framework_summary": (
            "Uses TF-IDF (Term Frequency–Inverse Document Frequency) vectorization together "
            "with cosine similarity via scikit-learn. The comparison corpus combines full-text "
            "from approved research submissions with metadata from every ResearchPaper entry "
            "in the repository so studies added directly to it are also checked. Weighted "
            "30% ingredients & process, 30% the rest of the paper, 20% title, 20% abstract. "
            "A pre-trained Sentence-BERT language model (all-MiniLM-L6-v2) also compares the "
            "meaning of passages, so reworded copying is found. The AI score decides the result; "
            "TF-IDF also counts for a near-exact copy (80%+), and decides alone if the model is off."
        ),
    }
    return render(request, "core/admin_similarity_check.html", context)


@login_required(login_url="login")
def admin_similarity_records_view(request):
    """Standalone module: Similarity Check history, filterable by date and
    (for a Super Admin only) by role. A staff Admin sees only their own runs;
    a Super Admin sees every role's (Admin, Super Admin, Student) in one view."""
    redirect_response = _admin_module_or_denied(request, AdminModule.SIMILARITY_RECORDS)
    if redirect_response:
        return redirect_response

    is_super_admin = request.user.is_superuser
    date_from_raw = request.GET.get("date_from", "").strip()
    date_to_raw = request.GET.get("date_to", "").strip()
    date_from = parse_date(date_from_raw)
    date_to = parse_date(date_to_raw)
    role_filter = request.GET.get("role", "all").strip().lower() if is_super_admin else "all"

    if is_super_admin:
        records = SimilarityCheckRecord.objects.select_related("user")
        if role_filter == "student":
            records = records.filter(user__is_staff=False, user__is_superuser=False)
        elif role_filter == "admin":
            records = records.filter(user__is_staff=True, user__is_superuser=False)
        elif role_filter == "super_admin":
            records = records.filter(user__is_superuser=True)
    else:
        records = SimilarityCheckRecord.objects.filter(user=request.user)

    if date_from:
        records = records.filter(checked_at__date__gte=date_from)
    if date_to:
        records = records.filter(checked_at__date__lte=date_to)

    paginator = Paginator(records, SIMILARITY_RECORDS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "page_title": "Similarity Check Records",
        "is_super_admin": is_super_admin,
        "admin_role": "Super Admin" if is_super_admin else "Admin",
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "similarity_history": page_obj,
        "page_obj": page_obj,
        "date_from": date_from_raw if date_from else "",
        "date_to": date_to_raw if date_to else "",
        "role_filter": role_filter,
    }
    return render(request, "core/admin_similarity_records.html", context)


LOGIN_ATTEMPT_WINDOW_SECONDS = 15 * 60
LOGIN_LOCKOUT_MAX_SECONDS = 60
LOGIN_FORGOT_PASSWORD_AFTER_FAILS = 2


def _login_lockout_seconds(fail_count):
    # 1st-2nd failure: no lock. 3rd: 15s, 4th: 30s, 5th and beyond: 60s (cap).
    if fail_count < 3:
        return 0
    return {3: 15, 4: 30}.get(fail_count, LOGIN_LOCKOUT_MAX_SECONDS)


def _login_throttle_key(request, username):
    # _get_client_ip only trusts X-Forwarded-For behind our own proxy, so the
    # header can't be rotated to dodge the throttle.
    return f"login-throttle:{_get_client_ip(request)}:{_username_key(username)}"


def _remaining_seconds(locked_until):
    return max(0, math.ceil((locked_until or 0) - time.time()))


def _current_login_ui(request):
    """Failed-attempt state mirrored in the session so the login page can show
    the Forgot Password link and the countdown (enforcement lives in the cache)."""
    ui = request.session.get("login_ui") or {}
    locked = _remaining_seconds(ui.get("locked_until"))
    fails = int(ui.get("fails", 0))
    if not locked and time.time() - ui.get("updated", 0) > LOGIN_ATTEMPT_WINDOW_SECONDS:
        fails = 0
    return fails, locked


def _registration_pending(user):
    """A group that signed up on the Registration page and is still waiting
    for an Admin or Super Admin to approve it."""
    profile = getattr(user, "registration_profile", None)
    return bool(profile and profile.approval_status == RegistrationStatus.PENDING)


def login_view(request):
    if request.user.is_authenticated:
        redirect_response = _redirect_authenticated_user(request.user)
        if redirect_response:
            return redirect_response

    form = LoginForm(request.POST or None)
    deactivated_notice = None
    pending_notice = None

    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"]
        password = form.cleaned_data["password"]
        throttle_key = _login_throttle_key(request, username)
        state = cache.get(throttle_key) or {"fails": 0, "locked_until": 0}
        _, session_locked = _current_login_ui(request)
        locked_for = max(_remaining_seconds(state["locked_until"]), session_locked)

        if locked_for:
            # Locked out: do not even look at the credentials.
            request.session["login_ui"] = {
                "fails": state["fails"],
                "locked_until": time.time() + locked_for,
                "updated": time.time(),
            }
        else:
            authenticated_user = authenticate(
                request,
                username=username,
                password=password,
            )
            invite = None
            deactivated_user = None
            if not authenticated_user:
                invite = PendingUserInvite.objects.filter(username__iexact=username).first()
                if invite and not check_password(password, invite.password_hash):
                    invite = None
            if not authenticated_user and not invite:
                candidate = User.objects.filter(username__iexact=username, is_active=False).first()
                if candidate and candidate.check_password(password):
                    deactivated_user = candidate

            if authenticated_user or invite or deactivated_user:
                cache.delete(throttle_key)
                request.session.pop("login_ui", None)

            if deactivated_user and _registration_pending(deactivated_user):
                pending_notice = (
                    "Your registration is still waiting for approval by an Admin or Super Admin, "
                    f"so you can't log in yet. We will email {deactivated_user.email} as soon as it is approved."
                )
                _log_system_event(
                    request,
                    deactivated_user,
                    SystemLogType.ACTIVITY,
                    "Sign-in blocked: the registration is still waiting for approval.",
                )
            elif deactivated_user:
                record = AccountDeactivation.objects.filter(user=deactivated_user).first()
                deactivated_notice = {
                    "reason": record.reason if record else "",
                    "date": timezone.localtime(record.deactivated_at).strftime("%b %d, %Y") if record else "",
                }
                _log_system_event(
                    request,
                    deactivated_user,
                    SystemLogType.ACTIVITY,
                    "Sign-in blocked: the account is deactivated.",
                )

            if invite:
                request.session["pending_invite_id"] = invite.pk
                return redirect("complete_profile")

            if deactivated_user:
                pass
            elif not authenticated_user:
                attempted_account = User.objects.filter(username__iexact=username).first()
                _log_system_event(
                    request,
                    attempted_account,
                    SystemLogType.LOGIN,
                    f"{FAILED_SIGNIN_LOG_PREFIX}: wrong password."
                    if attempted_account
                    else f"{FAILED_SIGNIN_LOG_PREFIX} for unknown username '{username[:60]}'.",
                )
                state["fails"] += 1
                lock = _login_lockout_seconds(state["fails"])
                state["locked_until"] = time.time() + lock if lock else 0
                cache.set(throttle_key, state, LOGIN_ATTEMPT_WINDOW_SECONDS)
                request.session["login_ui"] = {
                    "fails": state["fails"],
                    "locked_until": state["locked_until"],
                    "updated": time.time(),
                }
                form.add_error(None, "Invalid username or password.")
            elif authenticated_user.is_staff or authenticated_user.is_superuser:
                role_label = "Super Admin" if authenticated_user.is_superuser else "Admin"
                login(request, authenticated_user)
                _log_system_event(
                    request,
                    authenticated_user,
                    SystemLogType.LOGIN,
                    f"{role_label} logged in.",
                )
                if not _profile_is_complete(authenticated_user):
                    return redirect("complete_profile")
                return redirect("admin_dashboard")
            else:
                profile = getattr(authenticated_user, "registration_profile", None)
                if not profile:
                    form.add_error(None, "No user role is assigned to this account.")
                elif profile.login_as == LoginAs.STUDENT:
                    login(request, authenticated_user)
                    _log_system_event(
                        request,
                        authenticated_user,
                        SystemLogType.LOGIN,
                        "Student logged in.",
                    )
                    if not _profile_is_complete(authenticated_user):
                        return redirect("complete_profile")
                    return redirect("student_dashboard")
                else:
                    form.add_error(None, "This account role is not supported.")

    fails, lock_seconds_remaining = _current_login_ui(request)
    context = {
        "form": form,
        "form_submitted": False,
        "page_title": "Login",
        "show_forgot_password": fails >= LOGIN_FORGOT_PASSWORD_AFTER_FAILS,
        "lock_seconds_remaining": lock_seconds_remaining,
        "deactivated_notice": deactivated_notice,
        "pending_notice": pending_notice,
        "contact_email": (LandingSettings.load().contact_email or "").strip(),
    }
    return render(request, "core/login.html", context)


PASSWORD_RESET_SESSION_KEY = "pw_reset"
PASSWORD_RESET_OTP_TTL_SECONDS = 10 * 60
PASSWORD_RESET_MAX_OTP_ATTEMPTS = 5
PASSWORD_RESET_RESEND_COOLDOWN_SECONDS = 60
PASSWORD_RESET_MAX_SENDS_PER_HOUR = 5
PASSWORD_RESET_MAX_SENDS_PER_USER_PER_HOUR = 10
PASSWORD_RESET_VERIFIED_WINDOW_SECONDS = 15 * 60

logger = logging.getLogger(__name__)
_dummy_otp_hash = None


def _send_password_reset_email(user, code, purpose="reset"):
    what = "password change" if purpose == "change" else "password reset"
    subject = f"Your Food Match {what} code"
    name = user.get_full_name().strip() or user.username
    minutes = PASSWORD_RESET_OTP_TTL_SECONDS // 60
    text_body = (
        f"Hello {name},\n\n"
        f"Your Food Match {what} code is: {code}\n\n"
        f"It expires in {minutes} minutes. If you did not request a {what}, "
        "you can ignore this email and your password will stay the same.\n"
    )
    html_body = (
        f"<p>Hello {name},</p>"
        f"<p>Your Food Match {what} code is:</p>"
        f'<p style="font-size:28px;font-weight:700;letter-spacing:6px;">{code}</p>'
        f"<p>It expires in {minutes} minutes. If you did not request a {what}, "
        "you can ignore this email and your password will stay the same.</p>"
    )
    message = EmailMultiAlternatives(subject, text_body, to=[user.email])
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)


def _send_password_reset_email_async(user, code, purpose="reset"):
    # Sent in the background so response time does not reveal whether the
    # username exists; failures are logged rather than shown.
    def _worker():
        try:
            _send_password_reset_email(user, code, purpose)
        except Exception:
            logger.exception("Could not send password reset email to user id %s", user.pk)
            if settings.DEBUG:
                # Development aid only: lets the flow be tested while SMTP is misconfigured.
                logger.warning("DEBUG ONLY - password reset code for %s is %s", user.username, code)

    threading.Thread(target=_worker, daemon=True).start()


def _password_reset_candidate(username):
    return (
        User.objects.filter(username__iexact=username.strip(), is_active=True)
        .exclude(email="")
        .first()
    )


def _issue_password_reset_otp(request, username):
    """Rate-limits by IP + username (independent of whether the account exists),
    then emails a fresh code if it does. Returns ("sent"|"cooldown"|"limited", wait_seconds)."""
    key = f"pwreset:{_get_client_ip(request)}:{_username_key(username)}"
    now = time.time()
    last_sent = cache.get(f"{key}:last")
    if last_sent and now - last_sent < PASSWORD_RESET_RESEND_COOLDOWN_SECONDS:
        return "cooldown", math.ceil(PASSWORD_RESET_RESEND_COOLDOWN_SECONDS - (now - last_sent))
    sends = cache.get(f"{key}:count", 0)
    if sends >= PASSWORD_RESET_MAX_SENDS_PER_HOUR:
        return "limited", 0
    cache.set(f"{key}:last", now, 3600)
    cache.set(f"{key}:count", sends + 1, 3600)

    user = _password_reset_candidate(username)
    if user:
        user_key = f"pwreset-user:{user.pk}"
        user_sends = cache.get(user_key, 0)
        if user_sends < PASSWORD_RESET_MAX_SENDS_PER_USER_PER_HOUR:
            cache.set(user_key, user_sends + 1, 3600)
            code = f"{secrets.randbelow(1_000_000):06d}"
            PasswordResetOTP.objects.filter(user=user, purpose="reset").delete()
            PasswordResetOTP.objects.create(
                user=user,
                purpose="reset",
                code_hash=make_password(code),
                expires_at=timezone.now() + timezone.timedelta(seconds=PASSWORD_RESET_OTP_TTL_SECONDS),
            )
            _send_password_reset_email_async(user, code)
            _log_system_event(request, user, SystemLogType.ACTIVITY, "Password reset code requested.")
    return "sent", PASSWORD_RESET_RESEND_COOLDOWN_SECONDS


def _reset_state(request):
    return request.session.get(PASSWORD_RESET_SESSION_KEY)


def _resend_wait_seconds(request, username):
    key = f"pwreset:{_get_client_ip(request)}:{_username_key(username)}:last"
    last_sent = cache.get(key)
    if not last_sent:
        return 0
    return max(0, math.ceil(PASSWORD_RESET_RESEND_COOLDOWN_SECONDS - (time.time() - last_sent)))


def forgot_password_view(request):
    """Step 1: ask for the username and email a one-time code."""
    if request.user.is_authenticated:
        redirect_response = _redirect_authenticated_user(request.user)
        if redirect_response:
            return redirect_response

    if request.GET.get("restart"):
        request.session.pop(PASSWORD_RESET_SESSION_KEY, None)
        return redirect("forgot_password")

    form = ForgotPasswordUsernameForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"].strip()
        _issue_password_reset_otp(request, username)
        user = _password_reset_candidate(username)
        request.session[PASSWORD_RESET_SESSION_KEY] = {
            "username": username,
            "user_id": user.pk if user else None,
            "stage": "otp",
            "attempts": 0,
            "started": time.time(),
        }
        return redirect("forgot_password_verify")

    return render(request, "core/forgot_password.html", {"step": "request", "form": form, "page_title": "Forgot Password"})


def forgot_password_verify_view(request):
    """Step 2: check the emailed one-time code."""
    global _dummy_otp_hash

    if request.user.is_authenticated:
        redirect_response = _redirect_authenticated_user(request.user)
        if redirect_response:
            return redirect_response

    state = _reset_state(request)
    if not state or state.get("stage") not in ("otp", "reset"):
        return redirect("forgot_password")
    if state["stage"] == "reset":
        return redirect("forgot_password_reset")
    if time.time() - state.get("started", 0) > PASSWORD_RESET_OTP_TTL_SECONDS + 60:
        request.session.pop(PASSWORD_RESET_SESSION_KEY, None)
        messages.error(request, "Your verification session expired. Please start again.")
        return redirect("forgot_password")

    username = state["username"]
    notice = ""
    form = ForgotPasswordOTPForm()

    if request.method == "POST" and request.POST.get("action") == "resend":
        status, _ = _issue_password_reset_otp(request, username)
        user = _password_reset_candidate(username)
        state["user_id"] = user.pk if user else None
        if status == "sent":
            state["attempts"] = 0
            state["started"] = time.time()
            notice = "A new code has been sent if the account exists."
        elif status == "cooldown":
            notice = "Please wait before requesting another code."
        else:
            notice = "Too many code requests. Please try again later."
        request.session[PASSWORD_RESET_SESSION_KEY] = state
    elif request.method == "POST":
        form = ForgotPasswordOTPForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["code"]
            user_id = state.get("user_id")
            otp = None
            if user_id:
                otp = (
                    PasswordResetOTP.objects.filter(user_id=user_id, purpose="reset", used_at__isnull=True, verified_at__isnull=True)
                    .order_by("-created_at")
                    .first()
                )
            correct = False
            if otp:
                correct, too_many, attempts_used = _check_otp_code(otp, code)
            else:
                if _dummy_otp_hash is None:
                    _dummy_otp_hash = make_password("000000")
                check_password(code, _dummy_otp_hash)
                state["attempts"] = state.get("attempts", 0) + 1
                too_many = state["attempts"] >= PASSWORD_RESET_MAX_OTP_ATTEMPTS
                attempts_used = state["attempts"]

            if correct:
                otp.verified_at = timezone.now()
                otp.save(update_fields=["verified_at"])
                state.update({"stage": "reset", "otp_id": otp.pk})
                request.session[PASSWORD_RESET_SESSION_KEY] = state
                return redirect("forgot_password_reset")

            if too_many:
                if otp:
                    otp.delete()
                request.session.pop(PASSWORD_RESET_SESSION_KEY, None)
                messages.error(request, "Too many incorrect codes. Please start again.")
                return redirect("forgot_password")
            request.session[PASSWORD_RESET_SESSION_KEY] = state
            left = PASSWORD_RESET_MAX_OTP_ATTEMPTS - attempts_used
            form.add_error("code", f"That code is incorrect or has expired. {left} attempt{'s' if left != 1 else ''} left.")

    return render(request, "core/forgot_password.html", {
        "step": "verify",
        "form": form,
        "page_title": "Verify Code",
        "reset_username": username,
        "notice": notice,
        "resend_wait": _resend_wait_seconds(request, username),
        "otp_minutes": PASSWORD_RESET_OTP_TTL_SECONDS // 60,
    })


def forgot_password_reset_view(request):
    """Step 3: after the code is verified the user must choose a new password."""
    if request.user.is_authenticated:
        redirect_response = _redirect_authenticated_user(request.user)
        if redirect_response:
            return redirect_response

    state = _reset_state(request)
    if not state or state.get("stage") != "reset" or not state.get("user_id"):
        return redirect("forgot_password")

    otp = PasswordResetOTP.objects.filter(pk=state.get("otp_id"), user_id=state["user_id"]).first()
    verified_recently = bool(
        otp
        and otp.verified_at
        and not otp.used_at
        and (timezone.now() - otp.verified_at).total_seconds() <= PASSWORD_RESET_VERIFIED_WINDOW_SECONDS
    )
    user = User.objects.filter(pk=state["user_id"], is_active=True).first()
    if not verified_recently or not user:
        request.session.pop(PASSWORD_RESET_SESSION_KEY, None)
        messages.error(request, "Your verification expired. Please start again.")
        return redirect("forgot_password")

    form = ForgotPasswordResetForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user.set_password(form.cleaned_data["new_password"])
            user.save(update_fields=["password"])
            PasswordResetOTP.objects.filter(user=user).delete()
        request.session.pop(PASSWORD_RESET_SESSION_KEY, None)
        request.session.pop("login_ui", None)
        _log_system_event(request, user, SystemLogType.ACTIVITY, "Password was reset using an emailed verification code.")
        messages.success(request, "Your password has been reset. You can now log in with your new password.")
        return redirect("login")

    return render(request, "core/forgot_password.html", {
        "step": "reset",
        "form": form,
        "page_title": "Set New Password",
        "reset_username": state["username"],
    })


def logout_view(request):
    current_user = request.user if request.user.is_authenticated else None
    if current_user:
        role_label = "Super Admin" if current_user.is_superuser else (
            "Admin" if current_user.is_staff else (
                getattr(current_user, "registration_profile", None) and current_user.registration_profile.login_as
                or "User"
            )
        )
        _log_system_event(
            request,
            current_user,
            SystemLogType.LOGOUT,
            f"{role_label} logged out.",
        )
    logout(request)
    return redirect("login")


def check_registration_field_view(request):
    field = request.GET.get("field", "")
    value = request.GET.get("value", "").strip()

    if field not in ("email", "username"):
        return JsonResponse({"error": "Unsupported field."}, status=400)

    users = User.objects.filter(**{f"{field}__iexact": value})
    if request.GET.get("exclude_self") == "1" and request.user.is_authenticated and request.user.pk:
        users = users.exclude(pk=request.user.pk)
    invites = PendingUserInvite.objects.filter(**{f"{field}__iexact": value})
    available = bool(value) and not users.exists() and not invites.exists()

    return JsonResponse({"available": available})


def _apply_group_members(user, profile, member_formset, group_name):
    """Replace a student account's members with the (validated) formset and mirror
    the leader onto the User / profile. The caller saves user and profile."""
    members = [form.cleaned_data for form in member_formset.forms]
    # People who stay in the group keep their record, so the system still knows
    # which group listed a person first (see BaseMemberFormSet.clean).
    existing = list(GroupMember.objects.filter(user=user).order_by("pk"))
    rows = []
    for position, data in enumerate(members):
        person = (data["first_name"], data.get("middle_name", ""), data["last_name"])
        row = next(
            (m for m in existing if m not in rows and same_person(person, (m.first_name, m.middle_name, m.last_name))),
            None,
        ) or GroupMember(user=user)
        row.first_name, row.middle_name, row.last_name, row.position = person[0], person[1], person[2], position
        rows.append(row)
    GroupMember.objects.filter(user=user).exclude(pk__in=[row.pk for row in rows if row.pk]).delete()
    for row in rows:
        row.save()
    leader = members[0]
    user.first_name = leader["first_name"]
    user.last_name = leader["last_name"]
    profile.middle_name = leader.get("middle_name", "")
    profile.group_name = (group_name or "").strip()


def _form_alert(forms, member_formset=None):
    """Text for the error modal shown when a submitted form comes back with
    problems: the form-wide problems (e.g. a member already in another group),
    or a pointer to the fields marked in red."""
    problems, marked = [], False
    for form in forms:
        problems += [str(error) for error in form.non_field_errors()]
        marked = marked or any(name != NON_FIELD_ERRORS for name in form.errors)
    if member_formset is not None:
        problems += [str(error) for error in member_formset.non_form_errors()]
        marked = marked or any(member_formset.errors)
    if not problems:
        return "Please check the fields marked in red and try again."
    return " ".join(problems) + (" Please also check the fields marked in red." if marked else "")


REGISTERED_USERNAME_SESSION_KEY = "registered_username"


def register_view(request):
    form = RegistrationForm(request.POST or None)
    member_formset = build_member_formset(request.POST if request.method == "POST" else None)
    form_alert = ""

    if request.method == "POST":
        form_valid = form.is_valid()
        members_valid = member_formset.is_valid()
        if form_valid and members_valid:
            with transaction.atomic():
                # The account can't log in until an Admin or Super Admin approves it.
                user = User.objects.create_user(
                    username=form.cleaned_data["username"],
                    email=form.cleaned_data["email"],
                    password=form.cleaned_data["password"],
                    is_active=False,
                )
                profile = RegistrationProfile(
                    user=user,
                    login_as=LoginAs.STUDENT,
                    program=form.cleaned_data["program"],
                    college=form.cleaned_data["college"],
                    approval_status=RegistrationStatus.PENDING,
                )
                _apply_group_members(user, profile, member_formset, form.cleaned_data.get("group_name", ""))
                user.save(update_fields=["first_name", "last_name"])
                profile.save()
            _log_system_event(
                request,
                user,
                SystemLogType.ACTIVITY,
                f"New student group registered and is waiting for approval: {account_display_name(user)} "
                f"({len(member_formset.forms)} member(s), program: {form.cleaned_data['program']}).",
            )
            notify(
                staff_with_module(AdminModule.MANAGE_USERS),
                NotificationCategory.ACCOUNT,
                "New registration to approve",
                f"{account_display_name(user)} registered ({form.cleaned_data['program']}) and is waiting for approval.",
                "admin_registration_requests",
            )
            # Post/Redirect/Get: reloading the page can't register the group twice.
            request.session[REGISTERED_USERNAME_SESSION_KEY] = {"username": user.username, "email": user.email}
            return redirect("register")
        form_alert = _form_alert([form], member_formset)

    registered = request.session.pop(REGISTERED_USERNAME_SESSION_KEY, None) if request.method == "GET" else None
    registered = registered if isinstance(registered, dict) else None
    context = {
        "form": form,
        "member_formset": member_formset,
        "max_group_members": MAX_GROUP_MEMBERS,
        "form_submitted": bool(registered),
        "registered_username": registered["username"] if registered else "",
        "registered_email": registered["email"] if registered else "",
        "registration_message": (
            f"Your registration ({registered['username']}) was sent and is now waiting for approval "
            "by an Admin or Super Admin. You can't log in yet. "
            f"We will email {registered['email']} as soon as it is approved."
        ) if registered else "",
        "form_alert": form_alert,
        "page_title": "Register",
    }
    return render(request, "core/register.html", context)


@login_required(login_url="login")
def student_dashboard(request):
    if not _profile_is_complete(request.user):
        return redirect("complete_profile")
    profile = getattr(request.user, "registration_profile", None)
    actual_dashboard = _dashboard_name_for_user(request.user)
    if actual_dashboard and actual_dashboard != "student_dashboard":
        return redirect(actual_dashboard)

    student_submissions = ResearchSubmission.objects.filter(student=request.user)

    # The dashboard's search bar searches the FULL shared repository (every
    # ResearchPaper plus every approved ResearchSubmission, from any student)
    # -- same engine as Repository Search, reused here rather than duplicated.
    search_query = request.GET.get("q", "").strip()
    category_id = request.GET.get("category", "").strip()
    published_year = request.GET.get("published_year", "").strip()

    paper_qs = ResearchPaper.objects.select_related("food_category")
    submission_qs = ResearchSubmission.objects.select_related("food_category", "student").filter(
        status=ResearchSubmissionStatus.APPROVED
    )

    if search_query:
        text_filter = _repository_text_filter(search_query)
        paper_qs = paper_qs.filter(text_filter)
        submission_qs = submission_qs.filter(text_filter)

    if category_id.isdigit():
        paper_qs = paper_qs.filter(food_category_id=category_id)
        submission_qs = submission_qs.filter(food_category_id=category_id)

    if published_year.isdigit():
        paper_qs = paper_qs.filter(published_year=int(published_year))
        submission_qs = submission_qs.filter(published_year=int(published_year))

    rows = [_repository_search_row_from_paper(paper) for paper in paper_qs]
    rows += [_repository_search_row_from_submission(sub, request.user) for sub in submission_qs]
    rows = _dedupe_repository_search_rows(rows)
    rows = _sort_repository_search_rows(rows, search_query)

    paginator = Paginator(rows, REPOSITORY_SEARCH_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "page_title": "Student Dashboard",
        "search_query": search_query,
        "category_id": category_id,
        "published_year": published_year,
        "categories": FoodCategory.objects.filter(parent__isnull=True),
        "published_years": _repository_search_published_years(),
        "search_suggestions": _repository_search_suggestions(),
        "page_obj": page_obj,
        "results": page_obj,
        "stats": {
            "total_submissions": student_submissions.count(),
            "completed": student_submissions.filter(status=ResearchSubmissionStatus.APPROVED).count(),
            "pending": student_submissions.filter(status=ResearchSubmissionStatus.PENDING).count(),
        },
        "student_name": account_display_name(request.user),
        "student_role": profile.login_as if profile else "Student",
    }
    return render(request, "core/student_dashboard.html", context)


DASHBOARD_RANGES = (
    (7, "Last 7 days"),
    (30, "Last 30 days"),
    (90, "Last 90 days"),
    (365, "Last 12 months"),
)
DASHBOARD_DEFAULT_RANGE = 30
DASHBOARD_RECENT_ROWS = 6
DASHBOARD_TOP_CATEGORIES = 5
DASHBOARD_TREND_MONTHS = 12
DASHBOARD_STORAGE_CACHE_SECONDS = 600


def _media_storage_bytes():
    """Total size of uploaded files, cached because it walks the media folder."""
    cached = cache.get("dashboard_media_bytes")
    if cached is not None:
        return cached
    total = 0
    for root, _dirs, files in os.walk(settings.MEDIA_ROOT):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    cache.set("dashboard_media_bytes", total, DASHBOARD_STORAGE_CACHE_SECONDS)
    return total


def _format_bytes(size):
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _plural_days(days):
    return f"{days} day" if days == 1 else f"{days} days"


def _dashboard_monthly_series(submissions, months):
    """Submitted vs approved research per month for the last `months` months."""
    today = timezone.localdate()
    month_keys = []
    year, month = today.year, today.month
    for _ in range(months):
        month_keys.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    month_keys.reverse()
    window_start = timezone.make_aware(datetime(month_keys[0][0], month_keys[0][1], 1))

    def per_month(queryset, field):
        rows = (
            queryset.filter(**{f"{field}__gte": window_start})
            .annotate(month=TruncMonth(field))
            .values_list("month")
            .annotate(n=Count("id"))
        )
        by_month = {(m.year, m.month): n for m, n in rows if m}
        return [by_month.get(key, 0) for key in month_keys]

    return {
        "labels": [date(y, m, 1).strftime("%b %Y") for y, m in month_keys],
        "submitted": per_month(submissions, "submitted_at"),
        "approved": per_month(submissions.filter(status=ResearchSubmissionStatus.APPROVED), "reviewed_at"),
    }


@login_required(login_url="login")
def admin_dashboard(request):
    redirect_response = _admin_only_or_redirect(request)
    if redirect_response:
        return redirect_response

    user = request.user
    is_super_admin = user.is_superuser
    now = timezone.now()

    try:
        range_days = int(request.GET.get("range", DASHBOARD_DEFAULT_RANGE))
    except (TypeError, ValueError):
        range_days = DASHBOARD_DEFAULT_RANGE
    if range_days not in dict(DASHBOARD_RANGES):
        range_days = DASHBOARD_DEFAULT_RANGE
    range_start = now - timezone.timedelta(days=range_days)
    range_label = dict(DASHBOARD_RANGES)[range_days]

    # Links only point at modules this account may open.
    can = {module.value: _admin_has_module(user, module) for module in AdminModule}

    # Staff Admins never see Super Admin accounts, logs or submissions.
    users = User.objects.all() if is_super_admin else User.objects.filter(is_superuser=False)
    # Registrations waiting for approval aren't users yet; they're counted on their own.
    registration_requests_count = users.filter(registration_profile__approval_status=RegistrationStatus.PENDING).count()
    users = users.exclude(registration_profile__approval_status=RegistrationStatus.PENDING)
    submissions = ResearchSubmission.objects.all()
    logs = SystemLog.objects.select_related("user")
    if not is_super_admin:
        submissions = submissions.exclude(student__is_superuser=True)
        logs = logs.filter(user__isnull=False, user__is_superuser=False)

    # --- KPI cards ---
    pending_qs = submissions.filter(status=ResearchSubmissionStatus.PENDING)
    pending_count = pending_qs.count()
    oldest_pending = pending_qs.order_by("submitted_at").values_list("submitted_at", flat=True).first()
    oldest_wait_days = (now - oldest_pending).days if oldest_pending else None
    oldest_wait_note = f"Oldest waiting {_plural_days(oldest_wait_days)}" if oldest_wait_days is not None else ""

    # Same de-duplicated list as the Reports page, so "added" can never exceed the total.
    repository_rows = _all_repository_rows(user)
    repository_added = sum(1 for row in repository_rows if row["added_sort"] and row["added_sort"] >= range_start)

    checks_in_range = SimilarityCheckRecord.objects.filter(checked_at__gte=range_start)
    level_counts = dict(checks_in_range.values_list("similarity_level").annotate(n=Count("id")))
    checks_total = sum(level_counts.values())
    high_checks = level_counts.get("high", 0)

    kpis = [
        {
            "key": "users",
            "label": "Total Users",
            "value": users.count(),
            "delta": users.filter(date_joined__gte=range_start).count(),
            "delta_label": "new",
            "url": reverse("admin_manage_users") if can["manage_users"] else "",
        },
        {
            "key": "repository",
            "label": "Research Repository",
            "value": len(repository_rows),
            "delta": repository_added,
            "delta_label": "added",
            "url": reverse("admin_repository_add") if can["research_repository"] else "",
        },
        {
            "key": "pending",
            "label": "Awaiting Review",
            "value": pending_count,
            "note": oldest_wait_note or "All caught up",
            "warn": bool(oldest_wait_days and oldest_wait_days >= 7),
            "url": reverse("admin_manage_submissions") if can["manage_submissions"] else "",
        },
        {
            "key": "checks",
            "label": "Similarity Checks",
            "value": checks_total,
            "note": f"{round(high_checks * 100 / checks_total)}% high similarity" if checks_total else "None in this period",
            "url": reverse("admin_similarity_records") if can["similarity_records"] else "",
        },
    ]

    # --- Needs your attention ---
    failed_signins = logs.filter(
        log_type=SystemLogType.LOGIN,
        action__startswith=FAILED_SIGNIN_LOG_PREFIX,
        created_at__gte=now - timezone.timedelta(hours=24),
    ).count()
    attention = []
    if is_super_admin:
        attention.append({
            "label": "Account deletion requests",
            "detail": "Waiting for your decision",
            "count": UserDeletionRequest.objects.filter(status=DeletionRequestStatus.PENDING).count(),
            "url": reverse("admin_deletion_requests"),
            "tone": "critical",
        })
    attention += [
        {
            "label": "Registration requests",
            "detail": "Groups waiting for approval",
            "count": registration_requests_count,
            "url": reverse("admin_registration_requests") if can["manage_users"] else "",
            "tone": "warning",
        },
        {
            "label": "Submissions awaiting review",
            "detail": oldest_wait_note or "Nothing waiting",
            "count": pending_count,
            "url": reverse("admin_manage_submissions") if can["manage_submissions"] else "",
            "tone": "warning",
        },
        {
            "label": "Failed sign-in attempts",
            "detail": "In the last 24 hours",
            "count": failed_signins,
            "url": reverse("admin_system_logs") + "?type=login&q=Failed+sign-in" if can["system_logs"] else "",
            "tone": "critical",
        },
        {
            "label": "High-similarity checks",
            "detail": range_label,
            "count": high_checks,
            "url": reverse("admin_similarity_records") if can["similarity_records"] else "",
            "tone": "warning",
        },
        {
            "label": "Deactivated accounts",
            "detail": "Cannot sign in",
            "count": users.filter(is_active=False).count(),
            "url": reverse("admin_manage_users") if can["manage_users"] else "",
            "tone": "neutral",
        },
    ]
    attention_open = sum(1 for item in attention if item["count"] and item["tone"] != "neutral")

    # --- Similarity results, categories, users ---
    similarity_breakdown = [
        {"key": "low", "label": "Low", "range": SIMILARITY_RANGES["low"], "count": level_counts.get("low", 0)},
        {"key": "moderate", "label": "Moderate", "range": SIMILARITY_RANGES["moderate"], "count": level_counts.get("moderate", 0)},
        {"key": "high", "label": "High", "range": SIMILARITY_RANGES["high"], "count": high_checks},
    ]
    for row in similarity_breakdown:
        row["pct"] = round(row["count"] * 100 / checks_total) if checks_total else 0

    category_totals = {}
    for row in repository_rows:
        name = row["category"].name if row["category"] else "Uncategorized"
        category_totals[name] = category_totals.get(name, 0) + 1
    ranked = sorted(category_totals.items(), key=lambda item: (-item[1], item[0]))[:DASHBOARD_TOP_CATEGORIES]
    top_max = ranked[0][1] if ranked else 0
    top_categories = [{"label": name, "count": n, "pct": round(n * 100 / top_max)} for name, n in ranked]

    user_breakdown = [
        {"label": "Students", "count": users.filter(is_staff=False, is_superuser=False).count()},
        {"label": "Admins", "count": users.filter(is_staff=True, is_superuser=False).count()},
    ]
    if is_super_admin:
        user_breakdown.append({"label": "Super Admins", "count": users.filter(is_superuser=True).count()})
    user_total = sum(row["count"] for row in user_breakdown)
    for row in user_breakdown:
        row["pct"] = round(row["count"] * 100 / user_total) if user_total else 0

    # --- Recent activity and submissions ---
    recent_activity = [
        {
            "time": timezone.localtime(log.created_at),
            "user_name": log.user_display_name(),
            "user_role": log.user_role_label(),
            "log_type": log.log_type,
            "failed": log.action.startswith(FAILED_SIGNIN_LOG_PREFIX),
            "action": log.action,
        }
        for log in logs.order_by("-created_at")[:DASHBOARD_RECENT_ROWS]
    ]
    recent_submissions = [
        {
            "title": submission.title,
            "submitted_by": account_display_name(submission.student),
            "status": submission.status,
            "date": timezone.localtime(submission.submitted_at) if submission.submitted_at else None,
        }
        for submission in submissions.select_related("student").order_by("-submitted_at")[:DASHBOARD_RECENT_ROWS]
    ]

    # --- System health (Super Admin only) ---
    system_health = []
    if is_super_admin:
        try:
            User.objects.exists()
            database_ok = True
        except Exception:
            database_ok = False
        email_ok = "smtp" in settings.EMAIL_BACKEND and bool(getattr(settings, "EMAIL_HOST_USER", ""))
        system_health = [
            {"label": "Database", "value": "Connected" if database_ok else "Unavailable", "ok": database_ok},
            {"label": "Email delivery", "value": "SMTP configured" if email_ok else "Not sent (console only)", "ok": email_ok},
            {"label": "Server mode", "value": "Debug (development)" if settings.DEBUG else "Production", "ok": not settings.DEBUG},
            {"label": "Uploaded files", "value": _format_bytes(_media_storage_bytes()), "ok": True},
        ]

    context = {
        "page_title": "Super Admin Dashboard" if is_super_admin else "Admin Dashboard",
        "is_super_admin": is_super_admin,
        "admin_name": user.get_full_name().strip() or user.username,
        "admin_first_name": user.first_name.strip() or user.username,
        "admin_role": "Super Admin" if is_super_admin else "Admin",
        "today": timezone.localdate(),
        "range_days": range_days,
        "range_label": range_label,
        "range_choices": DASHBOARD_RANGES,
        "can": can,
        "kpis": kpis,
        "attention": attention,
        "attention_open": attention_open,
        "similarity_breakdown": similarity_breakdown,
        "checks_total": checks_total,
        "top_categories": top_categories,
        "user_breakdown": user_breakdown,
        "user_total": user_total,
        "recent_activity": recent_activity,
        "recent_submissions": recent_submissions,
        "system_health": system_health,
        "trend_months": DASHBOARD_TREND_MONTHS,
        "chart_data": {"trend": _dashboard_monthly_series(submissions, DASHBOARD_TREND_MONTHS)},
    }
    return render(request, "core/admin_dashboard.html", context)


def _complete_profile_for_pending_invite(request, invite_id):
    invite = PendingUserInvite.objects.filter(pk=invite_id).first()
    if not invite:
        request.session.pop("pending_invite_id", None)
        return redirect("login")

    is_student_role = invite.login_as == PendingUserInviteRole.STUDENT

    form = ProfileCompletionForm(
        request.POST or None,
        require_student_fields=is_student_role,
    )
    member_formset = None
    if is_student_role:
        member_formset = build_member_formset(request.POST if request.method == "POST" else None)

    form_valid = form.is_valid() if request.method == "POST" else False
    members_valid = member_formset.is_valid() if (member_formset is not None and request.method == "POST") else True
    if request.method == "POST" and form_valid and members_valid:
        with transaction.atomic():
            is_admin_role = invite.login_as == PendingUserInviteRole.ADMIN
            is_super_admin_role = invite.login_as == PendingUserInviteRole.SUPER_ADMIN
            user = User.objects.create_user(
                username=invite.username,
                email=invite.email,
                password=form.cleaned_data["new_password"],
                first_name="" if is_student_role else form.cleaned_data["first_name"].strip(),
                last_name="" if is_student_role else form.cleaned_data["last_name"].strip(),
                is_staff=is_admin_role or is_super_admin_role,
                is_superuser=is_super_admin_role,
            )
            profile = RegistrationProfile(
                user=user,
                middle_name="" if is_student_role else form.cleaned_data["middle_name"].strip(),
                login_as=LoginAs.STUDENT,
                program=form.cleaned_data["program"] if is_student_role else "",
                college=form.cleaned_data["college"] if is_student_role else "",
            )
            if is_student_role:
                _apply_group_members(user, profile, member_formset, form.cleaned_data.get("group_name", ""))
                user.save(update_fields=["first_name", "last_name"])
            profile.save()
            invite.delete()

        request.session.pop("pending_invite_id", None)
        user.backend = "django.contrib.auth.backends.ModelBackend"
        login(request, user)
        _log_system_event(
            request,
            user,
            SystemLogType.ACTIVITY,
            f"{invite.login_as} account created and onboarding completed from a pending invite.",
        )
        redirect_response = _redirect_authenticated_user(user)
        if redirect_response:
            return redirect_response
        return redirect("home")

    role_display = {
        PendingUserInviteRole.STUDENT: "Student",
        PendingUserInviteRole.ADMIN: "Staff Admin",
        PendingUserInviteRole.SUPER_ADMIN: "Super Admin",
    }.get(invite.login_as, "User")

    context = {
        "page_title": "Complete Your Profile",
        "form": form,
        "form_submitted": False,
        "form_alert": _form_alert([form], member_formset) if request.method == "POST" else "",
        "is_student_role": is_student_role,
        "role_display": role_display,
        "user_name": invite.username,
        "user_email": invite.email,
        "member_formset": member_formset,
        "max_group_members": MAX_GROUP_MEMBERS,
    }
    return render(request, "core/complete_profile.html", context)


INVITE_TEMP_PASSWORD_LENGTH = 8
# No look-alike characters (0/O, 1/l/I) so the emailed password is easy to type.
_TEMP_PASSWORD_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_TEMP_PASSWORD_LOWER = "abcdefghijkmnopqrstuvwxyz"
_TEMP_PASSWORD_DIGITS = "23456789"


def _generate_temp_password():
    """8 random characters containing at least one uppercase letter, lowercase letter and digit."""
    pool = _TEMP_PASSWORD_UPPER + _TEMP_PASSWORD_LOWER + _TEMP_PASSWORD_DIGITS
    chars = [
        secrets.choice(_TEMP_PASSWORD_UPPER),
        secrets.choice(_TEMP_PASSWORD_LOWER),
        secrets.choice(_TEMP_PASSWORD_DIGITS),
    ] + [secrets.choice(pool) for _ in range(INVITE_TEMP_PASSWORD_LENGTH - 3)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _send_invite_credentials_email(request, username, email, role, temp_password):
    """Emails the username and temporary password straight to the invited person.
    Raises on failure so the caller can roll the invite back (the admin never sees the password)."""
    login_url = request.build_absolute_uri(reverse("login"))
    minutes_note = "You will be asked to complete your profile and choose a new password the first time you log in."
    text_body = (
        "Hello,\n\n"
        f"An administrator created a Food Match {role} account for you.\n\n"
        f"Username: {username}\n"
        f"Temporary password: {temp_password}\n\n"
        f"Log in here: {login_url}\n\n"
        f"{minutes_note}\n"
        "Keep this email private and do not share your temporary password.\n"
    )
    html_body = (
        "<p>Hello,</p>"
        f"<p>An administrator created a Food Match <strong>{role}</strong> account for you.</p>"
        f"<p>Username: <strong>{username}</strong><br>"
        f'Temporary password: <strong style="font-size:18px;letter-spacing:2px;">{temp_password}</strong></p>'
        f'<p><a href="{login_url}">Log in to Food Match</a></p>'
        f"<p>{minutes_note}</p>"
        "<p>Keep this email private and do not share your temporary password.</p>"
    )
    message = EmailMultiAlternatives("Your Food Match account details", text_body, to=[email])
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)


PASSWORD_CHANGE_SESSION_KEY = "pw_change"
PASSWORD_CHANGE_MAX_CURRENT_PASSWORD_FAILS = 5
PASSWORD_CHANGE_STATE_LIFETIME_SECONDS = 30 * 60


def _check_otp_code(otp, code):
    """Counts the attempt and compares the code. Returns (correct, too_many, attempts_used)."""
    otp.attempts += 1
    otp.save(update_fields=["attempts"])
    correct = check_password(code, otp.code_hash) and otp.expires_at > timezone.now()
    return correct, otp.attempts >= PASSWORD_RESET_MAX_OTP_ATTEMPTS, otp.attempts


def _mask_email(email):
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"


def _verify_current_password(user, raw_password):
    """Checks a logged-in user's current password, capping wrong guesses. Returns "ok"|"wrong"|"locked"."""
    key = f"pwcheck:{user.pk}"
    fails = cache.get(key, 0)
    if fails >= PASSWORD_CHANGE_MAX_CURRENT_PASSWORD_FAILS:
        return "locked"
    if verify_user_password(user, raw_password):
        cache.delete(key)
        return "ok"
    cache.set(key, fails + 1, PASSWORD_RESET_VERIFIED_WINDOW_SECONDS)
    return "wrong"


def _change_otp_wait_seconds(user):
    last_sent = cache.get(f"pwchange:{user.pk}:last")
    if not last_sent:
        return 0
    return max(0, math.ceil(PASSWORD_RESET_RESEND_COOLDOWN_SECONDS - (time.time() - last_sent)))


def _issue_change_password_otp(request, user):
    """Emails a fresh password-change code. Returns ("sent"|"cooldown"|"limited", otp_or_None)."""
    key = f"pwchange:{user.pk}"
    now = time.time()
    if _change_otp_wait_seconds(user):
        return "cooldown", None
    sends = cache.get(f"{key}:count", 0)
    if sends >= PASSWORD_RESET_MAX_SENDS_PER_HOUR:
        return "limited", None
    cache.set(f"{key}:last", now, 3600)
    cache.set(f"{key}:count", sends + 1, 3600)

    code = f"{secrets.randbelow(1_000_000):06d}"
    PasswordResetOTP.objects.filter(user=user, purpose="change").delete()
    otp = PasswordResetOTP.objects.create(
        user=user,
        purpose="change",
        code_hash=make_password(code),
        expires_at=timezone.now() + timezone.timedelta(seconds=PASSWORD_RESET_OTP_TTL_SECONDS),
    )
    _send_password_reset_email_async(user, code, "change")
    _log_system_event(request, user, SystemLogType.ACTIVITY, "Password change verification code requested.")
    return "sent", otp


def _send_password_changed_alert_async(user):
    def _worker():
        try:
            when = timezone.localtime().strftime("%B %d, %Y %I:%M %p") + " (Philippine time)"
            name = user.get_full_name().strip() or user.username
            message = EmailMultiAlternatives(
                "Your Food Match password was changed",
                (
                    f"Hello {name},\n\nThe password for your Food Match account ({user.username}) "
                    f"was changed on {when}.\n\nIf this was you, no action is needed. If it was not you, "
                    "reset your password right away using Forgot Password on the login page and tell an administrator.\n"
                ),
                to=[user.email],
            )
            message.send(fail_silently=False)
        except Exception:
            logger.exception("Could not send password-changed alert to user id %s", user.pk)

    if user.email:
        threading.Thread(target=_worker, daemon=True).start()


def _portal_role_for(user):
    if user.is_superuser:
        return "super_admin"
    if user.is_staff:
        return "admin"
    return "student"


def _account_page_context(user, page_mode, profile_form=None, request=None):
    portal_role = _portal_role_for(user)
    role_display = {"super_admin": "Super Admin", "admin": "Admin", "student": "Student"}[portal_role]
    is_virtual = is_emergency_user(user)
    context = {
        "page_mode": page_mode,
        "page_title": "My Profile" if page_mode == "profile" else "Change Password",
        "portal_role": portal_role,
        "is_super_admin_portal": portal_role == "super_admin",
        "role_display": role_display,
        "is_student": portal_role == "student",
        "is_virtual_account": is_virtual,
        "display_name": "Emergency Super Admin" if is_virtual else account_display_name(user),
        "group_members": [] if is_virtual else group_member_names(user),
        "account_username": user.username,
        "profile_form": profile_form,
    }
    if not is_virtual:
        context["original_email"] = user.email or ""
        context["date_joined"] = timezone.localtime(user.date_joined).strftime("%B %d, %Y")
        context["last_login"] = timezone.localtime(user.last_login).strftime("%b %d, %Y %I:%M %p") if user.last_login else "Never"
    if request is not None:
        # Outcome of the last action (after a redirect), shown as a modal.
        context["alert_message"], context["alert_error"] = _pop_result_messages(request)
        if context["alert_message"]:
            context["alert_title"] = "Profile Updated" if page_mode == "profile" else "Password Changed"
    return context


@login_required(login_url="login")
def profile_view(request):
    user = request.user

    if is_emergency_user(user):
        # Virtual break-glass account: no database row, so nothing to edit.
        return render(request, "core/profile.html", _account_page_context(user, "profile", request=request))

    if not _profile_is_complete(user):
        return redirect("complete_profile")

    context = _account_page_context(user, "profile", request=request)
    role_display = context["role_display"]
    is_student = context["is_student"]
    profile = getattr(user, "registration_profile", None)
    initial = {
        "first_name": user.first_name,
        "middle_name": profile.middle_name if profile else "",
        "last_name": user.last_name,
        "email": user.email,
        "program": profile.program if profile and is_student else "",
        "college": profile.college if profile and is_student else "",
        "group_name": profile.group_name if profile and is_student else "",
    }
    profile_form = ProfileUpdateForm(initial=initial, user=user, require_student_fields=is_student)
    member_formset = build_member_formset(None, user) if is_student else None

    if request.method == "POST":
        profile_form = ProfileUpdateForm(request.POST, user=user, require_student_fields=is_student)
        if is_student:
            member_formset = build_member_formset(request.POST, user)
        members_valid = member_formset.is_valid() if member_formset is not None else True
        if profile_form.is_valid():
            data = profile_form.cleaned_data
            if data["email"].lower() != (user.email or "").lower():
                check = _verify_current_password(user, data.get("current_password", ""))
                if check == "locked":
                    profile_form.add_error("current_password", "Too many incorrect attempts. Please try again later.")
                elif check == "wrong":
                    profile_form.add_error("current_password", "Your current password is incorrect.")
        if profile_form.is_valid() and members_valid:
            with transaction.atomic():
                if profile is None:
                    profile = RegistrationProfile(user=user, login_as=LoginAs.STUDENT)
                if is_student:
                    _apply_group_members(user, profile, member_formset, data.get("group_name", ""))
                    profile.program = data["program"]
                    profile.college = data["college"]
                else:
                    user.first_name = data["first_name"]
                    user.last_name = data["last_name"]
                    profile.middle_name = data["middle_name"]
                user.email = data["email"]
                user.save(update_fields=["first_name", "last_name", "email"])
                profile.save()
            _log_system_event(
                request, user, SystemLogType.ACTIVITY, f"{role_display} updated their profile information."
            )
            messages.success(request, "Your profile has been updated.")
            return redirect("profile")
        context["alert_error"] = _form_alert([profile_form], member_formset)
        context["alert_title"] = "Profile not updated"

    context["profile_form"] = profile_form
    context["member_formset"] = member_formset
    context["max_group_members"] = MAX_GROUP_MEMBERS
    return render(request, "core/profile.html", context)


@login_required(login_url="login")
def change_password_view(request):
    """Change password with step-up verification: current password -> emailed code -> new password."""
    user = request.user

    if is_emergency_user(user):
        return render(request, "core/profile.html", _account_page_context(user, "password", request=request))

    if not _profile_is_complete(user):
        return redirect("complete_profile")

    context = _account_page_context(user, "password", request=request)
    role_display = context["role_display"]

    if not user.email:
        context["change_step"] = "no_email"
        return render(request, "core/profile.html", context)

    if request.method == "POST" and request.POST.get("action") == "cancel":
        request.session.pop(PASSWORD_CHANGE_SESSION_KEY, None)
        return redirect("change_password")

    state = request.session.get(PASSWORD_CHANGE_SESSION_KEY)
    otp = None
    if state:
        otp = PasswordResetOTP.objects.filter(
            pk=state.get("otp_id"), user=user, purpose="change", used_at__isnull=True
        ).first()
        if not otp or time.time() - state.get("started", 0) > PASSWORD_CHANGE_STATE_LIFETIME_SECONDS:
            request.session.pop(PASSWORD_CHANGE_SESSION_KEY, None)
            state = None
            otp = None
            messages.error(request, "Your verification session expired. Please start again.")
            return redirect("change_password")

    # ---- Step 1: verify identity (current password) and email a code ----
    if not state:
        form = ChangePasswordVerifyForm(request.POST if request.method == "POST" else None)
        if request.method == "POST" and form.is_valid():
            check = _verify_current_password(user, form.cleaned_data["current_password"])
            if check == "locked":
                form.add_error("current_password", "Too many incorrect attempts. Please try again in 15 minutes.")
            elif check == "wrong":
                form.add_error("current_password", "Your current password is incorrect.")
            else:
                status, new_otp = _issue_change_password_otp(request, user)
                if status == "cooldown":
                    new_otp = (
                        PasswordResetOTP.objects.filter(user=user, purpose="change", used_at__isnull=True)
                        .order_by("-created_at")
                        .first()
                    )
                if new_otp:
                    request.session[PASSWORD_CHANGE_SESSION_KEY] = {
                        "stage": "otp",
                        "otp_id": new_otp.pk,
                        "started": time.time(),
                    }
                    return redirect("change_password")
                form.add_error(None, "Too many code requests. Please try again later.")
        context.update({"change_step": "verify", "verify_form": form, "masked_email": _mask_email(user.email)})
        return render(request, "core/profile.html", context)

    # ---- Step 2: enter the emailed code ----
    if state["stage"] == "otp":
        form = ForgotPasswordOTPForm()
        notice = ""
        if request.method == "POST" and request.POST.get("action") == "resend":
            status, new_otp = _issue_change_password_otp(request, user)
            if status == "sent":
                state["otp_id"] = new_otp.pk
                request.session[PASSWORD_CHANGE_SESSION_KEY] = state
                notice = "A new code has been sent to your email."
            elif status == "cooldown":
                notice = "Please wait before requesting another code."
            else:
                notice = "Too many code requests. Please try again later."
        elif request.method == "POST":
            form = ForgotPasswordOTPForm(request.POST)
            if form.is_valid():
                correct, too_many, attempts_used = _check_otp_code(otp, form.cleaned_data["code"])
                if correct:
                    otp.verified_at = timezone.now()
                    otp.save(update_fields=["verified_at"])
                    state["stage"] = "new"
                    request.session[PASSWORD_CHANGE_SESSION_KEY] = state
                    return redirect("change_password")
                if too_many:
                    otp.delete()
                    request.session.pop(PASSWORD_CHANGE_SESSION_KEY, None)
                    messages.error(request, "Too many incorrect codes. Please start again.")
                    return redirect("change_password")
                left = PASSWORD_RESET_MAX_OTP_ATTEMPTS - attempts_used
                form.add_error("code", f"That code is incorrect or has expired. {left} attempt{'s' if left != 1 else ''} left.")
        context.update({
            "change_step": "otp",
            "otp_form": form,
            "notice": notice,
            "masked_email": _mask_email(user.email),
            "resend_wait": _change_otp_wait_seconds(user),
            "otp_minutes": PASSWORD_RESET_OTP_TTL_SECONDS // 60,
        })
        return render(request, "core/profile.html", context)

    # ---- Step 3: choose the new password ----
    verified_recently = bool(
        otp.verified_at
        and (timezone.now() - otp.verified_at).total_seconds() <= PASSWORD_RESET_VERIFIED_WINDOW_SECONDS
    )
    if state["stage"] != "new" or not verified_recently:
        request.session.pop(PASSWORD_CHANGE_SESSION_KEY, None)
        messages.error(request, "Your verification expired. Please start again.")
        return redirect("change_password")

    form = ChangePasswordNewForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user.set_password(form.cleaned_data["new_password"])
            user.save(update_fields=["password"])
            PasswordResetOTP.objects.filter(user=user).delete()
        update_session_auth_hash(request, user)  # keep this device signed in; other sessions are signed out
        request.session.pop(PASSWORD_CHANGE_SESSION_KEY, None)
        cache.delete(f"pwcheck:{user.pk}")
        _log_system_event(request, user, SystemLogType.ACTIVITY, f"{role_display} changed their password (email code verified).")
        _send_password_changed_alert_async(user)
        messages.success(request, "Your password has been changed. Your other devices were signed out.")
        return redirect("change_password")

    context.update({"change_step": "new", "new_form": form})
    return render(request, "core/profile.html", context)


def complete_profile_view(request):
    if not request.user.is_authenticated:
        pending_invite_id = request.session.get("pending_invite_id")
        if pending_invite_id:
            return _complete_profile_for_pending_invite(request, pending_invite_id)
        return redirect("login")

    if _profile_is_complete(request.user):
        redirect_response = _redirect_authenticated_user(request.user)
        if redirect_response:
            return redirect_response
        return redirect("home")

    role = _effective_login_role_for_profile(request.user)
    is_student_role = role == LoginAs.STUDENT
    profile = getattr(request.user, "registration_profile", None)

    initial = {}
    if profile:
        initial = {
            "first_name": request.user.first_name,
            "middle_name": profile.middle_name,
            "last_name": request.user.last_name,
            "program": profile.program if is_student_role else "",
            "college": profile.college if is_student_role else "",
        }
    else:
        initial = {
            "first_name": request.user.first_name,
            "middle_name": "",
            "last_name": request.user.last_name,
            "program": "",
            "college": "",
        }

    initial["group_name"] = profile.group_name if profile else ""
    form = ProfileCompletionForm(
        request.POST or None,
        require_student_fields=is_student_role,
        initial=initial,
    )
    member_formset = None
    if is_student_role:
        member_formset = build_member_formset(request.POST if request.method == "POST" else None, request.user)
    form_submitted = False
    password_was_changed = False

    form_valid = form.is_valid() if request.method == "POST" else False
    members_valid = member_formset.is_valid() if (member_formset is not None and request.method == "POST") else True
    if request.method == "POST" and form_valid and members_valid:
        new_password = form.cleaned_data.get("new_password")
        with transaction.atomic():
            if profile is None:
                profile = RegistrationProfile(user=request.user, login_as=LoginAs.STUDENT)
            if is_student_role:
                _apply_group_members(request.user, profile, member_formset, form.cleaned_data.get("group_name", ""))
                profile.program = form.cleaned_data["program"]
                profile.college = form.cleaned_data["college"]
            else:
                request.user.first_name = form.cleaned_data["first_name"].strip()
                request.user.last_name = form.cleaned_data["last_name"].strip()
                profile.middle_name = form.cleaned_data["middle_name"].strip()

            if new_password:
                request.user.set_password(new_password)
                password_was_changed = True

            request.user.save()
            profile.save()

        if password_was_changed:
            update_session_auth_hash(request, request.user)

        form_submitted = True
        role_label = role or "User"
        pw_note = " Password was updated from temporary to permanent." if password_was_changed else ""
        _log_system_event(
            request,
            request.user,
            SystemLogType.ACTIVITY,
            f"{role_label} completed their onboarding profile.{pw_note}",
        )
        redirect_response = _redirect_authenticated_user(request.user)
        if redirect_response:
            return redirect_response
        return redirect("home")

    role_display = {
        LoginAs.STUDENT: "Student",
        "Admin": "Staff Admin",
        "Super Admin": "Super Admin",
    }.get(role, "User")

    context = {
        "page_title": "Complete Your Profile",
        "form": form,
        "form_submitted": form_submitted,
        "form_alert": _form_alert([form], member_formset) if request.method == "POST" else "",
        "is_student_role": is_student_role,
        "role_display": role_display,
        "user_name": request.user.username,
        "user_email": request.user.email,
        "member_formset": member_formset,
        "max_group_members": MAX_GROUP_MEMBERS,
    }
    return render(request, "core/complete_profile.html", context)


MAX_STATUS_REASON_LENGTH = 500


def _send_account_status_email(request, user, active, reason=""):
    """Tells the account holder their account was activated or deactivated.
    Returns an error message if the email could not be sent, else ""."""
    if not user.email:
        return "This account has no email address, so no email was sent."
    name = account_display_name(user)
    contact = (LandingSettings.load().contact_email or "").strip()
    contact_line = f"If you have questions, contact {contact}." if contact else "If you have questions, contact the research office."
    if active:
        login_url = request.build_absolute_uri(reverse("login"))
        subject = "Your Food Match account has been activated"
        text_body = (
            f"Hello {name},\n\n"
            f"Your Food Match account ({user.username}) has been activated. You can sign in again.\n\n"
            f"Sign in here: {login_url}\n\n{contact_line}\n"
        )
        html_body = (
            f"<p>Hello {escape(name)},</p>"
            f"<p>Your Food Match account (<strong>{escape(user.username)}</strong>) has been activated. You can sign in again.</p>"
            f'<p><a href="{escape(login_url)}">Sign in to Food Match</a></p>'
            f"<p>{escape(contact_line)}</p>"
        )
    else:
        subject = "Your Food Match account has been deactivated"
        text_body = (
            f"Hello {name},\n\n"
            f"Your Food Match account ({user.username}) has been deactivated, so you can no longer sign in.\n\n"
            f"Reason: {reason}\n\n{contact_line}\n"
        )
        html_body = (
            f"<p>Hello {escape(name)},</p>"
            f"<p>Your Food Match account (<strong>{escape(user.username)}</strong>) has been deactivated, so you can no longer sign in.</p>"
            f'<p><strong>Reason:</strong><br>{escape(reason)}</p>'
            f"<p>{escape(contact_line)}</p>"
        )
    try:
        message = EmailMultiAlternatives(subject, text_body, to=[user.email])
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)
    except Exception:
        logger.exception("Could not send account status email to user %s", user.pk)
        return "The status was changed, but the email to the user could not be sent."
    return ""


def _send_registration_decision_email(request, user, approved, reason=""):
    """Tells a group whether its registration was approved (they can now log in)
    or rejected (with the reason). Returns an error message if the email could
    not be sent, else ""."""
    if not user.email:
        return "This account has no email address, so no email was sent."
    name = account_display_name(user)
    contact = (LandingSettings.load().contact_email or "").strip()
    contact_line = f"If you have questions, contact {contact}." if contact else "If you have questions, contact the research office."
    if approved:
        login_url = request.build_absolute_uri(reverse("login"))
        subject = "Your Food Match registration has been approved"
        text_body = (
            f"Hello {name},\n\n"
            "Good news! Your Food Match registration has been approved. You can now log in with your "
            f"username ({user.username}) and the password you chose when you registered.\n\n"
            f"Log in here: {login_url}\n\n{contact_line}\n"
        )
        html_body = (
            f"<p>Hello {escape(name)},</p>"
            "<p>Good news! Your Food Match registration has been approved. You can now log in with your "
            f"username (<strong>{escape(user.username)}</strong>) and the password you chose when you registered.</p>"
            f'<p><a href="{escape(login_url)}">Log in to Food Match</a></p>'
            f"<p>{escape(contact_line)}</p>"
        )
    else:
        register_url = request.build_absolute_uri(reverse("register"))
        subject = "Your Food Match registration was not approved"
        text_body = (
            f"Hello {name},\n\n"
            f"Your Food Match registration ({user.username}) was not approved, so the account was not created.\n\n"
            f"Reason: {reason}\n\n"
            f"You may register again here: {register_url}\n\n{contact_line}\n"
        )
        html_body = (
            f"<p>Hello {escape(name)},</p>"
            f"<p>Your Food Match registration (<strong>{escape(user.username)}</strong>) was not approved, so the account was not created.</p>"
            f'<p><strong>Reason:</strong><br>{escape(reason)}</p>'
            f'<p>You may <a href="{escape(register_url)}">register again</a>.</p>'
            f"<p>{escape(contact_line)}</p>"
        )
    try:
        message = EmailMultiAlternatives(subject, text_body, to=[user.email])
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)
    except Exception:
        logger.exception("Could not send registration decision email to user %s", user.pk)
        return "The email to the group could not be sent."
    return ""


def _set_account_active(request, target_user, make_active, reason, actor_label):
    """Activate or deactivate an account: save it, record the reason, log it and
    email the user. Returns (message, email_warning)."""
    target_user.is_active = make_active
    target_user.save(update_fields=["is_active"])
    if make_active:
        AccountDeactivation.objects.filter(user=target_user).delete()
    else:
        AccountDeactivation.objects.update_or_create(
            user=target_user, defaults={"reason": reason, "deactivated_by": request.user}
        )
    target_label = target_user.get_full_name().strip() or target_user.username
    state_label = "activated" if make_active else "deactivated"
    log_text = f"{actor_label} {state_label} account: {target_label} (email: {target_user.email})."
    if not make_active:
        log_text += f" Reason: {reason}"
    _log_system_event(request, request.user, SystemLogType.ACTIVITY, log_text)
    email_warning = _send_account_status_email(request, target_user, make_active, reason)
    message = f"Account '{target_label}' has been {state_label}"
    message += "." if email_warning else " and the user was notified by email."
    return message, email_warning


def _clean_status_reason(request):
    return (request.POST.get("reason") or "").strip()[:MAX_STATUS_REASON_LENGTH]


def _confirm_password_only(request, wrong_password_error):
    """The acting Super Admin re-enters their own password. Returns an error
    message, or "" when it matches; nothing may change when it is set."""
    result = _verify_current_password(request.user, request.POST.get("confirm_password", ""))
    if result == "locked":
        return "Too many incorrect passwords. Wait a few minutes, then try again. Nothing was changed."
    if result == "wrong":
        return wrong_password_error
    return ""


def _confirm_with_password(request, missing_reason_error, wrong_password_error):
    """A Super Admin decision that needs a reason and the acting Super Admin's own
    password. Returns (reason, error); nothing may change when error is set."""
    reason = (request.POST.get("deletion_reason") or "").strip()[:MAX_STATUS_REASON_LENGTH]
    if not reason:
        return "", missing_reason_error
    error = _confirm_password_only(request, wrong_password_error)
    return ("", error) if error else (reason, "")


def _confirm_permanent_delete(request):
    return _confirm_with_password(
        request,
        "Please give a reason for deleting this account. Nothing was deleted.",
        "Incorrect password. The account was not deleted.",
    )


def _requested_active_state(request, target_user):
    """The state the button asked for ("1" activate / "0" deactivate). A form
    without it falls back to flipping the current state."""
    requested = request.POST.get("make_active")
    if requested in ("0", "1"):
        return requested == "1"
    return not target_user.is_active


def _redirect_with_result(request, url_name, action_message, action_error, query=""):
    """Post/Redirect/Get: carry the outcome to a fresh GET so reloading the page
    can never send the same action again. `query` keeps the page's filters."""
    if action_message:
        messages.success(request, action_message)
    if action_error:
        (messages.warning if action_message else messages.error)(request, action_error)
    return redirect(reverse(url_name) + (f"?{query}" if query else ""))


def _pop_result_messages(request):
    message, error = "", ""
    for item in messages.get_messages(request):
        if item.level >= messages.WARNING:
            error = str(item)
        else:
            message = str(item)
    return message, error


def _can_edit_account(actor, target):
    """Super Admin: anyone but themselves (their own account uses Profile).
    Admin: Admins and Students, never a Super Admin or themselves."""
    if target.pk == actor.pk or is_emergency_user(target):
        return False
    return actor.is_superuser or not target.is_superuser


def _account_edit_forms(target, data=None):
    is_student = not (target.is_staff or target.is_superuser)
    profile = getattr(target, "registration_profile", None)
    if data is None:
        initial = {
            "username": target.username,
            "email": target.email,
            "first_name": target.first_name,
            "middle_name": profile.middle_name if profile else "",
            "last_name": target.last_name,
            "program": profile.program if profile and is_student else "",
            "college": profile.college if profile and is_student else "",
            "group_name": profile.group_name if profile and is_student else "",
        }
        form = AdminUserEditForm(initial=initial, user=target, require_student_fields=is_student)
        members = build_member_formset(None, target) if is_student else None
    else:
        form = AdminUserEditForm(data, user=target, require_student_fields=is_student)
        members = build_member_formset(data, target) if is_student else None
    return form, members, is_student


@login_required(login_url="login")
def manage_users_view(request):
    redirect_response = _admin_module_or_denied(request, AdminModule.MANAGE_USERS)
    if redirect_response:
        return redirect_response

    is_super_admin = request.user.is_superuser
    form = AdminUserCreationForm(is_super_admin=is_super_admin)
    form_submitted = False
    created_user_name = ""
    created_user_email = ""
    created_user_role = ""
    action_message = ""
    action_error = ""
    edit_target = None
    edit_form = None
    edit_member_formset = None
    edit_is_student = False

    edit_id = request.GET.get("edit", "").strip()
    if request.method == "GET" and edit_id.isdigit():
        candidate = User.objects.filter(pk=int(edit_id)).first()
        if candidate is None:
            action_error = "That account no longer exists."
        elif not _can_edit_account(request.user, candidate):
            action_error = "You do not have permission to edit this account."
        else:
            edit_target = candidate
            edit_form, edit_member_formset, edit_is_student = _account_edit_forms(candidate)

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        user_id_raw = request.POST.get("user_id", "").strip()

        # ----------------- ACTIONS: Super Admin & Staff Admin -----------------
        # --- toggle_active: Super Admin (any user except self)
        #                    Staff Admin (only students, not self)
        # --- delete_user: Super Admin (direct delete, any user except self)
        # --- request_delete: Staff Admin (creates a pending UserDeletionRequest,
        #                      students only, no self-target)
        # (Approving/rejecting pending requests now lives on its own page —
        #  see deletion_requests_view.)
        # ------------------------------------------------------------------------

        id_valid = False
        target_user = None
        if user_id_raw and action in (
            "toggle_active", "delete_user", "request_delete", "edit_user",
        ):
            try:
                user_id = int(user_id_raw)
            except (TypeError, ValueError):
                action_error = "Invalid user reference."
            else:
                target_user = get_object_or_404(User, pk=user_id)
                id_valid = True

        if action == "toggle_active" and id_valid and target_user:
            # Permissions:
            #   Super Admin -> can toggle any user except self
            #   Staff Admin -> can toggle any user except self and Super Admins
            can_toggle = False
            actor_label = "Super Admin" if is_super_admin else "Admin"
            if is_super_admin:
                can_toggle = target_user.pk != request.user.pk
            else:
                can_toggle = (
                    target_user.pk != request.user.pk
                    and not target_user.is_superuser
                )

            if not can_toggle:
                if target_user.pk == request.user.pk:
                    action_error = "You cannot modify your own account status."
                else:
                    action_error = "You do not have permission to change this account's status."
            elif _registration_pending(target_user):
                action_error = "This registration is still waiting for approval. Approve or reject it on the Registration Requests page."
            else:
                make_active = _requested_active_state(request, target_user)
                reason = _clean_status_reason(request)
                target_label = target_user.get_full_name().strip() or target_user.username
                if make_active == target_user.is_active:
                    action_message = f"Account '{target_label}' is already {'active' if make_active else 'deactivated'}."
                elif not make_active and not reason:
                    action_error = "Please give a reason for deactivating this account."
                else:
                    action_message, email_warning = _set_account_active(
                        request, target_user, make_active, reason, actor_label
                    )
                    if email_warning:
                        action_error = email_warning

        elif action == "delete_user" and id_valid and is_super_admin and target_user:
            deletion_reason, confirm_error = ("", "") if target_user.pk == request.user.pk else _confirm_permanent_delete(request)
            if target_user.pk == request.user.pk:
                action_error = "You cannot delete your own account."
            elif confirm_error:
                action_error = confirm_error
            else:
                target_label = (
                    target_user.get_full_name().strip() or target_user.username
                )
                target_email = target_user.email
                with transaction.atomic():
                    try:
                        profile = getattr(target_user, "registration_profile", None)
                        if profile:
                            profile.delete()
                    except Exception:
                        pass
                    # Clean up any associated deletion requests
                    UserDeletionRequest.objects.filter(target_user=target_user).delete()
                    target_user.delete()
                action_message = (
                    f"Account '{target_label}' has been permanently deleted."
                )
                _log_system_event(
                    request,
                    request.user,
                    SystemLogType.ACTIVITY,
                    f"Super Admin permanently deleted account: {target_label} "
                    f"(email: {target_email}). Reason: {deletion_reason}",
                )

        elif action == "request_delete" and id_valid and not is_super_admin and target_user:
            # Staff Admin: can request deletion for any user except self and Super Admins
            target_label = (
                target_user.get_full_name().strip() or target_user.username
            )
            deletion_reason = _clean_status_reason(request)
            if target_user.pk == request.user.pk:
                action_error = "You cannot request deletion of your own account."
            elif target_user.is_superuser:
                action_error = "You cannot request deletion of a Super Admin account."
            elif not deletion_reason:
                action_error = "Please give a reason for the deletion request."
            else:
                existing_pending = UserDeletionRequest.objects.filter(
                    target_user=target_user,
                    status=DeletionRequestStatus.PENDING,
                ).first()
                if existing_pending:
                    action_error = (
                        f"There is already a pending deletion request for '{target_label}'."
                    )
                else:
                    UserDeletionRequest.objects.create(
                        target_user=target_user,
                        requested_by=request.user,
                        reason=deletion_reason,
                        status=DeletionRequestStatus.PENDING,
                    )
                    target_role_label = "Admin" if target_user.is_staff else "Student"
                    action_message = (
                        f"Deletion request for {target_role_label.lower()} '{target_label}' has been submitted. "
                        "Pending Super Admin approval."
                    )
                    _log_system_event(
                        request,
                        request.user,
                        SystemLogType.ACTIVITY,
                        f"Admin requested deletion of {target_role_label.lower()} account: {target_label} "
                        f"(email: {target_user.email}). Reason: {deletion_reason}. Request pending Super Admin approval.",
                    )
                    notify(
                        super_admins(),
                        NotificationCategory.DELETION,
                        "New deletion request",
                        f"{account_display_name(request.user)} requested deletion of {target_role_label.lower()} "
                        f"account '{target_label}'. Reason: {deletion_reason}",
                        "admin_deletion_requests",
                        exclude=request.user,
                    )

        elif action == "edit_user" and id_valid and target_user:
            if not _can_edit_account(request.user, target_user):
                action_error = "You do not have permission to edit this account."
            else:
                edit_target = target_user
                edit_form, edit_member_formset, edit_is_student = _account_edit_forms(target_user, request.POST)
                members_valid = edit_member_formset.is_valid() if edit_member_formset is not None else True
                if edit_form.is_valid() and members_valid:
                    data = edit_form.cleaned_data
                    old_username, old_email = target_user.username, target_user.email
                    with transaction.atomic():
                        profile = getattr(target_user, "registration_profile", None)
                        if profile is None:
                            profile = RegistrationProfile(user=target_user, login_as=LoginAs.STUDENT)
                        if edit_is_student:
                            _apply_group_members(target_user, profile, edit_member_formset, data.get("group_name", ""))
                            profile.program = data["program"]
                            profile.college = data["college"]
                        else:
                            target_user.first_name = data["first_name"]
                            target_user.last_name = data["last_name"]
                            profile.middle_name = data["middle_name"]
                        target_user.username = data["username"]
                        target_user.email = data["email"]
                        target_user.save(update_fields=["username", "first_name", "last_name", "email"])
                        profile.save()
                    changes = []
                    if old_username != target_user.username:
                        changes.append(f"username {old_username} -> {target_user.username}")
                    if (old_email or "").lower() != target_user.email.lower():
                        changes.append(f"email {old_email} -> {target_user.email}")
                    actor_label = "Super Admin" if is_super_admin else "Admin"
                    target_label = account_display_name(target_user)
                    _log_system_event(
                        request,
                        request.user,
                        SystemLogType.ACTIVITY,
                        f"{actor_label} edited account details of {target_label}"
                        + (f" ({'; '.join(changes)})." if changes else "."),
                    )
                    action_message = f"Account '{target_label}' was updated."
                    edit_target = None
                    edit_form = None
                    edit_member_formset = None

        elif action == "resend_invite" and user_id_raw:
            try:
                invite_id = int(user_id_raw)
            except (TypeError, ValueError):
                action_error = "Invalid invite reference."
            else:
                invite = PendingUserInvite.objects.filter(pk=invite_id).first()
                if not invite:
                    action_error = "This invite no longer exists."
                elif not is_super_admin and invite.login_as == PendingUserInviteRole.SUPER_ADMIN:
                    action_error = "You do not have permission to resend this invite."
                elif cache.get(f"invite-resend:{invite.pk}"):
                    action_error = "Login details were just sent. Please wait a minute before resending."
                else:
                    temp_password = _generate_temp_password()
                    try:
                        _send_invite_credentials_email(request, invite.username, invite.email, invite.login_as, temp_password)
                    except Exception:
                        logger.exception("Could not re-send invite credentials for %s", invite.username)
                        action_error = "We could not email the login details. Please try again."
                    else:
                        invite.password_hash = make_password(temp_password)
                        invite.save(update_fields=["password_hash"])
                        cache.set(f"invite-resend:{invite.pk}", True, 60)
                        action_message = f"New login details were emailed to {invite.email}. The previous temporary password no longer works."
                        _log_system_event(
                            request,
                            request.user,
                            SystemLogType.ACTIVITY,
                            f"{'Super Admin' if is_super_admin else 'Admin'} re-sent login details for pending invite: "
                            f"{invite.username} (email: {invite.email}).",
                        )

        elif action == "cancel_invite" and user_id_raw:
            try:
                invite_id = int(user_id_raw)
            except (TypeError, ValueError):
                action_error = "Invalid invite reference."
            else:
                invite = PendingUserInvite.objects.filter(pk=invite_id).first()
                if not invite:
                    action_error = "This invite no longer exists."
                elif not is_super_admin and invite.login_as == PendingUserInviteRole.SUPER_ADMIN:
                    action_error = "You do not have permission to cancel this invite."
                else:
                    invite_label = invite.username
                    invite.delete()
                    action_message = f"Pending invite for '{invite_label}' has been cancelled."
                    _log_system_event(
                        request,
                        request.user,
                        SystemLogType.ACTIVITY,
                        f"{'Super Admin' if is_super_admin else 'Admin'} cancelled pending invite: {invite_label} (email: {invite.email}).",
                    )

        elif not action:
            form = AdminUserCreationForm(request.POST, is_super_admin=is_super_admin)
            if form.is_valid():
                username = form.cleaned_data["username"]
                email = form.cleaned_data["email"]
                login_as = form.cleaned_data["login_as"]
                temp_password = _generate_temp_password()
                invite = PendingUserInvite.objects.create(
                    username=username,
                    email=email,
                    password_hash=make_password(temp_password),
                    login_as=login_as,
                    created_by=request.user,
                )
                try:
                    _send_invite_credentials_email(request, username, email, login_as, temp_password)
                except Exception:
                    logger.exception("Could not email invite credentials for %s", username)
                    invite.delete()
                    form.add_error(
                        None,
                        "We could not email the login details, so the account was not created. "
                        "Check the email address and try again.",
                    )
                else:
                    created_user_name = invite.username
                    created_user_email = email
                    created_user_role = login_as
                    form = AdminUserCreationForm(is_super_admin=is_super_admin)
                    form_submitted = True
                    actor_label = "Super Admin" if is_super_admin else "Admin"
                    _log_system_event(
                        request,
                        request.user,
                        SystemLogType.ACTIVITY,
                        f"{actor_label} invited a new {login_as} account: {created_user_name} (email: {email}). "
                        "Login details were emailed to the user; the account will be created once they log in "
                        "and complete onboarding.",
                    )

    if request.method == "POST" and action and not (action == "edit_user" and edit_target is not None):
        return _redirect_with_result(request, "admin_manage_users", action_message, action_error)
    if request.method == "GET":
        flash_message, flash_error = _pop_result_messages(request)
        action_message = action_message or flash_message
        action_error = action_error or flash_error

    if is_super_admin:
        all_users = User.objects.select_related("registration_profile").prefetch_related("group_members").order_by(
            "-is_superuser", "-is_staff", "-date_joined"
        )
    else:
        # Staff Admin sees every account except Super Admins (fellow Admins + Students).
        all_users = User.objects.select_related("registration_profile").prefetch_related("group_members").filter(
            is_superuser=False
        ).order_by("-is_staff", "-date_joined")
    # Registrations still waiting for approval live on the Registration Requests page.
    all_users = all_users.exclude(registration_profile__approval_status=RegistrationStatus.PENDING)

    # Build set of user_ids with a pending deletion request
    pending_req_user_ids = set(
        UserDeletionRequest.objects
        .filter(status=DeletionRequestStatus.PENDING)
        .exclude(target_user__isnull=True)
        .values_list("target_user_id", flat=True)
    )

    user_rows = []
    for user in all_users:
        profile = getattr(user, "registration_profile", None)
        effective_role = _effective_login_role_for_profile(user) or (profile.login_as if profile and profile.login_as else None)
        if effective_role == "Super Admin":
            role_label = "Super Admin"
            role_category = "super_admin"
        elif effective_role == "Admin":
            role_label = "Admin"
            role_category = "admin"
        elif effective_role == LoginAs.STUDENT:
            role_label = "Student"
            role_category = "student"
        else:
            role_label = "Student" if not is_super_admin else "Unknown"
            role_category = "student" if not is_super_admin else "unknown"

        display_name = account_display_name(user) if user.get_full_name().strip() else ""
        member_names = [] if (user.is_staff or user.is_superuser) else group_member_names(user)
        profile_complete = _profile_is_complete(user)
        user_rows.append(
            {
                "id": user.pk,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "middle_name": profile.middle_name if profile else "",
                "last_name": user.last_name,
                "program": profile.program if profile else "",
                "college": profile.college if profile else "",
                "display_name": display_name,
                "group_name": (profile.group_name if profile and not (user.is_staff or user.is_superuser) else ""),
                "members": member_names,
                "members_joined": " | ".join(member_names),
                "role_label": role_label,
                "role_category": role_category,
                "is_active": user.is_active,
                "profile_complete": profile_complete,
                "is_superuser": user.is_superuser,
                "is_staff": user.is_staff,
                "has_pending_delete": user.pk in pending_req_user_ids,
                "date_joined": timezone.localtime(user.date_joined).strftime("%b %d, %Y %I:%M %p"),
                "date_joined_iso": timezone.localdate(user.date_joined).isoformat() if user.date_joined else "",
                "last_login": timezone.localtime(user.last_login).strftime("%b %d, %Y %I:%M %p") if user.last_login else "Never logged in",
            }
        )

    context = {
        "page_title": "Manage Users",
        "is_super_admin": is_super_admin,
        "form": form,
        "form_submitted": form_submitted,
        "created_user_name": created_user_name,
        "created_user_email": created_user_email,
        "created_user_role": created_user_role,
        "action_message": action_message,
        "action_error": action_error,
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "admin_role": "Super Admin" if is_super_admin else "Admin",
        "user_rows": user_rows,
        "total_users": len(user_rows),
        "edit_target": edit_target,
        "edit_target_name": account_display_name(edit_target) if edit_target else "",
        "edit_form": edit_form,
        "member_formset": edit_member_formset,
        "edit_is_student": edit_is_student,
        "max_group_members": MAX_GROUP_MEMBERS,
    }
    return render(request, "core/admin_manage_users.html", context)


REGISTRATION_HISTORY_SHOWN = 20


def _decide_registration(request, action, user_id_raw):
    """Approve (account turned on + email) or reject (email with the reason,
    then the request is removed) one registration. Returns (message, error)."""
    actor_label = "Super Admin" if request.user.is_superuser else "Admin"
    applicant = None
    if user_id_raw.isdigit():
        applicant = User.objects.select_related("registration_profile").filter(
            pk=int(user_id_raw),
            is_staff=False,
            is_superuser=False,
            registration_profile__approval_status=RegistrationStatus.PENDING,
        ).first()
    if applicant is None:
        return "", "This registration request no longer exists or was already handled."
    applicant_label = account_display_name(applicant)

    if action == "approve_registration":
        with transaction.atomic():
            # Only one decision counts if two people click at the same time.
            approved = RegistrationProfile.objects.filter(
                user=applicant, approval_status=RegistrationStatus.PENDING
            ).update(
                approval_status=RegistrationStatus.APPROVED,
                approved_by=request.user,
                approved_at=timezone.now(),
            )
            if approved:
                User.objects.filter(pk=applicant.pk).update(is_active=True)
        if not approved:
            return "", "This registration request was already handled."
        _log_system_event(
            request,
            request.user,
            SystemLogType.ACTIVITY,
            f"{actor_label} approved the registration of {applicant_label} "
            f"(username: {applicant.username}, email: {applicant.email}).",
        )
        email_warning = _send_registration_decision_email(request, applicant, True)
        message = f"The registration of '{applicant_label}' was approved. " + (
            "They can now log in." if email_warning else "They were emailed that they can now log in."
        )
        return message, email_warning

    reason = (request.POST.get("deletion_reason") or "").strip()[:MAX_STATUS_REASON_LENGTH]
    if not reason:
        return "", "Please give a reason for rejecting this registration."
    username, email = applicant.username, applicant.email
    email_warning = _send_registration_decision_email(request, applicant, False, reason)
    # Removing the request frees the username, email and members, so the group
    # can fix the problem and register again.
    applicant.delete()
    _log_system_event(
        request,
        request.user,
        SystemLogType.ACTIVITY,
        f"{actor_label} rejected the registration of {applicant_label} "
        f"(username: {username}, email: {email}). Reason: {reason}",
    )
    message = f"The registration of '{applicant_label}' was rejected and removed."
    if not email_warning:
        message += " The group was emailed your reason."
    return message, email_warning


def _registration_row(applicant):
    profile = applicant.registration_profile
    return {
        "id": applicant.pk,
        "status": profile.approval_status,
        "username": applicant.username,
        "email": applicant.email,
        "display_name": account_display_name(applicant),
        "members": group_member_names(applicant),
        "program": profile.program,
        "college": profile.college,
        "registered_at": timezone.localtime(applicant.date_joined).strftime("%b %d, %Y %I:%M %p"),
        "approved_by": account_display_name(profile.approved_by) if profile.approved_by else "",
        "approved_at": timezone.localtime(profile.approved_at).strftime("%b %d, %Y %I:%M %p") if profile.approved_at else "",
    }


@login_required(login_url="login")
def registration_requests_view(request):
    """Student groups that signed up on the Registration page and wait for an
    Admin or Super Admin to approve them, plus the ones approved most recently."""
    redirect_response = _admin_module_or_denied(request, AdminModule.MANAGE_USERS)
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action in ("approve_registration", "reject_registration"):
            message, error = _decide_registration(request, action, request.POST.get("user_id", "").strip())
        else:
            message, error = "", "Unknown action."
        return _redirect_with_result(request, "admin_registration_requests", message, error)

    action_message, action_error = _pop_result_messages(request)
    students = User.objects.filter(is_staff=False, is_superuser=False).select_related(
        "registration_profile__approved_by"
    ).prefetch_related("group_members")
    pending = [
        _registration_row(applicant)
        for applicant in students.filter(registration_profile__approval_status=RegistrationStatus.PENDING).order_by("date_joined")
    ]
    recently_approved = [
        _registration_row(applicant)
        for applicant in students.filter(
            registration_profile__approval_status=RegistrationStatus.APPROVED,
            registration_profile__approved_at__isnull=False,
        ).order_by("-registration_profile__approved_at")[:REGISTRATION_HISTORY_SHOWN]
    ]
    context = {
        "page_title": "Registration Requests",
        "is_super_admin": request.user.is_superuser,
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "admin_role": "Super Admin" if request.user.is_superuser else "Admin",
        "pending_requests": pending,
        "recently_approved": recently_approved,
        "action_message": action_message,
        "action_error": action_error,
    }
    return render(request, "core/admin_registration_requests.html", context)


@login_required(login_url="login")
def deletion_requests_view(request):
    redirect_response = _super_admin_module_or_denied(request, "Deletion Requests")
    if redirect_response:
        return redirect_response

    action_message = ""
    action_error = ""

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        request_id_raw = request.POST.get("deletion_request_id", "").strip()

        if action in ("approve_delete", "reject_delete") and request_id_raw:
            try:
                request_id = int(request_id_raw)
            except (TypeError, ValueError):
                action_error = "Invalid deletion request reference."
            else:
                del_request = get_object_or_404(
                    UserDeletionRequest.objects.select_related(
                        "target_user", "requested_by"
                    ),
                    pk=request_id,
                )
                # Approving: the requesting Admin already gave the reason, so the
                # Super Admin only confirms with their own password. Rejecting
                # keeps the account and needs the Super Admin's reason (no password).
                if action == "approve_delete":
                    decision_reason = ""
                    confirm_error = _confirm_password_only(request, "Incorrect password. The account was not deleted.")
                else:
                    decision_reason = (request.POST.get("deletion_reason") or "").strip()[:MAX_STATUS_REASON_LENGTH]
                    confirm_error = "" if decision_reason else "Please give a reason for rejecting this request. It is still pending."
                if del_request.status != DeletionRequestStatus.PENDING:
                    action_error = (
                        f"This request is already {del_request.status}."
                    )
                elif confirm_error:
                    action_error = confirm_error
                else:
                    target_label = del_request.target_display_name()
                    target_email = (
                        del_request.target_user.email
                        if del_request.target_user
                        else "N/A"
                    )
                    with transaction.atomic():
                        del_request.status = (
                            DeletionRequestStatus.APPROVED
                            if action == "approve_delete"
                            else DeletionRequestStatus.REJECTED
                        )
                        del_request.reviewed_by = request.user
                        del_request.reviewed_at = timezone.now()
                        del_request.review_notes = decision_reason
                        del_request.save()

                        if action == "approve_delete" and del_request.target_user:
                            actual_user = del_request.target_user
                            try:
                                profile = getattr(actual_user, "registration_profile", None)
                                if profile:
                                    profile.delete()
                            except Exception:
                                pass
                            # Wipe FK reference so CASCADE doesn't wipe the request row
                            del_request.target_user = None
                            del_request.save(update_fields=["target_user"])
                            actual_user.delete()

                    status_word = "approved" if action == "approve_delete" else "rejected"
                    action_message = (
                        f"Deletion request for '{target_label}' has been {status_word}."
                    )
                    log_msg = (
                        f"Super Admin {status_word} deletion request for account: {target_label} "
                        f"(email: {target_email})."
                    )
                    if action == "approve_delete":
                        log_msg += " Account was permanently deleted."
                    if decision_reason:
                        log_msg += f" Super Admin's reason: {decision_reason}"
                    if del_request.reason:
                        log_msg += f" Request reason: {del_request.reason}"
                    _log_system_event(
                        request,
                        request.user,
                        SystemLogType.ACTIVITY,
                        log_msg,
                    )
                    review_notes = del_request.review_notes
                    notify(
                        [del_request.requested_by],
                        NotificationCategory.DELETION,
                        f"Deletion request {status_word}",
                        f"Your request to delete '{target_label}' was {status_word}."
                        + (f" Reason: {review_notes}" if review_notes else ""),
                        "admin_manage_users",
                        exclude=request.user,
                    )
        # Post/Redirect/Get: a refresh can never resend the decision (or the password).
        return _redirect_with_result(request, "admin_deletion_requests", action_message, action_error)

    action_message, action_error = _pop_result_messages(request)
    qs = (
        UserDeletionRequest.objects
        .select_related("requested_by", "reviewed_by", "target_user")
        .order_by("-requested_at")
    )
    pending_deletion_count = qs.filter(status=DeletionRequestStatus.PENDING).count()

    deletion_requests = []
    for req in qs:
        deletion_requests.append({
            "id": req.pk,
            "status": req.status,
            "target_user_id": req.target_user.pk if req.target_user else None,
            "target_username": req.target_user.username if req.target_user else "[DELETED]",
            "target_email": req.target_user.email if req.target_user else "N/A",
            "target_display_name": (
                req.target_user.get_full_name().strip()
                if req.target_user and req.target_user.get_full_name().strip()
                else (req.target_user.username if req.target_user else req.target_display_name())
            ),
            "requested_by_name": req.requester_display_name(),
            "reason": req.reason,
            "requested_by_role": (
                "Super Admin"
                if req.requested_by and req.requested_by.is_superuser
                else "Admin"
                if req.requested_by and req.requested_by.is_staff
                else "Unknown"
            ),
            "reviewed_by_name": req.reviewer_display_name(),
            "review_notes": req.review_notes or "",
            "requested_at": timezone.localtime(req.requested_at).strftime("%b %d, %Y %I:%M %p"),
            "reviewed_at": (
                timezone.localtime(req.reviewed_at).strftime("%b %d, %Y %I:%M %p")
                if req.reviewed_at
                else "—"
            ),
        })

    context = {
        "page_title": "Deletion Requests",
        "is_super_admin": True,
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "admin_role": "Super Admin",
        "action_message": action_message,
        "action_error": action_error,
        "deletion_requests": deletion_requests,
        "pending_deletion_count": pending_deletion_count,
    }
    return render(request, "core/admin_deletion_requests.html", context)


@login_required(login_url="login")
def manage_food_categories_view(request):
    redirect_response = _admin_module_or_denied(request, AdminModule.MANAGE_CATEGORIES)
    if redirect_response:
        return redirect_response
    actor_label = "Super Admin" if request.user.is_superuser else "Admin"

    action_message = ""
    action_error = ""

    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        if action == "add_category":
            name = request.POST.get("name", "").strip()
            if not name:
                action_error = "Category name is required."
            elif FoodCategory.objects.filter(parent__isnull=True, name__iexact=name).exists():
                action_error = f"A category named '{name}' already exists."
            else:
                FoodCategory.objects.create(name=name, parent=None)
                action_message = f"Category '{name}' was added."
                _log_system_event(
                    request, request.user, SystemLogType.ACTIVITY,
                    f"{actor_label} added food category: '{name}'.",
                )

        elif action == "add_subcategory":
            name = request.POST.get("name", "").strip()
            parent_id = request.POST.get("parent_id", "").strip()
            parent = FoodCategory.objects.filter(pk=parent_id, parent__isnull=True).first()
            if not name:
                action_error = "Subcategory name is required."
            elif not parent:
                action_error = "Please choose a valid category."
            elif FoodCategory.objects.filter(parent=parent, name__iexact=name).exists():
                action_error = f"'{name}' already exists under '{parent.name}'."
            else:
                FoodCategory.objects.create(name=name, parent=parent)
                action_message = f"Subcategory '{name}' was added under '{parent.name}'."
                _log_system_event(
                    request, request.user, SystemLogType.ACTIVITY,
                    f"{actor_label} added food subcategory: '{name}' under '{parent.name}'.",
                )

        elif action == "delete_category":
            category_id = request.POST.get("category_id", "").strip()
            category = FoodCategory.objects.filter(pk=category_id).first()
            if not category:
                action_error = "Category not found or already deleted."
            else:
                deleted_name = category.name
                is_parent = category.parent_id is None
                child_count = category.subcategories.count() if is_parent else 0
                category.delete()
                if is_parent and child_count:
                    action_message = f"Category '{deleted_name}' and its {child_count} subcategories were deleted."
                else:
                    action_message = f"'{deleted_name}' was deleted."
                _log_system_event(
                    request, request.user, SystemLogType.ACTIVITY,
                    f"{actor_label} deleted food category: '{deleted_name}'.",
                )

    categories = (
        FoodCategory.objects
        .filter(parent__isnull=True)
        .prefetch_related("subcategories")
        .order_by("id")
    )

    context = {
        "page_title": "Manage Categories",
        "is_super_admin": request.user.is_superuser,
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "admin_role": "Super Admin" if request.user.is_superuser else "Admin",
        "action_message": action_message,
        "action_error": action_error,
        "categories": categories,
        "total_categories": categories.count(),
        "total_subcategories": FoodCategory.objects.filter(parent__isnull=False).count(),
    }
    return render(request, "core/admin_manage_categories.html", context)


@login_required(login_url="login")
def admin_extract_research_metadata_view(request):
    """AJAX endpoint: given an uploaded research file, extract Title, Authors,
    Adviser, Abstract, Published Month, and Published Year so the Add Research
    (Admin) / Submit Research (Student) forms can pre-fill them for review
    before saving. Best-effort — any field can come back blank; nothing here
    is ever required to be right."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Please log in."}, status=403)

    is_super_admin = request.user.is_superuser
    can_add_research = _admin_has_module(request.user, AdminModule.ADD_RESEARCH)
    is_student = not request.user.is_staff and not is_super_admin
    if not (can_add_research or is_student):
        return JsonResponse({"error": "You do not have permission to use this."}, status=403)

    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=405)

    uploaded_file = request.FILES.get("document")
    if not uploaded_file:
        return JsonResponse({"error": "Please choose a file first."}, status=400)

    if not uploaded_file.name.lower().endswith(DOCUMENT_UPLOAD_EXTENSIONS):
        return JsonResponse({"error": "Only PDF, DOCX, TXT, JPG, or PNG files are allowed."}, status=400)

    # Warn right away if this exact file is already in the system; the final
    # submit checks again, so this is only an early heads-up.
    duplicate_error = duplicate_file_error(file_sha256(uploaded_file), request.user)
    if duplicate_error:
        return JsonResponse({"error": duplicate_error, "duplicate": True}, status=409)

    text_layer = read_text_layer(uploaded_file)
    try:
        if text_layer["kind"] == "pdf" and len(text_layer["text"].strip()) >= 40:
            text = text_layer["text"]  # same text as before; saves reading the PDF twice
        else:
            text = extract_text_from_uploaded_file(uploaded_file)
    except Exception as exc:
        return JsonResponse({"error": f"Could not read this file: {exc}"}, status=400)

    if not text.strip():
        return JsonResponse({"error": "The uploaded file does not contain readable text."}, status=400)

    metadata = extract_research_metadata_from_text(text)
    food_check = assess_food_relevance(metadata["title"], metadata["abstract"], "", text)
    if not food_check["is_food"]:
        return JsonResponse({"error": not_food_research_error(food_check), "not_food": True}, status=422)

    # Same completeness rule as the final submit, shown as soon as the file is chosen.
    completeness = assess_document(text_layer)
    if completeness["status"] == "incomplete":
        return JsonResponse(
            {"error": incomplete_research_error(completeness), "incomplete": True, "missing": completeness["missing"]},
            status=422,
        )
    if completeness["status"] == "unverified" and is_student:
        return JsonResponse({"error": UNVERIFIED_RESEARCH_ERROR, "incomplete": True}, status=422)
    # Text read from the file is fitted to the same character rules as typed
    # input, so the auto-filled fields don't start out with errors.
    filled = {
        "title": tidy_to_rule(metadata["title"] or "", "title"),
        "abstract": tidy_to_rule(metadata["abstract"] or "", "abstract"),
        "adviser": tidy_to_rule(metadata["adviser"] or "", "name"),
    }
    authors = [name for name in (tidy_to_rule(a, "name") for a in metadata["authors"] or []) if name]
    tidied = [
        label for label, key in (("Title", "title"), ("Abstract", "abstract"), ("Adviser", "adviser"))
        if filled[key] != normalize_text_input(metadata[key] or "").strip()
    ]
    if authors != [normalize_text_input(a).strip() for a in metadata["authors"] or []]:
        tidied.append("Authors")
    return JsonResponse(
        {
            **filled,
            "authors": authors,
            "published_month": metadata["published_month"],
            "published_year": metadata["published_year"],
            "tidied": tidied,
        }
    )


@login_required(login_url="login")
def add_food_category_view(request):
    """AJAX endpoint: create a new top-level food category inline from the Add
    Research (Admin) / Submit Research (Student) forms, so a user doesn't have
    to leave the form to add a category that isn't in the list yet. Same
    permission scope as the metadata-extraction endpoint above."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Please log in."}, status=403)

    is_super_admin = request.user.is_superuser
    can_add_research = _admin_has_module(request.user, AdminModule.ADD_RESEARCH)
    is_student = not request.user.is_staff and not is_super_admin
    if not (can_add_research or is_student):
        return JsonResponse({"error": "You do not have permission to use this."}, status=403)

    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=405)

    name = " ".join(normalize_text_input(request.POST.get("name", "")).split())
    if not name:
        return JsonResponse({"error": "Category name is required."}, status=400)
    if len(name) > 100:
        return JsonResponse({"error": "Category name is too long."}, status=400)
    name_error = rule_error("Category name", name, "category")
    if name_error:
        return JsonResponse({"error": name_error}, status=400)

    existing = FoodCategory.objects.filter(parent__isnull=True, name__iexact=name).first()
    if existing:
        return JsonResponse({"id": existing.pk, "name": existing.name, "already_existed": True})

    category = FoodCategory.objects.create(name=name, parent=None)
    actor_label = "Super Admin" if is_super_admin else "Admin" if request.user.is_staff else "Student"
    _log_system_event(
        request, request.user, SystemLogType.ACTIVITY,
        f"{actor_label} added food category: '{name}'.",
    )
    return JsonResponse({"id": category.pk, "name": category.name, "already_existed": False})


@login_required(login_url="login")
@ensure_csrf_cookie
def repository_add_research_view(request):
    redirect_response = _admin_module_or_denied(request, AdminModule.RESEARCH_REPOSITORY)
    if redirect_response:
        return redirect_response
    is_super_admin = request.user.is_superuser
    # Deleting stays Super Admin-only regardless of granted privileges.
    can_add_research = _admin_has_module(request.user, AdminModule.ADD_RESEARCH)
    actor_label = "Super Admin" if is_super_admin else "Admin"

    form = RepositoryResearchAddForm()
    form_submitted = False
    saved_title = ""
    saved_error = ""
    action_message = ""
    action_error = ""
    if request.method != "POST":
        action_message, action_error = _pop_result_messages(request)

    # Staff Admins without the privilege browse the repository read-only.
    if request.method == "POST" and not can_add_research:
        return redirect("admin_repository_add")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "delete_research":
            delete_reason = ""
            if not is_super_admin:
                action_error = "Only Super Admin can delete research from the repository."
                paper_id = None
            else:
                paper_id = request.POST.get("paper_id")
                # A reason, then the Super Admin's own password (see _delete_confirm_modal.html).
                delete_reason, confirm_error = _confirm_with_password(
                    request,
                    "Please give a reason for deleting this study. Nothing was deleted.",
                    "Incorrect password. The study was not deleted.",
                )
                if confirm_error:
                    action_error, paper_id = confirm_error, None
            if paper_id:
                try:
                    paper = ResearchPaper.objects.get(pk=paper_id)
                    deleted_title = paper.title
                    deleted_authors = paper.authors
                    with transaction.atomic():
                        # The same study may have been uploaded more than once
                        # (before duplicate uploads were blocked); remove every copy.
                        copies = list(ResearchSubmission.objects.filter(
                            student=request.user,
                            title=paper.title,
                            status=ResearchSubmissionStatus.APPROVED,
                        ))
                        files = [(sub.document.storage, sub.document.name) for sub in copies if sub.document]
                        ResearchSubmission.objects.filter(pk__in=[sub.pk for sub in copies]).delete()
                        paper.delete()
                        # Files go only once the database change is saved.
                        transaction.on_commit(lambda files=files: [_delete_stored_file(name, storage) for storage, name in files])
                    action_message = f"Deleted '{deleted_title}' from the repository."
                    copies_note = f" Removed {len(copies)} uploaded copies of it." if len(copies) > 1 else ""
                    _log_system_event(
                        request,
                        request.user,
                        SystemLogType.ACTIVITY,
                        f"Super Admin deleted research from the repository: '{deleted_title}' (authors: {deleted_authors}).{copies_note}"
                        f" Reason: {delete_reason}",
                    )
                except ResearchPaper.DoesNotExist:
                    action_error = "Research paper not found or already deleted."
                except Exception as exc:
                    action_error = f"Unable to delete study: {str(exc)}"
            # Post/Redirect/Get: a refresh can never resend the delete (or the password).
            return _redirect_with_result(request, "admin_repository_add", action_message, action_error,
                                         query=request.GET.urlencode())
        elif action == "add_research" or not action:
            form = RepositoryResearchAddForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    with transaction.atomic():
                        title = form.cleaned_data["title"].strip()
                        authors_json_raw = form.cleaned_data.get("authors_json") or ""
                        author_list = [normalize_text_input(a).strip() for a in _parse_authors_list(authors_json_raw, request)]
                        if not author_list:
                            form.add_error("authors_json", "Please add at least one author.")
                            raise ValueError("Please add at least one author.")
                        authors_error = list_rule_error("Author names", author_list, "name")
                        if authors_error:
                            form.add_error("authors_json", authors_error)
                            raise ValueError(authors_error)
                        document = form.cleaned_data.get("document")
                        document_hash = file_sha256(document) if document else ""
                        file_error = duplicate_file_error(document_hash, request.user)
                        title_error = duplicate_title_error(title, request.user)
                        if file_error:
                            form.add_error("document", file_error)
                        if title_error:
                            form.add_error("title", title_error)
                        if file_error or title_error:
                            raise ValueError(file_error or title_error)
                        text_layer = read_text_layer(document)
                        food_check = check_uploaded_research(
                            document, title, form.cleaned_data.get("abstract"), form.cleaned_data.get("keywords"),
                            text=text_layer["text"],
                        )
                        if not food_check["is_food"]:
                            food_error = not_food_research_error(food_check)
                            form.add_error("document", food_error)
                            raise ValueError(food_error)
                        # Only finished research is accepted. Staff may still add a
                        # scanned copy (e.g. an old printed thesis) that can't be checked.
                        completeness = assess_document(text_layer)
                        if completeness["status"] == "incomplete":
                            incomplete_error = incomplete_research_error(completeness)
                            form.add_error("document", incomplete_error)
                            raise ValueError(incomplete_error)
                        completeness_unverified = completeness["status"] == "unverified"
                        authors = ", ".join(author_list)
                        abstract = form.cleaned_data["abstract"]
                        adviser = (form.cleaned_data.get("adviser") or "").strip()
                        published_month_raw = (form.cleaned_data.get("published_month") or "").strip() or None
                        published_year_raw = form.cleaned_data.get("published_year")
                        published_month = published_month_raw if published_month_raw in [
                            "January","February","March","April","May","June",
                            "July","August","September","October","November","December"
                        ] else None
                        if isinstance(published_year_raw, int) and 1990 <= published_year_raw <= 2199:
                            published_year = published_year_raw
                        else:
                            published_year = None
                        category = form.cleaned_data.get("category")
                        keywords = (form.cleaned_data.get("keywords") or "").strip()

                        if document:
                            submission = ResearchSubmission(
                                student=request.user,
                                title=title,
                                authors=authors,
                                abstract=abstract,
                                keywords=keywords,
                                food_category=category,
                                document=document,
                                document_hash=document_hash,
                                status=ResearchSubmissionStatus.APPROVED,
                                admin_notes=f"Directly added to repository by {actor_label}.",
                                reviewed_at=timezone.now(),
                            )
                            submission.save()
                            # Prepare the AI model's meaning vectors for future checks.
                            transaction.on_commit(lambda pk=submission.pk: semantic.index_in_background(pk))

                        paper_defaults = {
                            "abstract": abstract,
                            "keywords": keywords,
                            "adviser": adviser,
                            "food_category": category,
                            "published_month": published_month,
                            "published_year": published_year,
                        }
                        ResearchPaper.objects.update_or_create(
                            title=title,
                            authors=authors,
                            defaults=paper_defaults,
                        )

                    saved_title = title
                    form_submitted = True
                    form = RepositoryResearchAddForm()
                    _parts = [f"authors: {authors}"]
                    if adviser:
                        _parts.append(f"adviser: {adviser}")
                    if published_month and published_year:
                        _parts.append(f"published: {published_month} {published_year}")
                    elif published_month:
                        _parts.append(f"published month: {published_month}")
                    elif published_year:
                        _parts.append(f"published year: {published_year}")
                    if completeness_unverified:
                        _parts.append("completeness not checked: scanned copy")
                    _log_system_event(
                        request,
                        request.user,
                        SystemLogType.ACTIVITY,
                        f"{actor_label} added research directly to the repository: '{title}' ({', '.join(_parts)}).",
                    )
                except ValueError as exc:
                    saved_error = str(exc)
                except Exception as exc:
                    saved_error = str(exc)

    recent_papers = ResearchPaper.objects.order_by("-created_at")[:5]
    total_papers = ResearchPaper.objects.count()
    total_approved_submissions = ResearchSubmission.objects.filter(
        status=ResearchSubmissionStatus.APPROVED
    ).count()

    # Search bar (same as the student dashboard's) plus filters, including the
    # date a study was added to the repository.
    search_query = request.GET.get("q", "").strip()
    category_id = request.GET.get("category", "").strip()
    published_year = request.GET.get("published_year", "").strip()
    added_from = _parse_date_param(request.GET.get("added_from"))
    added_to = _parse_date_param(request.GET.get("added_to"))
    if added_from and added_to and added_from > added_to:
        added_from, added_to = added_to, added_from

    papers_qs = ResearchPaper.objects.select_related("food_category")
    if search_query:
        papers_qs = papers_qs.filter(_repository_text_filter(search_query))
    if category_id.isdigit():
        papers_qs = papers_qs.filter(food_category_id=category_id)
    if published_year.isdigit():
        papers_qs = papers_qs.filter(published_year=int(published_year))
    if added_from:
        papers_qs = papers_qs.filter(created_at__date__gte=added_from)
    if added_to:
        papers_qs = papers_qs.filter(created_at__date__lte=added_to)
    matched_papers = list(papers_qs.order_by("-created_at"))
    if search_query:
        # Best match first; equally good matches stay newest-first.
        matched_papers.sort(
            key=lambda p: _repository_relevance(search_query, p.title, p.keywords, p.authors, p.adviser, p.abstract),
            reverse=True,
        )
    page_obj = Paginator(matched_papers, REPOSITORY_ADMIN_PAGE_SIZE).get_page(request.GET.get("page"))
    filter_values = {
        "q": search_query,
        "category": category_id,
        "published_year": published_year,
        "added_from": added_from.isoformat() if added_from else "",
        "added_to": added_to.isoformat() if added_to else "",
    }
    filter_params = urlencode({key: value for key, value in filter_values.items() if value})

    paper_rows = []
    for paper in page_obj:
        doc_sub = ResearchSubmission.objects.filter(
            title=paper.title,
            status=ResearchSubmissionStatus.APPROVED,
            document__gt=""
        ).first()
        doc_url = ""
        doc_name = ""
        doc_type = ""
        if doc_sub and doc_sub.document:
            try:
                doc_url = reverse("open_submission_document", args=[doc_sub.pk])
                doc_name = str(doc_sub.document.name.split("/")[-1])
                lower = doc_name.lower()
                if lower.endswith(".pdf"):
                    doc_type = "PDF"
                elif lower.endswith(".docx"):
                    doc_type = "DOCX"
                elif lower.endswith(".txt"):
                    doc_type = "TXT"
                else:
                    doc_type = "Document"
            except Exception:
                pass
        added = timezone.localtime(paper.created_at)
        published_label = " ".join(
            part for part in ((paper.published_month or ""), str(paper.published_year or "")) if part
        ) or (paper.published_date.strftime("%b %d, %Y") if paper.published_date else "")
        paper_rows.append({
            "id": paper.pk,
            "title": paper.title,
            "authors": paper.authors,
            "adviser": getattr(paper, "adviser", "") or "",
            "abstract": paper.abstract,
            "keywords": paper.keywords or "",
            "published_date": paper.published_date.strftime("%b %d, %Y") if paper.published_date else "",
            "published_month": getattr(paper, "published_month", "") or "",
            "published_year": getattr(paper, "published_year", "") or "",
            "created_at": added.strftime("%b %d, %Y"),
            "created_time": added.strftime("%I:%M %p").lstrip("0"),
            "published_label": published_label,
            "category": paper.food_category.name if paper.food_category else "",
            "has_document": bool(doc_sub and doc_sub.document),
            "doc_url": doc_url,
            "doc_name": doc_name,
            "doc_type": doc_type,
        })

    context = {
        "page_title": "Research Repository",
        "is_super_admin": is_super_admin,
        "can_add_research": can_add_research,
        "admin_role": "Super Admin" if is_super_admin else "Admin",
        "form": form,
        "form_submitted": form_submitted,
        "saved_title": saved_title,
        "saved_error": saved_error,
        "action_message": action_message,
        "action_error": action_error,
        "recent_papers": recent_papers,
        "all_papers": paper_rows,
        "total_papers": total_papers,
        "total_approved_submissions": total_approved_submissions,
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "search_query": search_query,
        "category_id": category_id,
        "published_year": published_year,
        "added_from": filter_values["added_from"],
        "added_to": filter_values["added_to"],
        "categories": FoodCategory.objects.filter(parent__isnull=True),
        "published_years": _repository_search_published_years(),
        "search_suggestions": _repository_search_suggestions(),
        "filters_active": bool(filter_params),
        "filter_params": filter_params,
        "page_obj": page_obj,
    }
    return render(request, "core/admin_repository_add_research.html", context)


@login_required(login_url="login")
@ensure_csrf_cookie
def student_submissions_view(request):
    redirect_response = _student_only_or_redirect(request)
    if redirect_response:
        return redirect_response

    # Submitting research is independent of the Similarity Check — that page
    # remains a separate, optional tool. Upload happens directly here, same
    # pattern as the Admin's Add Research File: upload -> auto-extract (AJAX)
    # -> review editable fields -> submit.
    form = ResearchSubmissionForm(request.POST or None, request.FILES or None, include_document_field=True)
    form_submitted = False
    submission_name = ""

    if request.method == "POST":
        if form.is_valid():
            # Authors are always the account's registered members — never taken
            # from the uploaded file or free-typed, so the byline can't drift
            # from who's actually registered under this account.
            author_list = group_member_names(request.user)
            document = form.cleaned_data.get("document")
            document_hash = file_sha256(document) if document else ""
            file_error = duplicate_file_error(document_hash, request.user)
            title_error = duplicate_title_error(form.cleaned_data.get("title"), request.user)
            if file_error:
                form.add_error("document", file_error)
            if title_error:
                form.add_error("title", title_error)
            content_error = ""
            if document and not file_error:
                text_layer = read_text_layer(document)
                food_check = check_uploaded_research(
                    document, form.cleaned_data.get("title"), form.cleaned_data.get("abstract"),
                    form.cleaned_data.get("keywords"), text=text_layer["text"],
                )
                if not food_check["is_food"]:
                    content_error = not_food_research_error(food_check)
                else:
                    # Only finished research is accepted. A scanned copy can't be
                    # checked, so students are asked for the original file.
                    completeness = assess_document(text_layer)
                    if completeness["status"] == "incomplete":
                        content_error = incomplete_research_error(completeness)
                    elif completeness["status"] == "unverified":
                        content_error = UNVERIFIED_RESEARCH_ERROR
                if content_error:
                    form.add_error("document", content_error)
            if not author_list:
                form.add_error(None, "Your account has no registered members to list as authors. Please update your profile first.")
            elif not (file_error or title_error or content_error):
                submission = form.save(commit=False)
                submission.document_hash = document_hash
                submission.student = request.user
                submission.status = ResearchSubmissionStatus.PENDING
                submission.authors = ", ".join(author_list)
                submission.food_category = form.cleaned_data["category"]
                submission.save()
                submission_name = submission.title
                form_submitted = True
                form = ResearchSubmissionForm(include_document_field=True)
                _log_system_event(
                    request,
                    request.user,
                    SystemLogType.ACTIVITY,
                    f"Student submitted research for adviser review: '{submission_name}' (pending).",
                )
                notify(
                    staff_with_module(AdminModule.MANAGE_SUBMISSIONS),
                    NotificationCategory.SUBMISSION,
                    "New research submission",
                    f"{account_display_name(request.user)} submitted '{submission_name}' for review.",
                    "admin_manage_submissions",
                )

    submissions = ResearchSubmission.objects.filter(student=request.user)
    context = {
        "page_title": "My Submissions",
        "form": form,
        "form_submitted": form_submitted,
        "submission_name": submission_name,
        "student_name": account_display_name(request.user),
        "student_role": "Student",
        "group_members": group_member_names(request.user),
        "submissions": submissions,
        "stats": {
            "total_submissions": submissions.count(),
            "approved": submissions.filter(status=ResearchSubmissionStatus.APPROVED).count(),
            "pending": submissions.filter(status=ResearchSubmissionStatus.PENDING).count(),
        },
    }
    return render(request, "core/student_submissions.html", context)


@login_required(login_url="login")
def manage_submissions_view(request):
    redirect_response = _admin_module_or_denied(request, AdminModule.MANAGE_SUBMISSIONS)
    if redirect_response:
        return redirect_response

    action_message = ""
    action_error = ""

    if request.method == "POST":
        submission = get_object_or_404(ResearchSubmission, pk=request.POST.get("submission_id"))
        action = request.POST.get("action")
        admin_notes = request.POST.get("admin_notes", "").strip()
        actor_label = "Super Admin" if request.user.is_superuser else "Admin"

        if action == "approve":
            if submission.status == ResearchSubmissionStatus.APPROVED:
                action_message = f'"{submission.title}" is already approved.'
            else:
                try:
                    with transaction.atomic():
                        submission.status = ResearchSubmissionStatus.APPROVED
                        submission.admin_notes = admin_notes
                        submission.reviewed_at = timezone.now()
                        submission.drive_file_id = ""
                        submission.drive_file_url = ""
                        submission.save()
                        # Prepare the AI model's meaning vectors for future checks.
                        transaction.on_commit(lambda pk=submission.pk: semantic.index_in_background(pk))

                        ResearchPaper.objects.update_or_create(
                            title=submission.title,
                            authors=submission.authors.strip()
                            or account_display_name(submission.student),
                            defaults={
                                "abstract": submission.abstract,
                                "keywords": submission.keywords,
                                "adviser": submission.adviser,
                                "food_category": submission.food_category,
                                "published_date": submission.published_date,
                                "published_month": submission.published_month,
                                "published_year": submission.published_year,
                            },
                        )
                    action_message = f'"{submission.title}" was approved and added to the system repository.'
                    _log_system_event(
                        request,
                        request.user,
                        SystemLogType.ACTIVITY,
                        f"{actor_label} approved submission: '{submission.title}' by {account_display_name(submission.student)}.",
                    )
                    notify(
                        [submission.student],
                        NotificationCategory.REVIEW,
                        "Submission approved",
                        f"'{submission.title}' was approved and added to the research repository."
                        + (f" Notes: {admin_notes}" if admin_notes else ""),
                        "student_submissions",
                    )
                except Exception as exc:
                    action_error = str(exc)
        elif action == "reject":
            submission.status = ResearchSubmissionStatus.REJECTED
            submission.admin_notes = admin_notes
            submission.reviewed_at = timezone.now()
            submission.save(update_fields=["status", "admin_notes", "reviewed_at", "updated_at"])
            action_message = f'"{submission.title}" was marked as rejected.'
            _log_system_event(
                request,
                request.user,
                SystemLogType.ACTIVITY,
                f"{actor_label} rejected submission: '{submission.title}' by {account_display_name(submission.student)}.",
            )
            notify(
                [submission.student],
                NotificationCategory.REVIEW,
                "Submission rejected",
                f"'{submission.title}' was not approved."
                + (f" Notes: {admin_notes}" if admin_notes else ""),
                "student_submissions",
            )
        # Back to the same tab / search / page the review was made from.
        return _redirect_with_result(
            request, "admin_manage_submissions", action_message, action_error,
            query=_manage_submissions_query(request.GET),
        )

    action_message, action_error = _pop_result_messages(request)
    filters = _manage_submissions_filters(request.GET)

    base = ResearchSubmission.objects.select_related("student", "student__registration_profile", "food_category")
    if not request.user.is_superuser:
        base = base.exclude(student__is_superuser=True)
    counts = {"all": base.count()}
    for key, status_value in SUBMISSION_STATUS_TABS.items():
        if status_value:
            counts[key] = base.filter(status=status_value).count()

    # Same filters as the Research Repository, plus the review status.
    submissions = base
    if SUBMISSION_STATUS_TABS[filters["status"]]:
        submissions = submissions.filter(status=SUBMISSION_STATUS_TABS[filters["status"]])
    if filters["q"]:
        query = filters["q"]
        submissions = submissions.filter(
            _repository_text_filter(query)
            | Q(student__first_name__icontains=query)
            | Q(student__last_name__icontains=query)
            | Q(student__username__icontains=query)
            | Q(student__registration_profile__group_name__icontains=query)
        )
    if filters["category"]:
        submissions = submissions.filter(food_category_id=filters["category"])
    if filters["published_year"]:
        submissions = submissions.filter(published_year=int(filters["published_year"]))
    if filters["submitted_from"]:
        submissions = submissions.filter(submitted_at__date__gte=filters["submitted_from"])
    if filters["submitted_to"]:
        submissions = submissions.filter(submitted_at__date__lte=filters["submitted_to"])
    # Submissions waiting for review always come first, newest first after that.
    submissions = submissions.annotate(
        review_order=Case(
            When(status=ResearchSubmissionStatus.PENDING, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by("review_order", "-submitted_at")
    page_obj = Paginator(submissions, MANAGE_SUBMISSIONS_PAGE_SIZE).get_page(request.GET.get("page"))

    rows = []
    for submission in page_obj:
        submitted = timezone.localtime(submission.submitted_at)
        reviewed = timezone.localtime(submission.reviewed_at) if submission.reviewed_at else None
        rows.append({
            "id": submission.pk,
            "title": submission.title,
            "student": account_display_name(submission.student),
            "authors": submission.authors,
            "adviser": submission.adviser,
            "abstract": submission.abstract,
            "keywords": submission.keywords,
            "category": submission.food_category.name if submission.food_category else "",
            "published": " ".join(
                part for part in ((submission.published_month or ""), str(submission.published_year or "")) if part
            ),
            "status": submission.status,
            "status_key": submission.status.lower(),
            "submitted_date": submitted.strftime("%b %d, %Y"),
            "submitted_time": submitted.strftime("%I:%M %p").lstrip("0"),
            "reviewed_date": reviewed.strftime("%b %d, %Y") if reviewed else "",
            "notes": submission.admin_notes,
            "file_url": reverse("open_submission_document", args=[submission.pk]) if submission.document else "",
            "doc_type": _document_type_label(submission.document) if submission.document else "",
        })

    status_labels = {"all": "All statuses", "pending": "Pending", "approved": "Approved", "rejected": "Rejected"}
    filter_params = _manage_submissions_query(request.GET, keep_page=False)
    context = {
        "page_title": "Manage Submissions",
        "is_super_admin": request.user.is_superuser,
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "admin_role": "Super Admin" if request.user.is_superuser else "Admin",
        "rows": rows,
        "page_obj": page_obj,
        "status_key": filters["status"],
        "search_query": filters["q"],
        "category_id": filters["category"],
        "published_year": filters["published_year"],
        "submitted_from": filters["submitted_from"].isoformat() if filters["submitted_from"] else "",
        "submitted_to": filters["submitted_to"].isoformat() if filters["submitted_to"] else "",
        "status_options": [
            {"key": key, "label": status_labels[key], "count": counts[key]} for key in SUBMISSION_STATUS_TABS
        ],
        "counts": counts,
        "categories": FoodCategory.objects.filter(parent__isnull=True),
        "published_years": sorted(
            set(base.exclude(published_year__isnull=True).values_list("published_year", flat=True)), reverse=True
        ),
        "search_suggestions": _submission_search_suggestions(base),
        "filter_params": filter_params,
        "filters_active": bool(filter_params),
        "action_message": action_message,
        "action_error": action_error,
    }
    return render(request, "core/admin_manage_submissions.html", context)


def _manage_submissions_filters(params):
    """Manage Submissions filters from the query string, cleaned up."""
    status = params.get("status") or "all"
    if status not in SUBMISSION_STATUS_TABS:
        status = "all"
    category = (params.get("category") or "").strip()
    year = (params.get("published_year") or "").strip()
    submitted_from = _parse_date_param(params.get("submitted_from"))
    submitted_to = _parse_date_param(params.get("submitted_to"))
    if submitted_from and submitted_to and submitted_from > submitted_to:
        submitted_from, submitted_to = submitted_to, submitted_from
    return {
        "q": (params.get("q") or "").strip(),
        "status": status,
        "category": category if category.isdigit() else "",
        "published_year": year if year.isdigit() else "",
        "submitted_from": submitted_from,
        "submitted_to": submitted_to,
    }


def _manage_submissions_query(params, keep_page=True):
    """The filters (and page) of Manage Submissions as a safe query string."""
    filters = _manage_submissions_filters(params)
    kept = {
        "q": filters["q"],
        "status": "" if filters["status"] == "all" else filters["status"],
        "category": filters["category"],
        "published_year": filters["published_year"],
        "submitted_from": filters["submitted_from"].isoformat() if filters["submitted_from"] else "",
        "submitted_to": filters["submitted_to"].isoformat() if filters["submitted_to"] else "",
    }
    if keep_page and (params.get("page") or "").isdigit():
        kept["page"] = params.get("page")
    return urlencode({key: value for key, value in kept.items() if value})


def _submission_search_suggestions(submissions, limit=60, rows=80):
    """Typeahead for the Manage Submissions search bar: titles, group names and
    keywords of the submissions this reviewer can see."""
    suggestions, seen = [], set()

    def add(value):
        cleaned = (value or "").strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            suggestions.append(cleaned)

    for title, keywords, group in submissions.order_by("-submitted_at").values_list(
        "title", "keywords", "student__registration_profile__group_name"
    )[:rows]:
        add(title)
        add(group)
        for keyword in (keywords or "").split(","):
            add(keyword)
        if len(suggestions) >= limit:
            break
    return suggestions[:limit]


CATALOG_NAME_LIMITS = {"college": 120, "program": 255}


@login_required(login_url="login")
def settings_programs_view(request):
    redirect_response = _admin_module_or_denied(request, AdminModule.PROGRAMS_COURSES)
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        message, error = _handle_catalog_action(request, action)
        return _redirect_with_result(request, "admin_settings_programs", message, error)

    action_message, action_error = _pop_result_messages(request)
    colleges = list(College.objects.order_by("name"))
    programs = list(Program.objects.select_related("college").order_by("name"))
    # One table: each college, then the programs under it. Programs with no college go last.
    groups = [
        {"college": college, "programs": [p for p in programs if p.college_id == college.pk]}
        for college in colleges
    ]
    context = {
        "page_title": "Programs & Colleges",
        "is_super_admin": request.user.is_superuser,
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "admin_role": "Super Admin" if request.user.is_superuser else "Admin",
        "action_message": action_message,
        "action_error": action_error,
        "groups": groups,
        "unassigned_programs": [p for p in programs if p.college_id is None],
        "college_options": [c for c in colleges if c.is_active],
        "college_count": len(colleges),
        "program_count": len(programs),
    }
    return render(request, "core/settings_programs.html", context)


def _catalog_item(model, raw_id):
    try:
        return model.objects.get(pk=int(raw_id))
    except (TypeError, ValueError, model.DoesNotExist):
        return None


def _handle_catalog_action(request, action):
    """Add, rename, move and activate colleges and programs. Returns (message, error)."""
    if action in ("add_college", "edit_college", "toggle_college"):
        kind, model, label = "college", College, "College"
    elif action in ("add_program", "edit_program", "toggle_program"):
        kind, model, label = "program", Program, "Program"
    else:
        return "", "Unknown action."

    if action.startswith("toggle_"):
        item = _catalog_item(model, request.POST.get(f"{kind}_id"))
        if not item:
            return "", f"{label} not found."
        item.is_active = not item.is_active
        item.save(update_fields=["is_active"])
        state = "activated" if item.is_active else "deactivated"
        _log_system_event(request, request.user, SystemLogType.ACTIVITY, f"{label} '{item.name}' {state} in Settings.")
        note = "" if item.is_active else " It stays on existing records but can no longer be picked on sign-up."
        return f"{label} '{item.name}' was {state}.{note}", ""

    name = " ".join(request.POST.get("name", "").split())[: CATALOG_NAME_LIMITS[kind]]
    if not name:
        return "", f"Please enter the {kind} name."
    clashes = model.objects.filter(name__iexact=name)

    college = None
    if kind == "program" and request.POST.get("college_id", ""):
        college = _catalog_item(College, request.POST.get("college_id"))
        if not college:
            return "", "Please choose a valid college."

    if action.startswith("add_"):
        if clashes.exists():
            return "", f"'{name}' already exists."
        if kind == "college":
            model.objects.create(name=name)
        else:
            model.objects.create(name=name, college=college)
        _log_system_event(request, request.user, SystemLogType.ACTIVITY, f"Added {kind} '{name}' in Settings.")
        return f"{label} '{name}' was added.", ""

    item = _catalog_item(model, request.POST.get(f"{kind}_id"))
    if not item:
        return "", f"{label} not found."
    if clashes.exclude(pk=item.pk).exists():
        return "", f"'{name}' already exists."

    old_name = item.name
    with transaction.atomic():
        item.name = name
        if kind == "program":
            item.college = college
            item.save(update_fields=["name", "college"])
        else:
            item.save(update_fields=["name"])
        # Profiles store the name as text, so keep them matching a rename.
        if old_name != name:
            if kind == "college":
                RegistrationProfile.objects.filter(college=old_name).update(college=name)
            else:
                RegistrationProfile.objects.filter(program=old_name).update(program=name)
    _log_system_event(request, request.user, SystemLogType.ACTIVITY, f"Updated {kind} '{old_name}' to '{name}' in Settings.")
    return f"{label} '{name}' was saved.", ""


@login_required(login_url="login")
def system_logs_view(request):
    redirect_response = _admin_module_or_denied(request, AdminModule.SYSTEM_LOGS)
    if redirect_response:
        return redirect_response

    is_super_admin = request.user.is_superuser
    active_type = request.GET.get("type", "login").strip().lower()
    if active_type not in ("login", "activity"):
        active_type = "login"
    # Staff Admins never see Super Admin logs, so they can't filter by that role either.
    allowed_roles = ("super_admin", "admin", "student") if is_super_admin else ("admin", "student")
    filters = _log_filters(request.GET, allowed_roles)
    search_query = filters["q"]

    base_logs = SystemLog.objects.select_related("user").all()
    if not is_super_admin:
        # Staff Admins only see Admin and Student logs. Super Admin logs (and
        # user-less entries such as the emergency account) are excluded.
        base_logs = base_logs.filter(user__isnull=False, user__is_superuser=False)
    base_logs = _apply_log_role_and_dates(base_logs, filters)

    if search_query:
        base_logs = base_logs.filter(
            Q(action__icontains=search_query)
            | Q(user__username__icontains=search_query)
            | Q(user__email__icontains=search_query)
            | Q(user__first_name__icontains=search_query)
            | Q(user__last_name__icontains=search_query)
        )

    login_log_types = (SystemLogType.LOGIN, SystemLogType.LOGOUT)
    login_logs = base_logs.filter(log_type__in=login_log_types)
    activity_logs = base_logs.exclude(log_type__in=login_log_types)
    logs = login_logs if active_type == "login" else activity_logs

    paginator = Paginator(logs, SYSTEM_LOGS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    events = [
        {
            "timestamp": timezone.localtime(log.created_at).strftime("%b %d, %Y %I:%M:%S %p"),
            "user_name": log.user_display_name(),
            "user_role": log.user_role_label(),
            "log_type": log.log_type,
            "action": log.action,
            "ip_address": log.ip_address or "N/A",
        }
        for log in page_obj
    ]
    login_count = login_logs.count()
    activity_count = activity_logs.count()

    context = {
        "page_title": "System Logs",
        "is_super_admin": is_super_admin,
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "admin_role": "Super Admin" if is_super_admin else "Admin",
        "active_type": active_type,
        "events": events,
        "page_obj": page_obj,
        "login_count": login_count,
        "activity_count": activity_count,
        "total_logs_count": login_count + activity_count,
        "role_options": [(key, LOG_ROLE_FILTERS[key][0]) for key in allowed_roles],
        **_log_page_context(filters, page_obj),
    }
    return render(request, "core/system_logs.html", context)


@login_required(login_url="login")
def privilege_and_access_control_view(request):
    redirect_response = _super_admin_module_or_denied(request, "Privilege & Access Control")
    if redirect_response:
        return redirect_response

    action_message = ""
    action_error = ""

    if request.method == "POST":
        user_id = request.POST.get("user_id")
        action = request.POST.get("action")
        target_user = get_object_or_404(User, pk=user_id)
        target_name = target_user.get_full_name().strip() or target_user.username

        if not target_user.is_staff:
            action_error = "Privileges are only managed for Admin accounts."
        elif target_user.pk == request.user.pk:
            action_error = "You cannot modify your own role, privileges, or account status."
        elif action == "save_modules":
            if target_user.is_superuser:
                action_error = "Super Admins already have access to every module."
            else:
                valid = set(AdminModule.values)
                selected = {m for m in request.POST.getlist("modules") if m in valid}
                # Adding research happens on the Research Repository page, so it can't stand alone.
                if AdminModule.ADD_RESEARCH in selected:
                    selected.add(AdminModule.RESEARCH_REPOSITORY)
                current = set(
                    AdminModuleAccess.objects.filter(user=target_user).values_list("module", flat=True)
                )
                to_grant = selected - current
                to_revoke = current - selected
                with transaction.atomic():
                    AdminModuleAccess.objects.filter(user=target_user, module__in=to_revoke).delete()
                    AdminModuleAccess.objects.bulk_create(
                        [AdminModuleAccess(user=target_user, module=m, granted_by=request.user) for m in to_grant]
                    )
                if not to_grant and not to_revoke:
                    action_message = f"No changes to the module privileges of '{target_name}'."
                else:
                    granted_labels = ", ".join(sorted(AdminModule(m).label for m in to_grant)) or "none"
                    revoked_labels = ", ".join(sorted(AdminModule(m).label for m in to_revoke)) or "none"
                    action_message = f"Module privileges updated for '{target_name}'."
                    _log_system_event(
                        request,
                        request.user,
                        SystemLogType.ACTIVITY,
                        f"Super Admin updated module privileges for: {target_name} (email: {target_user.email}). "
                        f"Granted: {granted_labels}. Revoked: {revoked_labels}.",
                    )
                    notify(
                        [target_user],
                        NotificationCategory.PRIVILEGE,
                        "Your module access was updated",
                        f"Granted: {granted_labels}. Revoked: {revoked_labels}.",
                        "admin_dashboard",
                    )
        elif action == "make_super_admin":
            target_user.is_superuser = True
            target_user.save(update_fields=["is_superuser"])
            AdminModuleAccess.objects.filter(user=target_user).delete()
            action_message = f"'{target_name}' has been promoted to Super Admin."
            _log_system_event(
                request,
                request.user,
                SystemLogType.ACTIVITY,
                f"Super Admin promoted: {target_name} (email: {target_user.email}) to Super Admin.",
            )
        elif action == "revoke_admin":
            target_user.is_staff = False
            target_user.is_superuser = False
            target_user.save(update_fields=["is_staff", "is_superuser"])
            AdminModuleAccess.objects.filter(user=target_user).delete()
            action_message = f"'{target_name}' has had admin privileges revoked."
            _log_system_event(
                request,
                request.user,
                SystemLogType.ACTIVITY,
                f"Super Admin revoked admin privileges from: {target_name} (email: {target_user.email}).",
            )
        elif action == "toggle_active":
            make_active = _requested_active_state(request, target_user)
            reason = _clean_status_reason(request)
            if make_active == target_user.is_active:
                action_message = f"Account '{target_name}' is already {'active' if make_active else 'deactivated'}."
            elif not make_active and not reason:
                action_error = "Please give a reason for deactivating this account."
            else:
                action_message, email_warning = _set_account_active(
                    request, target_user, make_active, reason, "Super Admin"
                )
                if email_warning:
                    action_error = email_warning
        else:
            action_error = "Unknown action."

    if request.method == "POST":
        return _redirect_with_result(request, "admin_privilege_access_control", action_message, action_error)
    action_message, action_error = _pop_result_messages(request)

    admin_users = list(User.objects.filter(is_staff=True).order_by("-is_superuser", "-date_joined"))
    granted_by_user = {}
    for owner_id, module in AdminModuleAccess.objects.filter(user__in=admin_users).values_list("user_id", "module"):
        granted_by_user.setdefault(owner_id, set()).add(module)

    user_rows = []
    for user in admin_users:
        granted = granted_by_user.get(user.pk, set())
        module_groups = [
            {
                "label": group_label,
                "modules": [
                    {"value": module.value, "label": module.label, "granted": module.value in granted}
                    for module in modules
                ],
            }
            for group_label, modules in ADMIN_MODULE_GROUPS
        ]
        user_rows.append(
            {
                "id": user.pk,
                "name": account_display_name(user),
                "email": user.email,
                "is_active": user.is_active,
                "is_superuser": user.is_superuser,
                "module_groups": module_groups,
                "granted_count": len(granted),
                "date_joined": timezone.localtime(user.date_joined).strftime("%b %d, %Y") if user.date_joined else "N/A",
                "is_self": user.pk == request.user.pk,
            }
        )

    context = {
        "page_title": "Privilege and Access Control",
        "is_super_admin": True,
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "admin_role": "Super Admin",
        "user_rows": user_rows,
        "total_module_count": len(AdminModule.values),
        "total_super_admins": sum(1 for row in user_rows if row["is_superuser"]),
        "total_admins": sum(1 for row in user_rows if not row["is_superuser"]),
        "active_accounts": sum(1 for row in user_rows if row["is_active"]),
        "inactive_accounts": sum(1 for row in user_rows if not row["is_active"]),
        "action_message": action_message,
        "action_error": action_error,
    }
    return render(request, "core/privilege_access_control.html", context)


def _reports_filtered_submissions(request):
    qs = ResearchSubmission.objects.select_related(
        "student", "student__registration_profile"
    ).order_by("-submitted_at")

    status = request.GET.get("sub_status", "").strip()
    program = request.GET.get("sub_program", "").strip()
    college = request.GET.get("sub_college", "").strip()
    date_from = request.GET.get("sub_date_from", "").strip()
    date_to = request.GET.get("sub_date_to", "").strip()

    if status:
        qs = qs.filter(status=status)
    if program:
        qs = qs.filter(student__registration_profile__program=program)
    if college:
        qs = qs.filter(student__registration_profile__college=college)
    if date_from:
        qs = qs.filter(submitted_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(submitted_at__date__lte=date_to)
    return qs


def _reports_filtered_repository(request):
    qs = ResearchPaper.objects.order_by("-created_at")

    year = request.GET.get("repo_year", "").strip()
    month = request.GET.get("repo_month", "").strip()

    if year:
        qs = qs.filter(published_year=year)
    if month:
        qs = qs.filter(published_month=month)
    return qs


def _reports_filtered_users(request):
    qs = User.objects.select_related("registration_profile").order_by("-date_joined")

    role = request.GET.get("user_role", "").strip()
    active = request.GET.get("user_active", "").strip()

    if role == "student":
        qs = qs.filter(is_staff=False, is_superuser=False)
    elif role == "admin":
        qs = qs.filter(is_staff=True, is_superuser=False)
    elif role == "super_admin":
        qs = qs.filter(is_superuser=True)

    if active == "active":
        qs = qs.filter(is_active=True)
    elif active == "inactive":
        qs = qs.filter(is_active=False)
    return qs


@login_required(login_url="login")
def reports_view(request):
    redirect_response = _admin_module_or_denied(request, AdminModule.REPORTS)
    if redirect_response:
        return redirect_response

    today = timezone.localdate()

    # --- Submissions per month (last 12 months), stacked by status ---
    month_starts = []
    year, month = today.year, today.month
    for _ in range(REPORTS_MONTHS_SHOWN):
        month_starts.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    month_starts.reverse()
    first_year, first_month = month_starts[0]
    window_start = timezone.make_aware(datetime(first_year, first_month, 1))

    status_order = [
        ResearchSubmissionStatus.APPROVED,
        ResearchSubmissionStatus.PENDING,
        ResearchSubmissionStatus.REJECTED,
    ]
    monthly_counts = {(y, m): {status: 0 for status in status_order} for y, m in month_starts}
    window_rows = (
        ResearchSubmission.objects.filter(submitted_at__gte=window_start)
        .annotate(month=TruncMonth("submitted_at"))
        .values_list("month", "status")
        .annotate(n=Count("id"))
    )
    for month_value, status, n in window_rows:
        key = (month_value.year, month_value.month)
        if key in monthly_counts and status in monthly_counts[key]:
            monthly_counts[key][status] += n
    month_labels = [date(y, m, 1).strftime("%b %Y") for y, m in month_starts]
    submissions_by_month = {
        "labels": month_labels,
        "series": [
            {"label": status.label, "key": status.value.lower(), "values": [monthly_counts[k][status] for k in month_starts]}
            for status in status_order
        ],
    }
    submissions_month_rows = [
        {"label": label, "values": [monthly_counts[k][status] for status in status_order], "total": sum(monthly_counts[k].values())}
        for label, k in zip(month_labels, month_starts)
    ]

    # --- Similarity level distribution (all checks ever run) ---
    level_counts = dict(
        SimilarityCheckRecord.objects.values_list("similarity_level").annotate(n=Count("id"))
    )
    similarity_levels = [
        {"key": "low", "label": f"Low ({SIMILARITY_RANGES['low']})", "count": level_counts.get("low", 0)},
        {"key": "moderate", "label": f"Moderate ({SIMILARITY_RANGES['moderate']})", "count": level_counts.get("moderate", 0)},
        {"key": "high", "label": f"High ({SIMILARITY_RANGES['high']})", "count": level_counts.get("high", 0)},
    ]

    # --- Repository (papers + approved submissions, deduped like the student search) ---
    repository_rows = _all_repository_rows(request.user)

    category_totals = {}
    year_totals = {}
    for row in repository_rows:
        category_name = row["category"].name if row["category"] else "Uncategorized"
        category_totals[category_name] = category_totals.get(category_name, 0) + 1
        if row["published_year"]:
            year_totals[row["published_year"]] = year_totals.get(row["published_year"], 0) + 1
    ranked_categories = sorted(category_totals.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked_categories) > REPORTS_TOP_CATEGORIES:
        shown = ranked_categories[: REPORTS_TOP_CATEGORIES - 1]
        other_total = sum(n for _, n in ranked_categories[REPORTS_TOP_CATEGORIES - 1 :])
        ranked_categories = shown + [("Other categories", other_total)]
    research_by_category = [{"label": name, "count": n} for name, n in ranked_categories]
    repository_by_year = [{"label": str(y), "count": year_totals[y]} for y in sorted(year_totals)]

    # --- Submissions by college ---
    college_counts = dict(
        ResearchSubmission.objects.values_list("student__registration_profile__college").annotate(n=Count("id"))
    )
    submissions_by_college = [
        {
            "label": value.split(" (")[0].removeprefix("Department of "),
            "full_label": label,
            "count": college_counts.get(value, 0),
        }
        for value, label in [(name, name) for name in College.objects.order_by("name").values_list("name", flat=True)]
    ]
    not_set = sum(n for value, n in college_counts.items() if value not in set(College.objects.values_list("name", flat=True)))
    if not_set:
        submissions_by_college.append({"label": "Not set", "full_label": "College not set", "count": not_set})

    # --- Headline numbers ---
    status_totals = dict(ResearchSubmission.objects.values_list("status").annotate(n=Count("id")))
    total_submissions = sum(status_totals.values())
    approved_total = status_totals.get(ResearchSubmissionStatus.APPROVED, 0)
    rejected_total = status_totals.get(ResearchSubmissionStatus.REJECTED, 0)
    reviewed_total = approved_total + rejected_total
    check_stats = SimilarityCheckRecord.objects.aggregate(avg=Avg("top_score_percent"), n=Count("id"))

    context = {
        "page_title": "Reports & Export",
        "is_super_admin": request.user.is_superuser,
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "admin_role": "Super Admin" if request.user.is_superuser else "Admin",
        "kpi": {
            "total_submissions": total_submissions,
            "pending_submissions": status_totals.get(ResearchSubmissionStatus.PENDING, 0),
            "approval_rate": round(approved_total * 100 / reviewed_total) if reviewed_total else None,
            "reviewed_total": reviewed_total,
            "repository_total": len(repository_rows),
            "average_similarity": round(check_stats["avg"], 1) if check_stats["avg"] is not None else None,
            "total_checks": check_stats["n"],
            "high_checks": level_counts.get("high", 0),
        },
        "months_shown": REPORTS_MONTHS_SHOWN,
        "status_labels": [status.label for status in status_order],
        "submissions_month_rows": submissions_month_rows,
        "similarity_levels": similarity_levels,
        "research_by_category": research_by_category,
        "category_chart_height": max(192, len(research_by_category) * 36 + 48),
        "repository_by_year": repository_by_year,
        "submissions_by_college": submissions_by_college,
        "chart_data": {
            "submissionsByMonth": submissions_by_month,
            "similarityLevels": similarity_levels,
            "researchByCategory": research_by_category,
            "repositoryByYear": repository_by_year,
            "submissionsByCollege": submissions_by_college,
        },
    }
    return render(request, "core/admin_reports.html", context)


@login_required(login_url="login")
def export_submissions_csv(request):
    redirect_response = _admin_module_or_denied(request, AdminModule.REPORTS)
    if redirect_response:
        return redirect_response

    submissions = _reports_filtered_submissions(request)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="submissions_report.csv"'
    writer = csv.writer(response)
    writer.writerow(["Title", "Student", "Group Members", "Email", "Program", "College", "Status", "Submitted At", "Reviewed At"])
    for submission in submissions:
        profile = getattr(submission.student, "registration_profile", None)
        writer.writerow([
            submission.title,
            account_display_name(submission.student),
            "; ".join(group_member_names(submission.student)),
            submission.student.email,
            getattr(profile, "program", "") or "",
            getattr(profile, "college", "") or "",
            submission.status,
            timezone.localtime(submission.submitted_at).strftime("%Y-%m-%d %H:%M") if submission.submitted_at else "",
            timezone.localtime(submission.reviewed_at).strftime("%Y-%m-%d %H:%M") if submission.reviewed_at else "",
        ])

    _log_system_event(
        request,
        request.user,
        SystemLogType.ACTIVITY,
        "Super Admin exported the Submissions report to CSV.",
    )
    return response


@login_required(login_url="login")
def export_repository_csv(request):
    redirect_response = _admin_module_or_denied(request, AdminModule.REPORTS)
    if redirect_response:
        return redirect_response

    papers = _reports_filtered_repository(request)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="repository_report.csv"'
    writer = csv.writer(response)
    writer.writerow(["Title", "Authors", "Adviser", "Published Month", "Published Year", "Published Date", "Keywords", "Added At"])
    for paper in papers:
        writer.writerow([
            paper.title,
            paper.authors,
            paper.adviser or "",
            paper.published_month or "",
            paper.published_year or "",
            paper.published_date.isoformat() if paper.published_date else "",
            paper.keywords or "",
            timezone.localtime(paper.created_at).strftime("%Y-%m-%d %H:%M") if paper.created_at else "",
        ])

    _log_system_event(
        request,
        request.user,
        SystemLogType.ACTIVITY,
        "Super Admin exported the Research Repository report to CSV.",
    )
    return response


@login_required(login_url="login")
def export_users_csv(request):
    redirect_response = _admin_module_or_denied(request, AdminModule.REPORTS)
    if redirect_response:
        return redirect_response

    users = _reports_filtered_users(request)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="users_report.csv"'
    writer = csv.writer(response)
    writer.writerow(["Username", "Full Name", "Email", "Role", "Program", "College", "Active", "Date Joined", "Last Login"])
    for user in users:
        profile = getattr(user, "registration_profile", None)
        role = _effective_login_role_for_profile(user) or (profile.login_as if profile else "N/A")
        writer.writerow([
            user.username,
            account_display_name(user),
            user.email,
            role,
            getattr(profile, "program", "") or "",
            getattr(profile, "college", "") or "",
            "Yes" if user.is_active else "No",
            timezone.localtime(user.date_joined).strftime("%Y-%m-%d %H:%M") if user.date_joined else "",
            timezone.localtime(user.last_login).strftime("%Y-%m-%d %H:%M") if user.last_login else "",
        ])

    _log_system_event(
        request,
        request.user,
        SystemLogType.ACTIVITY,
        "Super Admin exported the Users report to CSV.",
    )
    return response


def _safe_next_url(request, fallback="dashboard_redirect"):
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return next_url
    return reverse(fallback)


@login_required(login_url="login")
def open_notification_view(request, notification_id):
    notification = get_object_or_404(Notification, pk=notification_id, recipient=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
    if notification.link:
        return redirect(notification.link)
    return redirect(_safe_next_url(request))


@login_required(login_url="login")
@require_POST
def mark_all_notifications_read_view(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return redirect(_safe_next_url(request))

# --- Landing Page Settings ---------------------------------------------------

LANDING_TABS = (
    ("general", "General & Sections"),
    ("slides", "Hero Slides"),
    ("announcements", "Announcements"),
    ("steps", "How It Works"),
    ("features", "Features"),
    ("gallery", "Gallery"),
    ("colleges", "Colleges"),
    ("faq", "FAQ"),
    ("categories", "Category Photos"),
)

LANDING_COLLECTIONS = {
    "slides": {
        "model": HeroSlide, "form": HeroSlideForm, "noun": "slide",
        "title": "headline", "subtitle": "subtitle", "image": "image", "active": "is_active",
    },
    "announcements": {
        "model": Announcement, "form": AnnouncementForm, "noun": "announcement",
        "title": "title", "subtitle": "body", "active": "is_active",
        "thumbnail": lambda obj: obj.images.first(),
        "badge": lambda obj: f"{obj.images.count()} image{'s' if obj.images.count() != 1 else ''}",
    },
    "steps": {
        "model": HowItWorksStep, "form": HowItWorksStepForm, "noun": "step",
        "title": "title", "subtitle": "description", "icon": "icon",
    },
    "features": {
        "model": LandingFeature, "form": LandingFeatureForm, "noun": "feature",
        "title": "title", "subtitle": "description", "icon": "icon",
    },
    "gallery": {
        "model": GalleryImage, "form": GalleryImageForm, "noun": "photo",
        "title": "caption", "subtitle": "alt_text", "image": "image", "active": "is_active",
    },
    "colleges": {
        "model": PartnerCollege, "form": PartnerCollegeForm, "noun": "college",
        "title": "name", "subtitle": "", "image": "logo",
    },
    "faq": {
        "model": FaqItem, "form": FaqItemForm, "noun": "question",
        "title": "question", "subtitle": "answer", "active": "is_active",
    },
    "categories": {
        "model": FoodCategory, "form": CategoryImageForm, "noun": "category photo",
        "title": "name", "subtitle": "", "image": "image",
        "queryset": lambda: FoodCategory.objects.filter(parent__isnull=True).order_by("name"),
        "can_add": False, "can_delete": False,
    },
}


def _landing_image_fields(model):
    return [f.name for f in model._meta.get_fields() if isinstance(f, models.ImageField)]


def _delete_stored_file(name, storage):
    if name:
        try:
            storage.delete(name)
        except OSError:
            logger.warning("Could not delete stored file %s", name)


@login_required(login_url="login")
def landing_settings_view(request):
    redirect_response = _admin_module_or_denied(request, AdminModule.LANDING_PAGE)
    if redirect_response:
        return redirect_response

    tab_keys = [key for key, _ in LANDING_TABS]
    tab = request.GET.get("tab", "general")
    if tab not in tab_keys:
        tab = "general"
    tab_label = dict(LANDING_TABS)[tab]
    actor_label = "Super Admin" if request.user.is_superuser else "Admin"
    tab_url = f"{reverse('admin_landing_settings')}?tab={tab}"

    settings_form = None
    item_form = None
    editing = None
    config = LANDING_COLLECTIONS.get(tab)

    if tab == "general":
        site = LandingSettings.load()
        settings_form = LandingSettingsForm(request.POST or None, instance=site)
        if request.method == "POST" and settings_form.is_valid():
            settings_form.save()
            _log_system_event(
                request, request.user, SystemLogType.ACTIVITY,
                f"{actor_label} updated the landing page general settings.",
            )
            messages.success(request, "Landing page settings saved.")
            return redirect(tab_url)
    else:
        model = config["model"]
        queryset = config["queryset"]() if "queryset" in config else model.objects.all()
        can_add = config.get("can_add", True)
        can_delete = config.get("can_delete", True)
        image_fields = _landing_image_fields(model)

        edit_id = request.POST.get("item_id") or request.GET.get("edit")
        if edit_id:
            editing = get_object_or_404(queryset, pk=edit_id)

        if request.method == "POST":
            action = request.POST.get("action", "save")
            if action == "delete" and editing is not None and can_delete:
                label = str(editing)
                files = [(getattr(editing, f).name, getattr(editing, f).storage) for f in image_fields]
                editing.delete()
                for name, storage in files:
                    _delete_stored_file(name, storage)
                _log_system_event(
                    request, request.user, SystemLogType.ACTIVITY,
                    f"{actor_label} deleted landing page {config['noun']}: '{label}'.",
                )
                messages.success(request, f"The {config['noun']} was deleted.")
                return redirect(tab_url)
            if action == "toggle" and editing is not None and config.get("active"):
                field = config["active"]
                setattr(editing, field, not getattr(editing, field))
                editing.save(update_fields=[field])
                state = "shown" if getattr(editing, field) else "hidden"
                _log_system_event(
                    request, request.user, SystemLogType.ACTIVITY,
                    f"{actor_label} {state} landing page {config['noun']}: '{editing}'.",
                )
                messages.success(request, f"The {config['noun']} is now {state}.")
                return redirect(tab_url)
            if action == "save" and (editing is not None or can_add):
                old_files = {f: getattr(editing, f).name for f in image_fields} if editing else {}
                item_form = config["form"](request.POST, request.FILES, instance=editing, session=request.session)
                if item_form.is_valid():
                    saved = item_form.save()
                    item_form.discard_used_uploads()
                    for field_name, old_name in old_files.items():
                        new_file = getattr(saved, field_name)
                        if old_name and old_name != new_file.name:
                            _delete_stored_file(old_name, new_file.storage)
                    verb = "updated" if editing else "added"
                    _log_system_event(
                        request, request.user, SystemLogType.ACTIVITY,
                        f"{actor_label} {verb} landing page {config['noun']}: '{saved}'.",
                    )
                    messages.success(request, f"The {config['noun']} was {verb}.")
                    return redirect(tab_url)
                item_form.stash_uploads()
        if item_form is None and (editing is not None or can_add):
            initial = {}
            if editing is None and model is Announcement:
                initial["publish_date"] = timezone.localdate()
            item_form = config["form"](instance=editing, initial=initial)

    items = []
    if config:
        for obj in (config["queryset"]() if "queryset" in config else config["model"].objects.all()):
            image_name = config.get("image")
            if "thumbnail" in config:
                thumbnail = config["thumbnail"](obj)
                image_file = thumbnail.image if thumbnail else None
            else:
                image_file = getattr(obj, image_name) if image_name else None
            subtitle_field = config.get("subtitle")
            active_field = config.get("active")
            items.append({
                "id": obj.pk,
                "title": getattr(obj, config["title"]) or str(obj),
                "subtitle": getattr(obj, subtitle_field) if subtitle_field else "",
                "image_url": image_file.url if image_file else "",
                "has_image_field": bool(image_name) or "thumbnail" in config,
                "badge": config["badge"](obj) if "badge" in config else "",
                "icon": getattr(obj, config["icon"]) if config.get("icon") else "",
                "order": getattr(obj, "order", None),
                "is_active": getattr(obj, active_field) if active_field else None,
                "is_editing": editing is not None and editing.pk == obj.pk,
            })

    context = {
        "page_title": "Landing Page Settings",
        "is_super_admin": request.user.is_superuser,
        "admin_name": request.user.get_full_name().strip() or request.user.username,
        "admin_role": "Super Admin" if request.user.is_superuser else "Admin",
        "tabs": LANDING_TABS,
        "tab": tab,
        "tab_label": tab_label,
        "settings_form": settings_form,
        "item_form": item_form,
        "editing": editing,
        "items": items,
        "noun": config["noun"] if config else "",
        "can_add": config.get("can_add", True) if config else False,
        "can_delete": config.get("can_delete", True) if config else False,
        "can_toggle": bool(config and config.get("active")),
    }
    return render(request, "core/admin_landing_settings.html", context)
