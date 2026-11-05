from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from . import signals  # noqa: F401

        # runserver's autoreloader only watches Python files. Watch .env too so
        # editing it (e.g. SMTP settings) restarts the server and reloads it.
        from django.conf import settings
        from django.utils import autoreload

        def watch_env_file(sender, **kwargs):
            sender.extra_files.add(settings.BASE_DIR / ".env")

        autoreload.autoreload_started.connect(watch_env_file)
