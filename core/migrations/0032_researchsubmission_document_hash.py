import hashlib

from django.db import migrations, models


def fingerprint_existing_files(apps, schema_editor):
    ResearchSubmission = apps.get_model("core", "ResearchSubmission")
    for submission in ResearchSubmission.objects.exclude(document=""):
        try:
            digest = hashlib.sha256()
            with submission.document.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except (FileNotFoundError, OSError, ValueError):
            continue  # file missing from storage; leave it blank
        ResearchSubmission.objects.filter(pk=submission.pk).update(document_hash=digest.hexdigest())


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0031_seed_programs_colleges"),
    ]

    operations = [
        migrations.AddField(
            model_name="researchsubmission",
            name="document_hash",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.RunPython(fingerprint_existing_files, migrations.RunPython.noop),
    ]
