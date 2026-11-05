from django.db import migrations


def backfill_members(apps, schema_editor):
    """Every existing student account becomes a group with one member: the
    person who registered it."""
    RegistrationProfile = apps.get_model("core", "RegistrationProfile")
    GroupMember = apps.get_model("core", "GroupMember")

    profiles = RegistrationProfile.objects.select_related("user").filter(
        user__is_staff=False, user__is_superuser=False
    )
    for profile in profiles:
        user = profile.user
        if GroupMember.objects.filter(user=user).exists():
            continue
        if not (user.first_name.strip() or user.last_name.strip()):
            continue
        GroupMember.objects.create(
            user=user,
            first_name=user.first_name.strip(),
            middle_name=(profile.middle_name or "").strip(),
            last_name=user.last_name.strip(),
            position=0,
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_group_members"),
    ]

    operations = [
        migrations.RunPython(backfill_members, noop),
    ]
