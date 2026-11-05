from django.db import migrations

# The colleges and programs that were hard-coded before they moved into the database.
# Names must stay exactly as they were, because sign-up profiles store them as text.
COLLEGES = [
    "CHTM (College of Tourism and Hospitality Management)",
    "CITTE (College of Industrial and Technical Teacher Education)",
    "Department of Laboratory High School",
]

# (program name, college name or None)
PROGRAMS = [
    ("Bachelor of Science in Hospitality Management (BSHM)", "CHTM (College of Tourism and Hospitality Management)"),
    ("Bachelor of Science in Tourism Management (BSTM)", "CHTM (College of Tourism and Hospitality Management)"),
    ("Bachelor of Science in Food and Beverage Service Management (BSFBSM)", "CHTM (College of Tourism and Hospitality Management)"),
    ("Bachelor of Science in Industrial Technology Major in Food Preparation & Services Management Technology", "CITTE (College of Industrial and Technical Teacher Education)"),
    ("Bachelor of Technical-Vocational Teacher Education Major in Food Service Management", "CITTE (College of Industrial and Technical Teacher Education)"),
    ("Bachelor of Technology and Livelihood Education Major in Home Economics", "CITTE (College of Industrial and Technical Teacher Education)"),
    ("Bachelor of Science in Entrepreneurship (BSEntrep)", None),
    ("Senior High School", "Department of Laboratory High School"),
]


def seed(apps, schema_editor):
    College = apps.get_model("core", "College")
    Program = apps.get_model("core", "Program")
    by_name = {}
    for name in COLLEGES:
        by_name[name] = College.objects.get_or_create(name=name)[0]
    for name, college_name in PROGRAMS:
        college = by_name.get(college_name) if college_name else None
        Program.objects.get_or_create(name=name, defaults={"college": college})


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0030_programs_colleges"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
