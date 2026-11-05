import time

from django.core.management.base import BaseCommand

from core import semantic
from core.models import ResearchSubmission, ResearchSubmissionStatus


class Command(BaseCommand):
    help = (
        "Prepares the AI model's meaning vectors for approved studies, so the "
        "Similarity Check can compare meaning. Only missing or outdated ones are "
        "built unless --rebuild is given."
    )

    def add_arguments(self, parser):
        parser.add_argument("--rebuild", action="store_true", help="Rebuild every study, not just missing ones.")

    def handle(self, *args, **options):
        if semantic.get_model() is None:
            self.stdout.write(self.style.WARNING("The AI model isn't available, so nothing was built (TF-IDF still works)."))
            return
        studies = ResearchSubmission.objects.filter(status=ResearchSubmissionStatus.APPROVED).exclude(document="")
        if not options["rebuild"]:
            studies = studies.exclude(semantic_index_version=semantic.INDEX_VERSION)
        total = studies.count()
        if not total:
            self.stdout.write("All approved studies are already prepared.")
            return
        started = time.time()
        built = 0
        for number, submission in enumerate(studies.iterator(), start=1):
            try:
                ok = semantic.build_index(submission)
            except Exception as exc:  # noqa: BLE001
                ok = False
                self.stderr.write(f"  could not prepare '{submission.title[:60]}': {exc}")
            built += ok
            self.stdout.write(f"  [{number}/{total}] {'done' if ok else 'skipped'}: {submission.title[:70]}")
        self.stdout.write(self.style.SUCCESS(f"Prepared {built} of {total} studies in {time.time() - started:.0f}s."))
