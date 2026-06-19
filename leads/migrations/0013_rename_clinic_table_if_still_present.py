# If 0012’s RenameModel did not run against the DB (e.g. fake migrate) but the app
# expects ``leads_lead``, align the table name when ``leads_clinic`` still exists.

from django.db import migrations


def rename_clinic_table_if_needed(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor != "postgresql":
        return
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'leads_clinic'
            LIMIT 1
            """
        )
        if not cursor.fetchone():
            return
        cursor.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'leads_lead'
            LIMIT 1
            """
        )
        if cursor.fetchone():
            return
        cursor.execute('ALTER TABLE "leads_clinic" RENAME TO "leads_lead";')


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0012_lead_search_history_and_rename"),
    ]

    operations = [
        migrations.RunPython(rename_clinic_table_if_needed, migrations.RunPython.noop),
    ]
