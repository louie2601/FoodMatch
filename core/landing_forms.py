import base64
import time
import uuid
from io import BytesIO

from django import forms
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Max
from PIL import Image, ImageOps, UnidentifiedImageError

from .forms import REPOSITORY_INPUT_CLASSES
from .models import (
    MAX_ANNOUNCEMENT_IMAGES,
    Announcement,
    AnnouncementImage,
    FaqItem,
    FoodCategory,
    GalleryImage,
    HeroSlide,
    HowItWorksStep,
    LandingFeature,
    LandingSettings,
    PartnerCollege,
)

MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024
IMAGE_UPLOAD_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
IMAGE_UPLOAD_ACCEPT = ",".join(IMAGE_UPLOAD_EXTENSIONS) + ",image/jpeg,image/png,image/webp"
CHECKBOX_CLASSES = "h-5 w-5 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
FILE_INPUT_CLASSES = (
    "block w-full text-sm text-slate-600 file:mr-4 file:rounded-xl file:border-0 "
    "file:bg-emerald-50 file:px-4 file:py-2.5 file:text-sm file:font-semibold "
    "file:text-emerald-700 hover:file:bg-emerald-100"
)

# Uploads from a save that failed validation wait here (outside media/landing,
# so they're never publicly served) until the corrected form is saved.
PENDING_UPLOAD_DIR = "landing_pending"
PENDING_SESSION_KEY = "landing_pending_uploads"
PENDING_MAX_AGE_SECONDS = 24 * 60 * 60


def optimize_image(uploaded, max_side):
    """Validate an uploaded image and re-encode it as a resized WebP, so a 12 MB
    phone photo never ships to landing page visitors as-is."""
    name = (uploaded.name or "").lower()
    if not name.endswith(IMAGE_UPLOAD_EXTENSIONS):
        raise forms.ValidationError("Only JPG, PNG, or WebP images are allowed.")
    if uploaded.size > MAX_IMAGE_UPLOAD_BYTES:
        raise forms.ValidationError("Images must be 5 MB or smaller.")
    try:
        uploaded.seek(0)
        image = Image.open(uploaded)
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise forms.ValidationError(
            "This file can't be read as an image. If it's an iPhone (HEIC) photo, save it as JPG first."
        )

    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    image = image.convert("RGBA" if has_alpha else "RGB")
    image.thumbnail((max_side, max_side), Image.LANCZOS)

    buffer = BytesIO()
    image.save(buffer, format="WEBP", quality=82, method=6)
    return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.webp")


def _thumbnail_data_uri(path):
    with default_storage.open(path) as fh:
        with Image.open(fh) as image:
            image = image.convert("RGB")
            image.thumbnail((240, 240))
            buffer = BytesIO()
            image.save(buffer, format="WEBP", quality=60)
    return "data:image/webp;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


