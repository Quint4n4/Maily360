# Generated manually — Maily360 sucursales, cierre de hueco en apps.notas.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notas", "0002_enable_rls"),
        ("clinica", "0018_rls_membership_sucursales"),
    ]

    operations = [
        migrations.AddField(
            model_name="note",
            name="sucursal",
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                help_text=(
                    "Sucursal (sede) a la que está acotado el aviso (scope=role|all). "
                    "Null = aviso de TODA la clínica (todas las sedes). Siempre null "
                    "en notas personales (scope=personal, que no tienen noción de "
                    "sede). Un no-owner solo puede crear/editar avisos en SU propia "
                    "sede (ver apps.clinica.sucursal_scope); solo el owner puede "
                    "elegir 'todas las sedes' o una sede específica libremente."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="clinica.sucursal",
            ),
        ),
        migrations.AddField(
            model_name="note",
            name="is_important",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Aviso destacado/importante. Solo el OWNER puede crearlo o "
                    "editarlo con este valor en True; un no-owner nunca puede "
                    "marcar ni mutar un aviso importante (services.py lo rechaza)."
                ),
            ),
        ),
    ]
