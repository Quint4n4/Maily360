"""
Fusión Favoritos/VIP → etiquetas (Camino A).

1. Crea las etiquetas de sistema "Favorito" y "VIP" (kind) en cada clínica.
   Si ya existía una etiqueta con ese nombre (custom), la promueve a sistema.
2. Migra los pacientes ya marcados: is_favorite/is_vip → relación M2M categories.

Se ejecuta ANTES de eliminar las columnas is_favorite/is_vip (migración 0011),
por lo que el estado histórico aquí todavía las expone.
"""

from django.db import migrations

_SYSTEM = {"favorite": "Favorito", "vip": "VIP"}


def migrar(apps, schema_editor):
    Tenant = apps.get_model("tenancy", "Tenant")
    PatientCategory = apps.get_model("clinica", "PatientCategory")
    Patient = apps.get_model("pacientes", "Patient")

    for tenant in Tenant.objects.all():
        cats = {}
        for kind, name in _SYSTEM.items():
            cat = PatientCategory.objects.filter(
                tenant=tenant, kind=kind, deleted_at__isnull=True
            ).first()
            if cat is None:
                # Reutiliza una etiqueta existente con ese nombre (promueve a sistema).
                existing = PatientCategory.objects.filter(
                    tenant=tenant, name=name, deleted_at__isnull=True
                ).first()
                if existing is not None:
                    existing.kind = kind
                    existing.save(update_fields=["kind"])
                    cat = existing
                else:
                    cat = PatientCategory.objects.create(
                        tenant=tenant, name=name, kind=kind, is_active=True
                    )
            cats[kind] = cat

        for patient in Patient.objects.filter(tenant=tenant):
            if getattr(patient, "is_favorite", False):
                patient.categories.add(cats["favorite"])
            if getattr(patient, "is_vip", False):
                patient.categories.add(cats["vip"])


def revertir(apps, schema_editor):
    """Reversa best-effort: repuebla los flags desde el M2M y borra las de sistema."""
    PatientCategory = apps.get_model("clinica", "PatientCategory")
    Patient = apps.get_model("pacientes", "Patient")

    for patient in Patient.objects.all():
        kinds = set(patient.categories.values_list("kind", flat=True))
        if hasattr(patient, "is_favorite"):
            patient.is_favorite = "favorite" in kinds
        if hasattr(patient, "is_vip"):
            patient.is_vip = "vip" in kinds
        patient.save()

    PatientCategory.objects.filter(kind__in=["favorite", "vip"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("pacientes", "0009_patient_categories_alter_patient_category"),
        ("clinica", "0009_patientcategory_kind_and_more"),
    ]

    operations = [
        migrations.RunPython(migrar, revertir),
    ]
