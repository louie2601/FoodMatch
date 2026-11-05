from django.db import migrations


STEPS = [
    ("Register your group", "Create one account for your research group with up to five members.", "users"),
    ("Run a similarity check", "Upload your draft and compare it against every study already in the repository.", "search"),
    ("Submit your research", "Send your final paper for review straight from your dashboard.", "upload"),
    ("Get reviewed", "An admin approves or returns it with notes, and you're notified either way.", "check"),
]

FEATURES = [
    ("Similarity Checking", "Compares title, abstract, ingredients and process, and full text against the repository.", "search"),
    ("Research Repository", "Search every approved food study by title, author, adviser, keyword, category, or year.", "book"),
    ("Review Workflow", "Submissions are approved or returned with notes, and every step sends a notification.", "clipboard"),
    ("Reports & Analytics", "Charts on submissions, similarity results, and repository coverage for the college.", "chart"),
]

FAQS = [
    (
        "Who can submit research?",
        "Registered student research groups. Each group shares one account that lists up to five members, and those members are used as the authors of every submission.",
    ),
    (
        "What is my paper compared against?",
        "Every approved study in the FOOD MATCH repository. The check weighs the ingredients and process section, the rest of the paper, the title, and the abstract.",
    ),
    (
        "What do the similarity levels mean?",
        "Low (0–30%) means the work reads as original, Moderate (31–60%) means it is a related study, and High (61–100%) flags possible duplication worth reviewing.",
    ),
    (
        "Can other students open my uploaded file?",
        "No. Other students only see a study's details such as its title, authors, abstract, and category. The document itself stays private to your group and the reviewers.",
    ),
]

COLLEGES = [
    "CHTM (College of Tourism and Hospitality Management)",
    "CITTE (College of Industrial and Technical Teacher Education)",
    "Department of Laboratory High School",
]


def seed(apps, schema_editor):
    LandingSettings = apps.get_model("core", "LandingSettings")
    HowItWorksStep = apps.get_model("core", "HowItWorksStep")
    LandingFeature = apps.get_model("core", "LandingFeature")
    FaqItem = apps.get_model("core", "FaqItem")
    PartnerCollege = apps.get_model("core", "PartnerCollege")

    LandingSettings.objects.get_or_create(pk=1)
    if not HowItWorksStep.objects.exists():
        HowItWorksStep.objects.bulk_create(
            HowItWorksStep(title=t, description=d, icon=i, order=n) for n, (t, d, i) in enumerate(STEPS, 1)
        )
    if not LandingFeature.objects.exists():
        LandingFeature.objects.bulk_create(
            LandingFeature(title=t, description=d, icon=i, order=n) for n, (t, d, i) in enumerate(FEATURES, 1)
        )
    if not FaqItem.objects.exists():
        FaqItem.objects.bulk_create(
            FaqItem(question=q, answer=a, order=n) for n, (q, a) in enumerate(FAQS, 1)
        )
    if not PartnerCollege.objects.exists():
        PartnerCollege.objects.bulk_create(
            PartnerCollege(name=name, order=n) for n, name in enumerate(COLLEGES, 1)
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_landing_page"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
