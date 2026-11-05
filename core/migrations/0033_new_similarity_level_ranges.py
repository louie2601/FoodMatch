"""Similarity levels changed to Low 0–30%, Moderate 31–49%, High 50% and up.

Relabels saved Similarity Check records from their stored scores, so history,
the dashboard and reports use the same scale as new checks, and updates the
ranges quoted in the landing page FAQ. Only Moderate/High labels can change:
the 30% line (which decides whether a student may upload) is the same.
"""
from django.db import migrations

LABELS = {"low": "Low Similarity", "moderate": "Moderate Similarity", "high": "High Similarity"}


def _level(score_percent):
    score = float(score_percent or 0)
    if score <= 30:
        return "low"
    if score < 50:
        return "moderate"
    return "high"


def relabel(apps, schema_editor):
    Record = apps.get_model("core", "SimilarityCheckRecord")
    for record in Record.objects.all().iterator():
        level = _level(record.top_score_percent)
        snapshot = record.results_snapshot or []
        new_snapshot = [
            {**item, "similarity_label": LABELS[_level(item.get("score_percent"))]} if isinstance(item, dict) else item
            for item in snapshot
        ]
        if record.similarity_level != level or record.similarity_label != LABELS[level] or new_snapshot != snapshot:
            record.similarity_level = level
            record.similarity_label = LABELS[level]
            record.results_snapshot = new_snapshot
            record.save(update_fields=["similarity_level", "similarity_label", "results_snapshot"])

    FaqItem = apps.get_model("core", "FaqItem")
    for faq in FaqItem.objects.all():
        answer = faq.answer or ""
        updated = answer
        for old, new in (("31–60%", "31–49%"), ("31-60%", "31-49%"), ("61–100%", "50–100%"), ("61-100%", "50-100%")):
            updated = updated.replace(old, new)
        if updated != answer:
            faq.answer = updated
            faq.save(update_fields=["answer"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0032_researchsubmission_document_hash"),
    ]

    operations = [
        migrations.RunPython(relabel, migrations.RunPython.noop),
    ]
