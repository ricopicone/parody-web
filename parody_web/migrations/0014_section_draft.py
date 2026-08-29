from django.db import migrations, models


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
    ]
