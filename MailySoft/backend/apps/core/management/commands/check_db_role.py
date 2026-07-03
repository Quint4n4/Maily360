"""Diagnostica el rol de conexión a PostgreSQL: ¿es NOSUPERUSER (RLS aplica)?

Contexto (Fase 5 / pgbouncer-rls-escalabilidad.md): el aislamiento multi-tenant
usa RLS con `FORCE ROW LEVEL SECURITY` como SEGUNDA barrera (la primera es el
TenantManager de Django). PERO PostgreSQL EXIME a los roles superuser (y a los
que tienen BYPASSRLS) de toda política RLS, incluso con FORCE. Si la app se
conecta con un rol superuser, esa segunda barrera queda INERTE: la única
defensa real es el filtro de aplicación.

Este comando reporta el rol de conexión actual y advierte si RLS no aplicaría.
Es seguro de correr en cualquier entorno (solo lee catálogos del sistema).

Uso:
    python manage.py check_db_role

En Railway (desde el servicio backend o con la CLI):
    railway run python manage.py check_db_role

Código de salida: 0 si el rol NO es superuser ni bypassrls (RLS aplica);
1 si el rol evade RLS (superuser o bypassrls) — útil para scripts/CI.
"""

from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Reporta el rol de conexión a PostgreSQL y si RLS aplica (NOSUPERUSER)."

    def handle(self, *args: Any, **options: Any) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user, current_database()")
            current_user, current_database = cursor.fetchone()

            cursor.execute(
                """
                SELECT rolsuper, rolbypassrls
                FROM pg_roles
                WHERE rolname = current_user
                """
            )
            row = cursor.fetchone()

        is_super = bool(row[0]) if row else False
        bypass_rls = bool(row[1]) if row else False
        evade_rls = is_super or bypass_rls

        self.stdout.write("")
        self.stdout.write(f"  Base de datos : {current_database}")
        self.stdout.write(f"  Usuario       : {current_user}")
        self.stdout.write(f"  SUPERUSER     : {is_super}")
        self.stdout.write(f"  BYPASSRLS     : {bypass_rls}")
        self.stdout.write("")

        if evade_rls:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  El rol EVADE Row Level Security (superuser o bypassrls).\n"
                    "    RLS + FORCE ROW LEVEL SECURITY NO aplica como segunda barrera:\n"
                    "    el aislamiento multi-tenant depende SOLO del TenantManager\n"
                    "    (capa de aplicación). Antes de escalar / activar pgbouncer,\n"
                    "    migra la conexión de la app a un rol NOSUPERUSER NOBYPASSRLS\n"
                    "    con GRANTs mínimos. Deja el rol superuser solo para migraciones\n"
                    "    y administración manual. Ver docs/design/pgbouncer-rls-escalabilidad.md."
                )
            )
            # Señal para scripts/CI, sin abortar con traza (es diagnóstico, no error).
            raise SystemExit(1)

        self.stdout.write(
            self.style.SUCCESS(
                "✅ El rol NO evade RLS: FORCE ROW LEVEL SECURITY aplica como\n"
                "   segunda barrera real de aislamiento multi-tenant."
            )
        )
