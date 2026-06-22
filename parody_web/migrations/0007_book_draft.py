from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parody_web", "0006_book_parts"),
    ]

    operations = [
        migrations.AddField(
            model_name="book",
            name="draft",
            field=models.BooleanField(default=False),
        ),
    ]
