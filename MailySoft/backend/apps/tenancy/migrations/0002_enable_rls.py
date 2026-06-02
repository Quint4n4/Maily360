"""
Migración manual: crea la función helper `current_tenant_id()` en PostgreSQL.

Esta función es usada por las políticas de Row Level Security (RLS) en las
tablas tenant-aware. Las políticas se añaden en las migraciones de cada app
de negocio (agenda, pacientes, etc.) a partir del Paso 3.

Por qué aquí y no en el app de cada modelo:
- La función es compartida por TODAS las políticas.
- Centralizarla en tenancy evita redefinirla múltiples veces.

Reversible: DROP FUNCTION IF EXISTS.
"""

from django.db import migrations

# Crea la función helper que lee el setting de sesión con un default seguro.
# NULLIF(..., '') asegura que una cadena vacía devuelve NULL (no falla el cast).
# EXCEPTION WHEN OTHERS captura el caso en que el setting aún no existe
# (migraciones, management commands sin contexto de request).
ENABLE_RLS_SQL = """
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS uuid AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_tenant_id', true), '')::uuid;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;
"""

DISABLE_RLS_SQL = """
DROP FUNCTION IF EXISTS current_tenant_id();
"""


class Migration(migrations.Migration):
    """Crea la función PostgreSQL current_tenant_id() para RLS."""

    dependencies = [
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ENABLE_RLS_SQL,
            reverse_sql=DISABLE_RLS_SQL,
        ),
    ]
