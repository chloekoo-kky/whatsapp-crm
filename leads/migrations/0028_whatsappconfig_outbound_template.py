from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0027_whatsappscripttemplate"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconfig",
            name="outbound_template_name",
            field=models.CharField(
                default="just_to_say_hi",
                help_text="Meta-approved template name used for outbound first-touch dispatch.",
                max_length=64,
            ),
        ),
    ]
