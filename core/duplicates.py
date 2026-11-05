"""Duplicate checks for research uploads.

A research is a duplicate when its file is byte-for-byte the same as one
already uploaded (checked by SHA-256 fingerprint, so renaming the file does not
get around it), or when its title matches an existing research title (ignoring
capital letters and extra spaces). Rejected submissions never count, so a
student can fix and resubmit a rejected research.
"""
import hashlib

from .models import ResearchPaper, ResearchSubmission, ResearchSubmissionStatus


def normalize_title(title):
    return " ".join((title or "").split()).casefold()


def file_sha256(uploaded_file):
    """Fingerprint of an uploaded (or stored) file. Leaves the file rewound so
    it can still be read or saved afterwards."""
    digest = hashlib.sha256()
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    if hasattr(uploaded_file, "chunks"):
        for chunk in uploaded_file.chunks():
            digest.update(chunk)
    else:
        digest.update(uploaded_file.read())
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    return digest.hexdigest()


def _active_submissions():
    return ResearchSubmission.objects.exclude(status=ResearchSubmissionStatus.REJECTED)


def duplicate_file_error(file_hash, user):
    """Error message if this exact file is already in the system, else ""."""
    if not file_hash:
        return ""
    existing = _active_submissions().filter(document_hash=file_hash).first()
    if not existing:
        return ""
    if existing.student_id == user.pk:
        return f"You already uploaded this file as “{existing.title}” ({existing.get_status_display()})."
    if user.is_staff or user.is_superuser:
        return f"This file has already been uploaded as “{existing.title}”."
    # Students don't get to see another account's pending titles.
    return "This file has already been uploaded to the system."


def duplicate_title_error(title, user):
    """Error message if a research with this title already exists, else ""."""
    wanted = normalize_title(title)
    if not wanted:
        return ""
    for existing in _active_submissions().only("title", "status", "student_id"):
        if normalize_title(existing.title) != wanted:
            continue
        is_staff = user.is_staff or user.is_superuser
        if existing.student_id == user.pk and not is_staff:
            return f"You already submitted a research with this title ({existing.get_status_display()})."
        if existing.status == ResearchSubmissionStatus.APPROVED:
            return "A research with this title already exists in the repository."
        return "A research with this title has already been submitted."
    for paper_title in ResearchPaper.objects.values_list("title", flat=True):
        if normalize_title(paper_title) == wanted:
            return "A research with this title already exists in the repository."
    return ""
