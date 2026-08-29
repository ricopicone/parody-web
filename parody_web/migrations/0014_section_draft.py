from django.db import migrations, models


def inherit_the_chapters_flag(apps, schema_editor):
    """Every existing section takes its chapter's draft status.

    AddField defaults the column to False, and the views now gate on it — so
    without this a `migrate` alone would publish every unreleased chapter in
    the database until something re-imported the artifacts. A host's deploy
    script usually does import right after migrating, but a gate this
    load-bearing must not depend on the order of someone else's script.

    This is the same inheritance rule the rest of the feature applies; it is
    exactly right for the pre-existing rows, none of which could carry a
    per-section flag.
    """
    Section = apps.get_model("parody_web", "Section")
    Section.objects.filter(chapter__draft=True).update(draft=True)


class Migration(migrations.Migration):

    dependencies = [
        ('parody_web', '0013_chapter_draft'),
    ]

    operations = [
        migrations.AddField(
            model_name='section',
            name='draft',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(inherit_the_chapters_flag,
                             migrations.RunPython.noop),
    ]
