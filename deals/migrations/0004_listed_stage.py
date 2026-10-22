from django.db import migrations


def add_listed(apps, schema_editor):
    Stage = apps.get_model("deals", "Stage")
    if Stage.objects.filter(key="listed").exists():
        return
    evaluating = Stage.objects.filter(key="evaluating").first()
    order = (evaluating.order + 5) if evaluating else 15
    Stage.objects.create(key="listed", name="Listed", order=order, category="active", is_contract_stage=False)


def remove_listed(apps, schema_editor):
    Stage = apps.get_model("deals", "Stage")
    stage = Stage.objects.filter(key="listed").first()
    if stage and not stage.deals.exists():
        stage.delete()


class Migration(migrations.Migration):
    dependencies = [("deals", "0003_listing_fields")]
    operations = [migrations.RunPython(add_listed, remove_listed)]
