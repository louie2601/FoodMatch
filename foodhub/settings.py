import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(env_path):
    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key.startswith("SMTP_"):
            # This project's .env is authoritative for SMTP_* (even blank), so another
            # account's machine-wide SMTP credentials are never mixed in.
            os.environ[key] = value
        elif not os.environ.get(key):
            os.environ[key] = value


load_env_file(BASE_DIR / ".env")

def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# Off unless explicitly turned on (put DEBUG=True in your local .env only).
DEBUG = env_bool("DEBUG", False)

SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if not SECRET_KEY:
    if not DEBUG:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured("Set SECRET_KEY in .env (a long random value) before running with DEBUG off.")
    SECRET_KEY = "django-insecure-local-development-only"

ALLOWED_HOSTS = [host.strip() for host in os.environ.get("ALLOWED_HOSTS", "").split(",") if host.strip()]
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Full origins (scheme + host + port) allowed to submit forms, e.g. "https://foodmatch.example.edu".
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

# Django's built-in /admin/ site has its own sign-in that skips the login
# lockout and the module privileges, so it is off unless explicitly enabled.
ENABLE_DJANGO_ADMIN = env_bool("ENABLE_DJANGO_ADMIN", False)

# Only behind a reverse proxy that overwrites X-Forwarded-For (the nginx in
# docker/) may that header be trusted as the visitor's IP; otherwise anyone
# could fake it to dodge the login lockout or spoof the IP in the logs.
TRUST_X_FORWARDED_FOR = env_bool("TRUST_X_FORWARDED_FOR", False)
# Only when the app is reachable solely through a Cloudflare Tunnel (bound to
# 127.0.0.1, see run_public.ps1): Cloudflare then sets CF-Connecting-IP to the
# visitor's real address and overwrites any value a visitor sends.
TRUST_CF_CONNECTING_IP = env_bool("TRUST_CF_CONNECTING_IP", False)

# Turn on once the site is served over HTTPS (HTTPS_ENABLED=True in .env).
HTTPS_ENABLED = env_bool("HTTPS_ENABLED", False)
if HTTPS_ENABLED:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "2592000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "foodhub.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.csrf",
                "core.context_processors.pending_deletion_count",
                "core.context_processors.registration_requests_nav",
                "core.context_processors.notifications",
                "core.context_processors.landing_site",
                "core.context_processors.admin_settings_access",
            ],
        },
    },
]

WSGI_APPLICATION = "foodhub.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "Foodmatch"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

AUTHENTICATION_BACKENDS = [
    "core.auth_backends.EmergencySuperAdminBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Break-glass Super Admin login that exists only here (via .env), never as a
# database row. Leave both unset to keep this disabled. Generate the hash with:
#   python manage.py shell -c "from django.contrib.auth.hashers import make_password; print(make_password('your-password-here'))"
EMERGENCY_SUPERADMIN_USERNAME = os.environ.get("EMERGENCY_SUPERADMIN_USERNAME", "")
EMERGENCY_SUPERADMIN_PASSWORD_HASH = os.environ.get("EMERGENCY_SUPERADMIN_PASSWORD_HASH", "")

# Outgoing email (password reset codes). Reads the SMTP_* variables from the
# environment / .env; without SMTP_HOST, emails are printed to the server console.
_smtp_host = os.environ.get("SMTP_HOST", "").strip()
if _smtp_host:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = _smtp_host
    EMAIL_PORT = int(os.environ.get("SMTP_PORT", "587") or 587)
    EMAIL_HOST_USER = os.environ.get("SMTP_USERNAME", "")
    EMAIL_HOST_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    _smtp_encryption = os.environ.get("SMTP_ENCRYPTION", "tls").strip().lower()
    EMAIL_USE_TLS = _smtp_encryption == "tls"
    EMAIL_USE_SSL = _smtp_encryption == "ssl"
    EMAIL_TIMEOUT = 15
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

_smtp_from_email = os.environ.get("SMTP_FROM_EMAIL", "").strip()
_smtp_from_name = os.environ.get("SMTP_FROM_NAME", "").strip()
if _smtp_from_email:
    DEFAULT_FROM_EMAIL = f"{_smtp_from_name} <{_smtp_from_email}>" if _smtp_from_name else _smtp_from_email

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"

# Philippine time (UTC+8) for every date and time the system shows, filters on,
# or exports. The database still stores UTC, so no stored data changes.
TIME_ZONE = "Asia/Manila"

USE_I18N = True

USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
# `collectstatic` gathers every static file here for the web server (Docker/nginx).
STATIC_ROOT = BASE_DIR / "staticfiles"
# Script and style links carry ?v=<last change time>, so browsers load an
# updated file instead of an old cached copy (see core/storage.py).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "core.storage.VersionedStaticFilesStorage"},
}

# Media files (user-uploaded content)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Machine-learning similarity (core/semantic.py): where the pre-trained language
# model is stored, and a switch to fall back to TF-IDF only.
ML_MODELS_DIR = Path(os.environ.get("ML_MODELS_DIR", "").strip() or BASE_DIR / "ml_models")
SEMANTIC_SIMILARITY_ENABLED = env_bool("SEMANTIC_SIMILARITY_ENABLED", True)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
