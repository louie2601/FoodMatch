import os

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import StaticFilesStorage


class VersionedStaticFilesStorage(StaticFilesStorage):
    """Static files whose script and style URLs end in ?v=<last change time>.

    Browsers (and the 7-day cache header nginx sends in Docker) keep static
    files, so after an update a page could keep running an old script. A new
    ?v= value whenever the file changes makes browsers fetch the new copy."""

    def url(self, name):
        url = super().url(name)
        if name and name.endswith((".js", ".css")):
            version = self._version(name)
            if version:
                url = f"{url}{'&' if '?' in url else '?'}v={version}"
        return url

    def _version(self, name):
        # The source file first (finders), so a stale copy in STATIC_ROOT never
        # hides a change; the collected copy when the source can't be found.
        for path in (finders.find(name), self._collected_path(name)):
            if path:
                try:
                    return int(os.path.getmtime(path))
                except OSError:
                    continue
        return ""

    def _collected_path(self, name):
        try:
            path = self.path(name)
        except Exception:
            return None
        return path if os.path.exists(path) else None
