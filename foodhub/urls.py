from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Landing page images are public by design, so they're served even with
    # DEBUG off. Nothing else under MEDIA_ROOT (student documents) is exposed.
    re_path(r"^media/landing/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT / "landing"}),
    path("", include("core.urls")),
]

if settings.ENABLE_DJANGO_ADMIN:
    urlpatterns.insert(0, path("admin/", admin.site.urls))

# Serve media files during development (only when DEBUG is True)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
