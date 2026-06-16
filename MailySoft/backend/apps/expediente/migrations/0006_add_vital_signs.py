"""
Migración A3: crea la tabla expediente_vital_signs para VitalSignsRecord.

Decisiones:
  D-EC-5 — sin borrado físico: no hay campo is_active ni soft-delete de negocio.
            Las tomas son append-only; no se borran.
  D-EC-6 — IMC derivado: no se almacena (property en el modelo).
  D-EC-8 — extra_params: JSONField con whitelist en serializer.

El índice (tenant_id, patient_id, measured_at) soporta historial y series temporales.

FK agenda.Appointment usa SET_NULL para que borrar una cita no elimine las tomas.
"""

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Crea el modelo VitalSignsRecord (expediente_vital_signs)."""

    dependencies = [
        ("agenda", "0010_appointment_reschedule_count"),
        ("expediente", "0005_rls_with_check"),
        ("pacientes", "0008_merge_20260616_1224"),
        ("tenancy", "0003_alter_tenantmembership_unique_together_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VitalSignsRecord",
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
                    "measured_at",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                        help_text=(
                            "Momento de la toma. Por defecto = ahora. "
                            "No se permite fecha futura; sí se permiten tomas retroactivas."
                        ),
                    ),
                ),
                (
                    "weight_kg",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text="Peso corporal en kilogramos. Rango válido: 0.2 – 500.",
                        max_digits=5,
                        null=True,
                    ),
                ),
                (
                    "height_m",
                    models.DecimalField(
                        blank=True,
                        decimal_places=3,
                        help_text="Talla en metros. Rango válido: 0.2 – 2.6.",
                        max_digits=4,
                        null=True,
                    ),
                ),
                (
                    "heart_rate",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        help_text="Frecuencia cardíaca en lpm. Rango válido: 20 – 300.",
                        null=True,
                    ),
                ),
                (
                    "resp_rate",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        help_text="Frecuencia respiratoria en rpm. Rango válido: 5 – 80.",
                        null=True,
                    ),
                ),
                (
                    "systolic",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        help_text="Presión sistólica en mmHg. Rango válido: 40 – 300.",
                        null=True,
                    ),
                ),
                (
                    "diastolic",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        help_text=(
                            "Presión diastólica en mmHg. Rango válido: 20 – 200. "
                            "Debe ser < sistólica."
                        ),
                        null=True,
                    ),
                ),
                (
                    "temperature_c",
                    models.DecimalField(
                        blank=True,
                        decimal_places=1,
                        help_text="Temperatura corporal en °C. Rango válido: 30 – 45.",
                        max_digits=4,
                        null=True,
                    ),
                ),
                (
                    "oxygen_saturation",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        help_text="Saturación de oxígeno en %. Rango válido: 50 – 100.",
                        null=True,
                    ),
                ),
                (
                    "glucose",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        help_text="Glucosa en mg/dL. Rango válido: 10 – 1000.",
                        null=True,
                    ),
                ),
                (
                    "extra_params",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text=(
                            "Parámetros del legacy. Claves permitidas: "
                            "colesterol, trigliceridos, urea, creatinina, hemoglobina."
                        ),
                    ),
                ),
                (
                    "notes",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text=(
                            "Observaciones breves del responsable de la toma "
                            "(máx 255 caracteres)."
                        ),
                        max_length=255,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=True,
                        help_text="Clínica a la que pertenece este registro.",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="tenancy.tenant",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        help_text=(
                            "Usuario que creó el registro. "
                            "Null en imports/seeds o si el usuario fue borrado."
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
                        help_text="Paciente al que pertenece la toma.",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="vital_signs",
                        to="pacientes.patient",
                    ),
                ),
                (
                    "appointment",
                    models.ForeignKey(
                        blank=True,
                        db_index=True,
                        help_text=(
                            "Cita médica asociada a esta toma (opcional). "
                            "Si se provee, debe pertenecer al mismo paciente y tenant."
                        ),
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="vital_signs",
                        to="agenda.appointment",
                    ),
                ),
            ],
            options={
                "db_table": "expediente_vital_signs",
                "ordering": ["-measured_at"],
            },
        ),
        migrations.AddIndex(
            model_name="vitalsignsrecord",
            index=models.Index(
                fields=["tenant", "patient", "measured_at"],
                name="vitals_tenant_patient_time_idx",
            ),
        ),
    ]
