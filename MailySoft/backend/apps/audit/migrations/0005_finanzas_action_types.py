"""
Amplía los choices de AuditLog.action con los eventos del dominio finanzas.

Solo cambia los choices (validación a nivel modelo); no altera el esquema de la
columna (sigue siendo varchar(30)). Se incluye para mantener el estado de
migraciones consistente con el modelo (makemigrations --check verde en CI).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0004_alter_auditlog_action"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditlog",
            name="action",
            field=models.CharField(
                choices=[
                    ("PATIENT_CREATE", "Crear paciente"),
                    ("PATIENT_READ", "Leer ficha de paciente"),
                    ("PATIENT_UPDATE", "Actualizar paciente"),
                    ("PATIENT_DEACTIVATE", "Desactivar paciente"),
                    ("APPOINTMENT_CREATE", "Crear cita"),
                    ("APPOINTMENT_UPDATE", "Actualizar cita"),
                    ("APPOINTMENT_STATUS", "Cambiar estado de cita"),
                    ("APPOINTMENT_RESCHEDULE", "Reagendar cita"),
                    ("DOCTOR_CREATE", "Crear médico"),
                    ("DOCTOR_UPDATE", "Actualizar médico"),
                    ("DOCTOR_DEACTIVATE", "Desactivar médico"),
                    ("CONSULTORIO_CREATE", "Crear consultorio"),
                    ("CONSULTORIO_UPDATE", "Actualizar consultorio"),
                    ("CONSULTORIO_DEACTIVATE", "Desactivar consultorio"),
                    ("SCHEDULE_CREATE", "Crear horario"),
                    ("SCHEDULE_DEACTIVATE", "Desactivar horario"),
                    ("CONFIG_UPDATE", "Actualizar configuración de agenda"),
                    ("CONCEPT_CREATE", "Crear concepto cobrable"),
                    ("CONCEPT_UPDATE", "Actualizar concepto cobrable"),
                    ("CONCEPT_DEACTIVATE", "Desactivar concepto cobrable"),
                    ("QUOTE_CREATE", "Crear cotización"),
                    ("QUOTE_UPDATE", "Actualizar cotización"),
                    ("QUOTE_STATUS", "Cambiar estado de cotización"),
                    ("CHARGE_CREATE", "Crear cargo"),
                    ("CHARGE_CANCEL", "Cancelar cargo"),
                    ("PAYMENT_REGISTER", "Registrar pago"),
                    ("CFDI_ISSUE", "Emitir CFDI"),
                    ("CFDI_CANCEL", "Cancelar CFDI"),
                    ("FISCAL_CONFIG_UPDATE", "Actualizar configuración fiscal"),
                    ("LOGIN", "Inicio de sesión"),
                    ("LOGOUT", "Cierre de sesión"),
                    ("LOGIN_FAILED", "Intento de sesión fallido"),
                ],
                db_index=True,
                help_text="Tipo de acción realizada (ActionType).",
                max_length=30,
            ),
        ),
    ]
