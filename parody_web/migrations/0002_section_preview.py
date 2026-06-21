from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parody_web", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="section",
            name="preview",
            field=models.BooleanField(default=False),
        ),
    ]
