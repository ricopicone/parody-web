from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parody_web", "0002_section_preview"),
    ]

    operations = [
        migrations.AddField(
            model_name="chapter",
            name="number",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="section",
            name="number",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
    ]
