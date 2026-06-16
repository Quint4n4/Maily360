# Generated manually for A3 — Signos Vitales (VITALSIGNS_CREATE action)

from django.db import migrations, models


class Migration(migrations.Migration):
    """Agrega VITALSIGNS_CREATE al campo action de AuditLog (A3)."""

    dependencies = [
        ("audit", "0016_add_medical_history_actions"),
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
                    ("APPOINTMENT_REACTIVATE", "Reactivar cita cancelada"),
                    ("APPOINTMENT_TYPE_CREATE", "Crear tipo de cita"),
                    ("APPOINTMENT_TYPE_UPDATE", "Actualizar tipo de cita"),
                    ("APPOINTMENT_TYPE_DEACTIVATE", "Desactivar tipo de cita"),
                    ("AGENDA_EVENT_CREATE", "Crear evento de agenda (reunión/bloqueo)"),
                    ("AGENDA_EVENT_UPDATE", "Actualizar evento de agenda"),
                    ("AGENDA_EVENT_DELETE", "Eliminar evento de agenda"),
                    ("DOCTOR_CREATE", "Crear médico"),
                    ("DOCTOR_UPDATE", "Actualizar médico"),
                    ("DOCTOR_DEACTIVATE", "Desactivar médico"),
                    ("DOCTOR_CONSULTORIOS", "Asignar consultorios a médico"),
                    ("CONSULTORIO_CREATE", "Crear consultorio"),
                    ("CONSULTORIO_UPDATE", "Actualizar consultorio"),
                    ("CONSULTORIO_DEACTIVATE", "Desactivar consultorio"),
                    ("SCHEDULE_CREATE", "Crear horario"),
                    ("SCHEDULE_DEACTIVATE", "Desactivar horario"),
                    ("CONFIG_UPDATE", "Actualizar configuración de agenda"),
                    ("MEMBER_CREATE", "Alta de miembro"),
                    ("MEMBER_UPDATE", "Actualizar miembro (nombre/rol)"),
                    ("MEMBER_BLOCK", "Bloquear o reactivar cuenta de miembro"),
                    ("MEMBER_PASSWORD", "Restablecer contraseña de miembro"),
                    ("NOTE_CREATE", "Crear nota personal"),
                    ("NOTE_UPDATE", "Actualizar nota"),
                    ("NOTE_DELETE", "Eliminar nota"),
                    ("NOTE_GLOBAL_SEND", "Enviar nota global"),
                    ("AGENDA_NOTE_ADD", "Agregar nota a evento de agenda"),
                    ("AGENDA_NOTE_DELETE", "Eliminar nota de evento de agenda"),
                    ("ALLERGY_CREATE", "Registrar alergia"),
                    ("ALLERGY_RESOLVE", "Resolver alergia"),
                    ("MEDICAL_HISTORY_READ", "Leer historia clínica"),
                    ("MEDICAL_HISTORY_UPDATE", "Actualizar historia clínica"),
                    ("VITALSIGNS_CREATE", "Registrar signos vitales"),
                    ("TENANT_CREATE", "Crear clínica nueva"),
                    ("TENANT_STATUS_CHANGE", "Cambiar estado de clínica"),
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
