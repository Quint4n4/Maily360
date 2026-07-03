"""
Migración de seguridad: agrega el fallback `OR current_tenant_id() IS NULL` al
WITH CHECK de las policies RLS de `clinica` que quedaron sin él.

Estas 5 policies se crearon con un WITH CHECK ESTRICTO
(`tenant_id = current_tenant_id()`), a diferencia del USING de las mismas
policies (que sí incluye `OR current_tenant_id() IS NULL`). Eso rompe los
INSERT hechos desde un contexto sin tenant fijado en el GUC — en particular el
alta de clínica (`tenant_and_owner_create` → `seed_system_patient_categories`,
`ClinicSettings`, etc.), que corre en `PlatformAPIView` (cross-tenant, GUC
vacío). Con un rol superuser el defecto quedaba oculto (RLS no aplica); con el
rol de aplicación NOSUPERUSER el INSERT era rechazado con
"new row violates row-level security policy".

El fallback IS NULL es el MISMO patrón que ya usan el USING de estas policies y
todas las demás tablas tenant-aware: los procesos con contexto (requests de
clínica) fijan el GUC y quedan restringidos a su tenant; los procesos sin
contexto (portal de plataforma, Celery, seeds, migraciones de datos) pueden
insertar cualquier tenant. No relaja el aislamiento de los requests de clínica.

Reversibilidad: vuelve al WITH CHECK estricto (solo USING-equivalente).
"""

from django.db import migrations

# (tabla, policy) — nombres tomados literalmente de pg_policies.
_POLICIES: list[tuple[str, str]] = [
    ("clinica_doctor_credentials", "clinica_doctor_credentials_tenant_isolation"),
    ("clinica_doctor_universities", "clinica_doctor_universities_tenant_isolation"),
    ("clinica_patient_categories", "clinica_patient_categories_tenant_isolation"),
    ("clinica_settings", "clinica_settings_tenant_isolation"),
    ("clinica_templates", "clinica_templates_tenant_isolation"),
]

_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"
_STRICT_CONDITION: str = "tenant_id = current_tenant_id()"


def _forward(table: str, policy: str) -> str:
    return f"ALTER POLICY {policy} ON {table} WITH CHECK ({_TENANT_CONDITION});"


def _reverse(table: str, policy: str) -> str:
    return f"ALTER POLICY {policy} ON {table} WITH CHECK ({_STRICT_CONDITION});"


class Migration(migrations.Migration):
    """Uniforma el WITH CHECK de las policies de clinica con el fallback IS NULL."""

    dependencies = [
        ("clinica", "0012_alter_clinicsettings_letterhead_full_and_more"),
    ]

    operations = [
        migrations.RunSQL(sql=_forward(t, p), reverse_sql=_reverse(t, p))
        for t, p in _POLICIES
    ]
