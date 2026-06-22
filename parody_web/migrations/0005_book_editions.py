from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parody_web", "0004_book_cover_errata"),
    ]

    operations = [
        # slug is no longer unique on its own — (slug, edition_id) is.
        migrations.AlterField(
            model_name="book",
            name="slug",
            field=models.SlugField(),
        ),
        migrations.AddField(
            model_name="book",
            name="edition_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="book",
            name="edition_title",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="book",
            name="edition_default",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="book",
            name="edition_order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterModelOptions(
            name="book",
            options={"ordering": ["slug", "edition_order"]},
        ),
        migrations.AlterUniqueTogether(
            name="book",
            unique_together={("slug", "edition_id")},
        ),
    ]
