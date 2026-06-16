"""
Migración inicial de la app expediente — sub-fase A1.

Crea la tabla expediente_allergies.
"""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Crea el modelo Allergy (expediente_allergies)."""

    initial = True

    dependencies = [
        ("pacientes", "0006_patient_nom004_fields"),
        ("tenancy", "0003_alter_tenantmembership_unique_together_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Allergy",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "deleted_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        help_text="NULL = activo. Rellenar para borrado lógico.",
                        null=True,
                    ),
                ),
                (
                    "substance",
                    models.CharField(
                        help_text="Sustancia o medicamento al que el paciente es alérgico.",
                        max_length=160,
                    ),
                ),
                (
                    "reaction",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Reacción observada (opcional).",
                        max_length=255,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("leve", "Leve"),
                            ("moderada", "Moderada"),
                            ("severa", "Severa"),
                        ],
                        default="",
                        help_text="Severidad de la reacción: leve, moderada o severa.",
                        max_length=10,
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        db_index=True,
                        default=True,
                        help_text=(
                            "True = alergia vigente (clínica). "
                            "False = resuelta (baja lógica). "
                            "Nunca se borra físicamente (D-EC-5)."
                        ),
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        help_text=(
                            "Usuario que creó el registro. Null en imports/seeds "
                            "o si el usuario fue borrado."
                        ),
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        db_index=True,
                        help_text="Paciente al que pertenece la alergia.",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="allergies",
                        to="pacientes.patient",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        help_text="Clínica a la que pertenece este registro.",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="tenancy.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "expediente_allergies",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["patient", "is_active"],
                        name="allergy_patient_active_idx",
                    ),
                ],
            },
        ),
    ]
