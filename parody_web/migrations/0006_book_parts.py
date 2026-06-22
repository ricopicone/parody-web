from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parody_web", "0005_book_editions"),
    ]

    operations = [
        migrations.AddField(
            model_name="book",
            name="parts",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
