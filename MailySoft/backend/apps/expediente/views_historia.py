"""
Vistas de la Historia Clínica del paciente (A2).

Extraído de expediente/views.py. GET devuelve la HC viva (o estructura vacía);
PUT hace upsert. Vista delgada con bitácora NOM-024.
"""

import logging
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.core.permissions import MedicalHistoryPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.expediente.selectors import medical_history_get_for_patient
from apps.expediente.serializers import (
    MedicalHistoryInputSerializer,
    MedicalHistoryOutputSerializer,
)
from apps.expediente.services import medical_history_upsert
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get

logger = logging.getLogger("apps.expediente.views_historia")


class MedicalHistoryApi(TenantAPIView):
    """GET /api/v1/expediente/<patient_id>/historia/ — devuelve la HC del paciente.
    PUT /api/v1/expediente/<patient_id>/historia/ — upsert de la HC.

    GET: si el paciente no tiene HC aún, devuelve un documento vacío (estructura
    con todos los bloques como {} y textos como "") con status 200. La decisión de
    no devolver 404 es consistente con el concepto de "documento vivo": siempre
    existe conceptualmente, aunque esté vacío.

    PUT: upsert completo. Crea la HC si no existe; actualiza la existente si ya
    hay una. Devuelve 200 con la HC resultante (creada o actualizada). No devuelve
    201 porque el contrato del endpoint es idempotente (upsert = misma URL siempre).

    Valida IDOR: patient_id debe pertenecer al tenant del request (TenantManager).
    Validación estricta D-EC-7: campos desconocidos → 400.
    """

    permission_classes = [IsAuthenticated, MedicalHistoryPermission]

    @staticmethod
    def _empty_history() -> dict:
        """Construye un documento HC vacío en cada llamada.

        BAJO-2: no usar un dict de clase compartido entre requests. Los sub-dicts
        (heredo_familiares, etc.) serían el mismo objeto mutable en memoria si se
        usara un atributo de clase, lo que podría causar estado compartido entre
        requests en workers multi-hilo. Esta función construye un documento fresco
        en cada llamada eliminando ese riesgo.
        """
        return {
            "id": None,
            "patient_id": None,
            "heredo_familiares": {},
            "personales_patologicos": {},
            "no_patologicos": {},
            "habitos_alimenticios": {},
            "gineco_obstetricos": {},
            "exploracion_fisica_basal": {},
            "antecedentes_importancia": "",
            "padecimiento_actual": "",
            "tratamientos_actuales": "",
            "prioridad_analisis": "",
            "created_at": None,
            "updated_at": None,
        }

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Devuelve la HC del paciente.

        Si el paciente no existe o es de otro tenant → 404 (anti-IDOR).
        Si no tiene HC aún → 200 con documento vacío.
        Si tiene HC → 200 con la HC serializada.

        Registra MEDICAL_HISTORY_READ en AuditLog (NOM-024).

        ALTO-1 — trade-off disponibilidad vs registro estricto (NOM-024):
        Si audit_record devuelve None (falla interna de la bitácora), el acceso
        NO se deniega: un médico en una urgencia no puede quedar bloqueado por
        un fallo de log. Sin embargo, el fallo se eleva a logger.critical para que
        aparezca en alertas de operaciones y pueda investigarse.
        Si en el futuro el equipo decide denegar el acceso cuando la bitácora falla,
        basta con descartar la respuesta y devolver:
            return Response({"detail": "Servicio de auditoría no disponible."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        """
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        history = medical_history_get_for_patient(patient=patient)

        # Registrar lectura de HC (NOM-024). resource_repr = UUID o "" si aún no existe.
        tenant = get_current_tenant()
        audit_result = audit_record(
            action=ActionType.MEDICAL_HISTORY_READ,
            resource_type="MedicalHistory",
            actor=request.user,
            tenant=tenant,
            resource_id=history.id if history is not None else None,
            resource_repr=str(history.id) if history is not None else "",
            metadata={"patient_id": str(patient.id)},
        )

        # ALTO-1: fallo de bitácora → alerta crítica. Solo UUIDs, nunca PII clínica.
        if audit_result is None:
            logger.critical(
                "ACCESO A EXPEDIENTE SIN REGISTRO EN BITÁCORA — "
                "acción MEDICAL_HISTORY_READ no pudo guardarse. "
                "tenant_id=%s patient_id=%s actor_id=%s. "
                "Revisar disponibilidad de BD de auditoría.",
                str(tenant.id) if tenant is not None else "None",
                str(patient.id),
                str(getattr(request.user, "pk", "anon")),
            )
            # El acceso continúa (disponibilidad clínica > registro estricto).
            # Para denegar en caso de fallo, sustituir las líneas siguientes por:
            #   return Response({"detail": "Servicio de auditoría no disponible."},
            #                   status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if history is None:
            # Documento vacío con patient_id relleno — construido fresco (BAJO-2).
            empty = self._empty_history()
            empty["patient_id"] = str(patient.id)
            return Response(empty, status=status.HTTP_200_OK)

        return Response(
            MedicalHistoryOutputSerializer(history).data,
            status=status.HTTP_200_OK,
        )

    def put(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Crea o actualiza la HC del paciente (upsert).

        Si el paciente no existe o es de otro tenant → 404 (anti-IDOR).
        Valida entrada estricta (D-EC-7). Delega upsert al service.
        Devuelve 200 con la HC resultante.
        """
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Pasar el paciente al context del serializer para la validación condicional
        # de gineco_obstetricos por sexo.
        s = MedicalHistoryInputSerializer(
            data=request.data,
            context={"patient": patient},
        )
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            history = medical_history_upsert(
                tenant=tenant,
                user=request.user,
                patient=patient,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            MedicalHistoryOutputSerializer(history).data,
            status=status.HTTP_200_OK,
        )
