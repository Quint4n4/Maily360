"""
Migración aditiva: agrega los campos NOM-004 al modelo Patient.

Sub-fase A1 del Expediente Clínico (plan §3.1).
Todos los campos son opcionales (blank=True / null=True / default="") para
convivir con expedientes provisionales ya existentes (D-06).

Reversible: cada AddField puede revertirse con RemoveField.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Agrega campos NOM-004 a pacientes_patients (aditiva, reversible)."""

    dependencies = [
        ("pacientes", "0005_patient_is_provisional_alter_patient_date_of_birth_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="patient",
            name="address_street",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Calle y número del domicilio.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="address_neighborhood",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Colonia del domicilio.",
                max_length=120,
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="city",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Ciudad de residencia.",
                max_length=120,
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="state",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Estado de residencia.",
                max_length=120,
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="postal_code",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Código postal (CP).",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="birthplace",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Lugar de nacimiento.",
                max_length=160,
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="marital_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("soltero", "Soltero/a"),
                    ("casado", "Casado/a"),
                    ("union_libre", "Unión libre"),
                    ("divorciado", "Divorciado/a"),
                    ("viudo", "Viudo/a"),
                    ("otro", "Otro"),
                ],
                default="",
                help_text="Estado civil (D-EC-8: opciones predefinidas).",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="education",
            field=models.CharField(
                blank=True,
                choices=[
                    ("ninguna", "Ninguna"),
                    ("primaria", "Primaria"),
                    ("secundaria", "Secundaria"),
                    ("preparatoria", "Preparatoria / Bachillerato"),
                    ("licenciatura", "Licenciatura"),
                    ("posgrado", "Posgrado"),
                ],
                default="",
                help_text="Escolaridad (D-EC-8: opciones predefinidas).",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="occupation",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Ocupación del paciente.",
                max_length=120,
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="religion",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Religión (opcional, libre).",
                max_length=80,
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="blood_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("A+", "A+"),
                    ("A-", "A-"),
                    ("B+", "B+"),
                    ("B-", "B-"),
                    ("AB+", "AB+"),
                    ("AB-", "AB-"),
                    ("O+", "O+"),
                    ("O-", "O-"),
                    ("desconocido", "Desconocido"),
                ],
                default="",
                help_text="Tipo de sangre ABO/Rh (D-EC-8: opciones predefinidas).",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="phone_secondary",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Segundo teléfono de contacto (opcional).",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="phone_label",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Etiqueta del segundo teléfono (ej. 'hija', 'esposo').",
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="is_deceased",
            field=models.BooleanField(
                default=False,
                help_text="True si el paciente ha fallecido (campo 'Finado').",
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="deceased_at",
            field=models.DateField(
                blank=True,
                null=True,
                help_text="Fecha de defunción. Null si is_deceased=False.",
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="custom_consultation_fee",
            field=models.DecimalField(
                blank=True,
                null=True,
                decimal_places=2,
                max_digits=10,
                help_text=(
                    "Costo de consulta personalizado para este paciente. "
                    "Null = usa la tarifa estándar de la clínica. Lo usará Finanzas."
                ),
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="category",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Categoría libre del paciente (uso interno de la clínica, v1).",
                max_length=60,
            ),
        ),
    ]
