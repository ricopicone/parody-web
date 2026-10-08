from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('parody_web', '0014_section_draft'),
    ]

    operations = [
        migrations.AddField(
            model_name='section',
            name='key_html',
            field=models.TextField(blank=True, default=''),
        ),
    ]
