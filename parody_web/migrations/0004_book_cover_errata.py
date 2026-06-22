from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parody_web", "0003_numbers"),
    ]

    operations = [
        migrations.AddField(
            model_name="book",
            name="cover_image",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="book",
            name="errata",
            field=models.TextField(blank=True, default=""),
        ),
    ]
