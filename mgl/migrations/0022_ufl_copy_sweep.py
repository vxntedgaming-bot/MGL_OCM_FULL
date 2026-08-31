from django.db import migrations


def update_ufl_copy(apps, schema_editor):
    SiteContent = apps.get_model("mgl", "SiteContent")
    replacements = {
        "leagues.page_intro": (
            "Official MGL standings. Click a club to open its squad and club page.",
            "Official UFL standings. Click a club to open its squad and club page.",
        ),
        "leagues.premier_description": (
            "The top active MGL competition.",
            "The top active UFL competition.",
        ),
        "jobs.page_intro": (
            "Take over an official MGL club. Inspect the squad first. Owner or admin approval is required before you are appointed.",
            "Take over an official UFL club. Inspect the squad first. Owner or admin approval is required before you are appointed.",
        ),
        "market.transfer_intro": (
            "Auctions, listed club players and Free Agents. Unassigned FC26 players are a separate admin-only pool. All deals use MGL tokens.",
            "Auctions, listed club players and Free Agents. Unassigned FC26 players are a separate admin-only pool. All deals use UFL tokens.",
        ),
        "community.history_intro": (
            "Saved MGL seasons and cup history will be recorded here. Live league tables are not rewritten as past winners.",
            "Saved UFL seasons and cup history will be recorded here. Live league tables are not rewritten as past winners.",
        ),
    }
    for key, (old, new) in replacements.items():
        row = SiteContent.objects.filter(key=key).first()
        if row and row.value == old:
            row.value = new
            row.save(update_fields=["value"])


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0021_ufl_foundation"),
    ]

    operations = [
        migrations.RunPython(update_ufl_copy, migrations.RunPython.noop),
    ]
