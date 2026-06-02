"""
Modelos de la app personal.

Doctor        — perfil profesional de un médico dentro de un tenant.
               Apunta a TenantMembership (OneToOne) para reutilizar la identidad
               del usuario. Un médico en 2 clínicas tiene un Doctor por clínica.
Consultorio   — espacio físico donde se atienden pacientes (sala, box, etc.).
DoctorSchedule — bloque de horario disponible de un médico en un consultorio.
               Los tiempos se almacenan en hora local del tenant; se convierten a UTC
               al comparar disponibilidad en el service de agenda (diseño 5.3).

Todos heredan de TenantAwareModel (id UUID, timestamps, soft-delete, tenant FK,
created_by, TenantManager con filtro por tenant activo).
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import TenantAwareModel


class Doctor(TenantAwareModel):
    """Perfil clínico de un médico dentro de un tenant (clínica).

    La identidad del usuario se obtiene a través de membership:
        doctor.membership.user.full_name

    Unicidad de `membership`: un TenantMembership puede tener como máximo un
    Doctor ACTIVO (deleted_at IS NULL). Se modela con un índice único parcial
    (Meta.constraints) en vez de un OneToOneField, para que un Doctor
    soft-deleted no bloquee la re-creación del perfil con la misma membresía.
    El service garantiza que membership.role == 'doctor'.
    """

    membership = models.ForeignKey(
        "tenancy.TenantMembership",
        on_delete=models.PROTECT,
        unique=False,
        related_name="doctor_profile",
        help_text="Membresía del médico en esta clínica. Role debe ser 'doctor'.",
    )
    cedula_profesional = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Cédula profesional emitida por la SEP.",
    )
    specialty = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Especialidad médica. Texto libre en v1; catálogo en v2.",
    )
    default_appointment_duration = models.PositiveSmallIntegerField(
        default=30,
        help_text="Duración default de cita para este médico, en minutos.",
    )
    bio_short = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Semblanza corta del médico (máx 255 caracteres).",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = médico inactivo (soft). No borra el registro.",
    )

    class Meta:
        db_table = "personal_doctors"
        ordering = ["-created_at"]
        constraints = [
            # Índice único parcial: un TenantMembership solo puede tener un
            # Doctor activo a la vez. Los soft-deleted (deleted_at NOT NULL)
            # quedan fuera del índice y por tanto no bloquean re-creación.
            models.UniqueConstraint(
                fields=["membership"],
                condition=Q(deleted_at__isnull=True),
                name="doctor_membership_active_uniq",
            ),
        ]

    @property
    def full_name(self) -> str:
        """Nombre completo derivado de la membresía del usuario."""
        return self.membership.user.full_name  # type: ignore[attr-defined]

    def __str__(self) -> str:
        specialty_label = self.specialty or "Sin especialidad"
        return f"{self.full_name} ({specialty_label})"


class Consultorio(TenantAwareModel):
    """Espacio físico donde se atienden pacientes (sala, box, consultorio, etc.).

    El campo color_hex se usa en la UI del calendario para distinguir consultorios.
    Constraint: nombre único por tenant.
    """

    name = models.CharField(
        max_length=100,
        help_text="Nombre del consultorio o sala. Único por clínica.",
    )
    location = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Ubicación física (piso, ala, edificio, etc.).",
    )
    color_hex = models.CharField(
        max_length=7,
        blank=True,
        default="",
        help_text="Color en formato hexadecimal (#RRGGBB) para el calendario.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = consultorio inactivo (soft). No borra el registro.",
    )

    class Meta:
        db_table = "personal_consultorios"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="consultorio_tenant_name_uniq",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Weekday(models.IntegerChoices):
    """Días de la semana en español.

    0 = Lunes ... 6 = Domingo (convención ISO 8601 adaptada).
    Se usa en DoctorSchedule.day_of_week.
    """

    LUNES = 0, "Lunes"
    MARTES = 1, "Martes"
    MIERCOLES = 2, "Miércoles"
    JUEVES = 3, "Jueves"
    VIERNES = 4, "Viernes"
    SABADO = 5, "Sábado"
    DOMINGO = 6, "Domingo"


class DoctorSchedule(TenantAwareModel):
    """Bloque de horario disponible de un médico.

    IMPORTANTE — zona horaria (diseño 5.3):
        start_time y end_time se almacenan en hora LOCAL del tenant
        (Tenant.timezone, por defecto "America/Mexico_City").
        NO son UTC. El service de agenda los debe convertir a UTC cuando
        compara disponibilidad con citas (agenda_appointments.starts_at que sí es UTC).

    Un "L-V 9-14 y 16-19" se representa como 10 filas (5 días × 2 bloques).
    """

    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="schedules",
        help_text="Médico al que pertenece este bloque de horario.",
    )
    day_of_week = models.PositiveSmallIntegerField(
        choices=Weekday.choices,
        help_text="Día de la semana (0=Lunes, 6=Domingo).",
    )
    start_time = models.TimeField(
        help_text="Hora de inicio en hora LOCAL del tenant (no UTC). Ver docstring del modelo.",
    )
    end_time = models.TimeField(
        help_text="Hora de fin en hora LOCAL del tenant (no UTC). Debe ser > start_time.",
    )
    consultorio = models.ForeignKey(
        Consultorio,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedules",
        help_text="Consultorio asignado a este bloque (opcional).",
    )
    valid_from = models.DateField(
        null=True,
        blank=True,
        help_text="Fecha desde la que aplica este horario (inclusive). Null = sin límite.",
    )
    valid_until = models.DateField(
        null=True,
        blank=True,
        help_text="Fecha hasta la que aplica este horario (inclusive). Null = sin límite.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = horario desactivado (soft). Se ignora en la agenda.",
    )

    class Meta:
        db_table = "personal_doctor_schedules"
        ordering = ["day_of_week", "start_time"]
        indexes = [
            models.Index(
                fields=["tenant", "doctor", "day_of_week"],
                name="schedule_doctor_day_idx",
            ),
        ]

    def clean(self) -> None:
        """Valida que end_time sea posterior a start_time."""
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError(
                {"end_time": "La hora de fin debe ser posterior a la hora de inicio."}
            )

    def __str__(self) -> str:
        day_label = Weekday(self.day_of_week).label if self.day_of_week is not None else "?"
        return (
            f"{self.doctor} — {day_label} "
            f"{self.start_time:%H:%M}-{self.end_time:%H:%M}"
        )
