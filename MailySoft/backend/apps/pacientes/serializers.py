"""
Serializers de la app pacientes.

Regla: serializers solo validan/formatean. Cero lógica de negocio aquí.

PatientOutputSerializer  — forma la respuesta (lectura).
Los InputSerializer se definen inline en cada view como clases anidadas
para mantener el contrato de validación cerca de la vista que lo usa.
"""

from rest_framework import serializers

from apps.pacientes.models import Patient, Sex


class PatientOutputSerializer(serializers.ModelSerializer):
    """Serializer de salida para Patient.

    Incluye full_name como campo calculado (propiedad del modelo).
    No expone campos de auditoría internos (deleted_at, created_by_id).
    """

    full_name = serializers.CharField(read_only=True)
    sex_display = serializers.CharField(source="get_sex_display", read_only=True)
    avatar = serializers.ImageField(read_only=True)

    class Meta:
        model = Patient
        fields = [
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
            "created_at",
        ]
        read_only_fields = fields