class LandingFormMixin:
    """Applies the shared Tailwind styling, turns each image upload into an
    optimized WebP sized for where it's displayed, and keeps uploads across a
    failed save so the admin doesn't have to choose the files again."""

    image_max_side = {}
    multi_image_max_side = {}
    image_alt_pairs = {}

    def default_alt_text(self, cleaned):
        """Alt text to use when none is typed, or "" if there's nothing sensible."""
        return ""

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = session
        self._fresh_uploads = {}
        self._kept_uploads = {}
        self.kept_upload_count = 0
        for alt_field in self.image_alt_pairs.values():
            self.fields[alt_field].required = False
            self.fields[alt_field].help_text = "Leave blank to use a description based on the details above."
        for image_field in self.image_max_side:
            # A kept image counts as "chosen" for required image fields.
            if image_field in self.fields and self._kept_from_request(image_field):
                self.fields[image_field].required = False
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = CHECKBOX_CLASSES
            elif isinstance(widget, forms.ClearableFileInput):
                widget.template_name = "core/widgets/landing_image_input.html"
                widget.attrs["class"] = FILE_INPUT_CLASSES
                widget.attrs["accept"] = IMAGE_UPLOAD_ACCEPT
                field.help_text = "JPG, PNG, or WebP up to 5 MB. Large photos are resized automatically."
            else:
                widget.attrs["class"] = REPOSITORY_INPUT_CLASSES
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 4)

    # -- uploads kept from an earlier failed save --------------------------------

    def _pending_registry(self):
        if self.session is None:
            return {}
        return dict(self.session.get(PENDING_SESSION_KEY, {}))

    def _kept_from_request(self, field_name):
        if not self.is_bound or self.session is None:
            return []
        registry = self._pending_registry()
        kept = []
        for token in self.data.getlist(f"{field_name}__pending"):
            entry = registry.get(token)
            if entry and entry["field"] == field_name and default_storage.exists(entry["path"]):
                kept.append((token, entry["path"]))
        return kept

    @staticmethod
    def _load_kept(path):
        with default_storage.open(path) as fh:
            return ContentFile(fh.read(), name=f"{uuid.uuid4().hex}.webp")

    def stash_uploads(self):
        """After a failed save: park every image from this attempt so the
        re-rendered form can offer them back."""
        if self.session is None:
            return
        registry = self._pending_registry()
        now = time.time()
        for token, entry in list(registry.items()):
            if now - entry.get("ts", 0) > PENDING_MAX_AGE_SECONDS:
                default_storage.delete(entry["path"])
                del registry[token]

        for field_name in set(self._fresh_uploads) | set(self._kept_uploads):
            entries = list(self._kept_uploads.get(field_name, []))
            for content in self._fresh_uploads.get(field_name, []):
                token = uuid.uuid4().hex
                content.seek(0)
                path = default_storage.save(f"{PENDING_UPLOAD_DIR}/{token}.webp", ContentFile(content.read()))
                registry[token] = {"field": field_name, "path": path, "ts": now}
                entries.append((token, path))
            if field_name in self.image_max_side:
                entries = entries[-1:]
            if field_name in self.fields and entries:
                self[field_name].kept_uploads = [
                    {"token": token, "thumb": _thumbnail_data_uri(path)} for token, path in entries
                ]
                self.kept_upload_count += len(entries)
        self.session[PENDING_SESSION_KEY] = registry

    def discard_used_uploads(self):
        """After a successful save: the parked files were copied into place."""
        if self.session is None:
            return
        registry = self._pending_registry()
        for entries in self._kept_uploads.values():
            for token, path in entries:
                default_storage.delete(path)
                registry.pop(token, None)
        self.session[PENDING_SESSION_KEY] = registry

    def clean(self):
        cleaned = super().clean()
        for image_field, max_side in self.image_max_side.items():
            if image_field in self.errors:
                continue
            value = cleaned.get(image_field)
            if isinstance(value, UploadedFile):
                try:
                    optimized = optimize_image(value, max_side)
                except forms.ValidationError as exc:
                    self.add_error(image_field, exc)
                    continue
                cleaned[image_field] = optimized
                self._fresh_uploads[image_field] = [optimized]
            elif value is not False:
                kept = self._kept_from_request(image_field)[-1:]
                if kept:
                    self._kept_uploads[image_field] = kept
                    cleaned[image_field] = self._load_kept(kept[0][1])

        for image_field, max_side in self.multi_image_max_side.items():
            uploaded_files = cleaned.get(image_field) or []
            optimized = []
            for uploaded in uploaded_files:
                try:
                    optimized.append(optimize_image(uploaded, max_side))
                except forms.ValidationError as exc:
                    self.add_error(image_field, f"{uploaded.name}: {exc.messages[0]}")
            kept = self._kept_from_request(image_field)
            self._fresh_uploads[image_field] = optimized
            self._kept_uploads[image_field] = kept
            cleaned[image_field] = [self._load_kept(path) for _, path in kept] + optimized

        for image_field, alt_field in self.image_alt_pairs.items():
            image = cleaned.get(image_field)
            if image is None and self.instance.pk:
                image = getattr(self.instance, image_field)
            if image and not (cleaned.get(alt_field) or "").strip():
                default = self.default_alt_text(cleaned).strip()[:150]
                if default:
                    cleaned[alt_field] = default
                else:
                    self.add_error(alt_field, "Describe the image for visitors who can't see it.")
        return cleaned


class LandingSettingsForm(LandingFormMixin, forms.ModelForm):
    class Meta:
        model = LandingSettings
        exclude = ["updated_at"]
        labels = {
            "hero_headline": "Default hero headline",
            "hero_subtitle": "Default hero subtitle",
            "footer_about": "Footer description",
            "facebook_url": "Facebook page URL",
            "website_url": "Website URL",
        }
        help_texts = {
            "hero_headline": "Shown when there are no active hero slides.",
        }
        widgets = {
            "hero_subtitle": forms.Textarea(attrs={"rows": 3}),
            "footer_about": forms.Textarea(attrs={"rows": 3}),
        }


class HeroSlideForm(LandingFormMixin, forms.ModelForm):
    image_max_side = {"image": 1920}
    image_alt_pairs = {"image": "alt_text"}

    def default_alt_text(self, cleaned):
        return cleaned.get("headline") or ""

    class Meta:
        model = HeroSlide
        fields = ["image", "alt_text", "headline", "subtitle", "button_text", "button_link", "order", "is_active"]
        labels = {"is_active": "Show this slide", "alt_text": "Image description (alt text)"}
        help_texts = {"button_link": "A page on this site such as /register/, or a full https:// link."}
        widgets = {"subtitle": forms.Textarea(attrs={"rows": 3})}

    def clean_button_link(self):
        link = (self.cleaned_data.get("button_link") or "").strip()
        first_part = link.split("/", 1)[0]
        if link and not link.startswith("/") and "://" not in link and "." in first_part and " " not in first_part:
            link = f"https://{link}"
        if link and not (link.startswith("/") or link.startswith("https://") or link.startswith("http://")):
            raise forms.ValidationError("Use a path starting with / or a full http(s):// link.")
        if link.startswith("//"):
            raise forms.ValidationError("Use a path starting with a single / or a full http(s):// link.")
        return link

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("button_link") and not (cleaned.get("button_text") or "").strip():
            self.add_error("button_text", "Add button text, or clear the link.")
        return cleaned


class MultipleImageInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleImageInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        files = data if isinstance(data, (list, tuple)) else [data]
        return [single_clean(f, initial) for f in files if f]


class AnnouncementForm(LandingFormMixin, forms.ModelForm):
    multi_image_max_side = {"images": 1600}

    images = MultipleImageField(
        required=False,
        label="Add images",
        help_text=(
            f"JPG, PNG, or WebP up to 5 MB each — select several at once. Up to {MAX_ANNOUNCEMENT_IMAGES} "
            "images per announcement; two or more play as a slideshow."
        ),
    )
    remove_images = forms.ModelMultipleChoiceField(
        queryset=AnnouncementImage.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Current images",
    )

    class Meta:
        model = Announcement
        fields = ["title", "body", "images", "remove_images", "publish_date", "expiry_date", "is_active"]
        labels = {
            "expiry_date": "Hide after (optional)",
            "is_active": "Show this announcement",
        }
        widgets = {
            "body": forms.Textarea(attrs={"rows": 4}),
            "publish_date": forms.DateInput(attrs={"type": "date"}),
            "expiry_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        images_widget = self.fields["images"].widget
        images_widget.attrs["class"] = FILE_INPUT_CLASSES
        images_widget.attrs["accept"] = IMAGE_UPLOAD_ACCEPT
        if self.instance.pk:
            self.fields["remove_images"].queryset = self.instance.images.all()
        else:
            del self.fields["remove_images"]

    def clean(self):
        cleaned = super().clean()
        publish, expiry = cleaned.get("publish_date"), cleaned.get("expiry_date")
        if publish and expiry and expiry < publish:
            self.add_error("expiry_date", "The hide date can't be before the publish date.")
        existing = self.instance.images.count() if self.instance.pk else 0
        removing = len(cleaned.get("remove_images") or [])
        adding = len(cleaned.get("images") or [])
        if existing - removing + adding > MAX_ANNOUNCEMENT_IMAGES:
            self.add_error(
                "images",
                f"An announcement can have at most {MAX_ANNOUNCEMENT_IMAGES} images "
                f"({existing - removing} already attached).",
            )
        return cleaned

    def save(self, commit=True):
        announcement = super().save(commit=True)
        for old in self.cleaned_data.get("remove_images") or []:
            old.delete()
        next_order = (announcement.images.aggregate(m=Max("order"))["m"] or 0) + 1
        title = announcement.title
        for offset, image in enumerate(self.cleaned_data.get("images") or []):
            AnnouncementImage.objects.create(
                announcement=announcement,
                image=image,
                alt_text=f"{title} — image {next_order + offset}"[:150],
                order=next_order + offset,
            )
        return announcement


class HowItWorksStepForm(LandingFormMixin, forms.ModelForm):
    class Meta:
        model = HowItWorksStep
        fields = ["title", "description", "icon", "order"]


class LandingFeatureForm(LandingFormMixin, forms.ModelForm):
    class Meta:
        model = LandingFeature
        fields = ["title", "description", "icon", "order"]


class GalleryImageForm(LandingFormMixin, forms.ModelForm):
    image_max_side = {"image": 1600}
    image_alt_pairs = {"image": "alt_text"}

    def default_alt_text(self, cleaned):
        return cleaned.get("caption") or ""

    class Meta:
        model = GalleryImage
        fields = ["image", "alt_text", "caption", "order", "is_active"]
        labels = {"alt_text": "Image description (alt text)", "is_active": "Show this photo"}


class PartnerCollegeForm(LandingFormMixin, forms.ModelForm):
    image_max_side = {"logo": 400}
    image_alt_pairs = {"logo": "alt_text"}

    def default_alt_text(self, cleaned):
        name = cleaned.get("name") or ""
        return f"{name} logo" if name else ""

    class Meta:
        model = PartnerCollege
        fields = ["name", "logo", "alt_text", "order"]
        labels = {"logo": "Logo (optional)", "alt_text": "Logo description (alt text)"}


class FaqItemForm(LandingFormMixin, forms.ModelForm):
    class Meta:
        model = FaqItem
        fields = ["question", "answer", "order", "is_active"]
        labels = {"is_active": "Show this question"}
        widgets = {"answer": forms.Textarea(attrs={"rows": 4})}


class CategoryImageForm(LandingFormMixin, forms.ModelForm):
    image_max_side = {"image": 800}
    image_alt_pairs = {"image": "image_alt"}

    def default_alt_text(self, cleaned):
        return self.instance.name or ""

    class Meta:
        model = FoodCategory
        fields = ["image", "image_alt"]
        labels = {"image": "Category photo", "image_alt": "Image description (alt text)"}
