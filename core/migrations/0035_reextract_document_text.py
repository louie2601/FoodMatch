"""PDF text is now read with PyMuPDF (cleaner and faster than PyPDF2), so the
cached text of every submission is cleared and read again on next use. The AI
model's meaning vectors are rebuilt too (core/semantic.py INDEX_VERSION)."""
from django.db import migrations


def clear_cached_text(apps, schema_editor):
    apps.get_model("core", "ResearchSubmission").objects.exclude(cached_document_text=None).update(cached_document_text=None)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0034_semantic_index"),
    ]

    operations = [
        migrations.RunPython(clear_cached_text, migrations.RunPython.noop),
    ]
