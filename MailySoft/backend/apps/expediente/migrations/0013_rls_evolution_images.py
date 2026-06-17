"""
Migración de seguridad: habilita RLS en expediente_evolution_images.

Patrón idéntico al de 0010_rls_evolution_addendum_diagnosis.py con USING y
WITH CHECK desde el inicio (lección aprendida en 0005_rls_with_check.py — ALTO-2).

Configuración:
    ENABLE ROW LEVEL SECURITY — activa RLS en la tabla.
    FORCE ROW LEVEL SECURITY  — aplica RLS también al propietario de la tabla
                                 (el usuario de Django con el que corre la app).
    POLICY USING + WITH CHECK — el tenant_id del row debe coincidir con el
                                 current_tenant_id() del contexto activo.
                                 La cláusula IS NULL preserva acceso de Celery,
                                 management commands y migraciones (sin tenant activo).

Reversible: la dirección inversa deshabilita RLS y elimina la política.
"""

from django.db import migrations

_TABLE = "expediente_evolution_images"
_POLICY = "exp_evolution_images_tenant_iso"
_TENANT_CONDITION: str = "tenant_id = current_tenant_id() OR current_tenant_id() IS NULL"

_FORWARD_SQL: str = "\n".join(
    [
        f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;",
        (
            f"CREATE POLICY {_POLICY} ON {_TABLE} "
            f"USING ({_TENANT_CONDITION}) "
            f"WITH CHECK ({_TENANT_CONDITION});"
        ),
    ]
)

_REVERSE_SQL: str = "\n".join(
    [
        f"DROP POLICY IF EXISTS {_POLICY} ON {_TABLE};",
        f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY;",
    ]
)


class Migration(migrations.Migration):
    """Habilita RLS con USING y WITH CHECK en expediente_evolution_images."""

    dependencies = [
        ("expediente", "0012_add_evolution_images"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_FORWARD_SQL,
            reverse_sql=_REVERSE_SQL,
        ),
    ]
