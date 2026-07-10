"""
Serializers de la app pacientes.

Regla: serializers solo validan/formatean. Cero lógica de negocio aquí.

PatientOutputSerializer  — forma la respuesta (lectura). Incluye campos NOM-004
                           de la sub-fase A1 del Expediente Clínico.
Los InputSerializer se definen inline en cada view como clases anidadas
para mantener el contrato de validación cerca de la vista que lo usa.
"""

from rest_framework import serializers

from apps.core.permissions import APPOINTMENT_VIEW_ROLES
from apps.pacientes.models import Patient


class PatientOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para Patient.

    Incluye full_name como campo calculado (propiedad del modelo).
    Incluye todos los campos NOM-004 del Expediente Clínico A1 (plan §3.1).
    No expone campos de auditoría internos (deleted_at, created_by_id).

    Campos anotados (disponibles cuando el QuerySet viene de patient_list):
      - last_seen_at:    Última vez que el paciente fue atendido (datetime ISO o null).
      - attended_count:  Número de citas atendidas (int o null si no viene anotado).

    Usa getattr con default None para ser tolerante cuando el objeto viene de
    endpoints que no anotan (p.ej. patient_get en el detalle individual).
    """

    full_name = serializers.CharField(read_only=True)
    sex_display = serializers.CharField(source="get_sex_display", read_only=True)
    marital_status_display = serializers.CharField(
        source="get_marital_status_display", read_only=True
    )
    education_display = serializers.CharField(source="get_education_display", read_only=True)
    blood_type_display = serializers.CharField(source="get_blood_type_display", read_only=True)
    avatar = serializers.ImageField(read_only=True)
    last_seen_at = serializers.SerializerMethodField()
    attended_count = serializers.SerializerMethodField()
    last_reason = serializers.SerializerMethodField()
    categories = serializers.SerializerMethodField()
    is_favorite = serializers.SerializerMethodField()
    is_vip = serializers.SerializerMethodField()

    def get_last_seen_at(self, obj: Patient) -> object:
        """Devuelve la anotación last_seen si existe (null si no viene anotada)."""
        return getattr(obj, "last_seen", None)

    def get_attended_count(self, obj: Patient) -> object:
        """Devuelve la anotación attended_count si existe (null si no viene anotada)."""
        return getattr(obj, "attended_count", None)

    def get_last_reason(self, obj: Patient) -> object:
        """Motivo de la última cita cancelada/reagendada (null si no viene anotado).

        FIX CRÍTICO (seguridad): Appointment.reason es información clínica y
        AppointmentPermission.GET excluye deliberadamente al rol FINANCE (ver
        apps.core.permissions.APPOINTMENT_VIEW_ROLES). Sin este control, un
        usuario finance vería motivos clínicos vía /pacientes/ aunque el
        endpoint de citas se los niegue — una fuga de dato clínico por rol.

        Se reutiliza EXACTAMENTE el mismo conjunto de roles que
        AppointmentPermission.GET (APPOINTMENT_VIEW_ROLES) para que ambos
        controles nunca se desincronicen.

        Fail-closed: si no hay request en el contexto o no hay rol activo
        resuelto (p. ej. serialización fuera de un request HTTP, como en un
        script o comando de management), se devuelve None en vez de exponer
        el dato por defecto.
        """
        request = self.context.get("request")
        role = getattr(request, "active_role", None) if request is not None else None
        if role not in APPOINTMENT_VIEW_ROLES:
            return None
        return getattr(obj, "last_reason", None)

    def get_categories(self, obj: Patient) -> list[dict[str, str]]:
        """Etiquetas PERSONALIZADAS asignadas (las de sistema Favorito/VIP se
        exponen como is_favorite/is_vip). Usa el prefetch de patient_list."""
        return [
            {"id": str(c.id), "name": c.name} for c in obj.categories.all() if c.kind == "custom"
        ]

    def get_is_favorite(self, obj: Patient) -> bool:
        """Derivado: el paciente tiene la etiqueta de sistema 'Favorito'."""
        return any(c.kind == "favorite" for c in obj.categories.all())

    def get_is_vip(self, obj: Patient) -> bool:
        """Derivado: el paciente tiene la etiqueta de sistema 'VIP'."""
        return any(c.kind == "vip" for c in obj.categories.all())

    class Meta:
        model = Patient
        fields = [
            # Campos base del expediente
            "id",
            "full_name",
            "avatar",
            "first_name",
            "paternal_surname",
            "maternal_surname",
            "date_of_birth",
            "sex",
            "sex_display",
            "curp",
            "phone",
            "email",
            "record_number",
            "notes",
            "is_active",
            "is_provisional",
            "is_favorite",
            "is_vip",
            # Campos NOM-004 expediente A1 (plan §3.1)
            "address_street",
            "address_neighborhood",
            "city",
            "state",
            "postal_code",
            "birthplace",
            "marital_status",
            "marital_status_display",
            "education",
            "education_display",
            "occupation",
            "religion",
            "blood_type",
            "blood_type_display",
            "phone_secondary",
            "phone_label",
            "is_deceased",
            "deceased_at",
            "custom_consultation_fee",
            "category",
            "categories",
            # Auditoría y anotaciones
            "created_at",
            "last_seen_at",
            "attended_count",
            "last_reason",
        ]
        read_only_fields = fields
