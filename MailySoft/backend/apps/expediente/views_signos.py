"""
Vistas de signos vitales (A3) — append-only.

Extraído de expediente/views.py. Lista/crea tomas de signos vitales y devuelve
series para gráficas. Vistas delgadas con bitácora NOM-024.
"""

import logging
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.core.permissions import VitalSignsPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.expediente.selectors import vital_signs_list, vital_signs_series
from apps.expediente.serializers import (
    VitalSignsInputSerializer,
    VitalSignsOutputSerializer,
)
from apps.expediente.services import vital_signs_create
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get

logger = logging.getLogger("apps.expediente.views_signos")


class _VitalSignsPagination(PageNumberPagination):
    """Paginación para el listado de signos vitales.

    MEDIO-3: page_size=50 con máximo de 200 registros por página para evitar
    que un cliente pida toda la tabla de una vez.
    """

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class VitalSignsListCreateApi(TenantAPIView):
    """GET  /api/v1/expediente/<patient_id>/signos/ — lista tomas de signos vitales.
    POST /api/v1/expediente/<patient_id>/signos/ — registra una toma nueva.

    APPEND-ONLY (D-EC-1/D-EC-5): las tomas son inmutables. No existen endpoints
    PATCH, PUT ni DELETE sobre una toma individual. Solo GET y POST están ruteados.

    GET: devuelve las tomas del paciente paginadas (page_size=50, máx 200),
         ordenadas por -measured_at, con el campo derivado `imc` incluido.
         MEDIO-3: el formato de respuesta incluye envoltura de paginación
         {count, next, previous, results}. El frontend debe consumir `results`.
         MEDIO-2: registra VITALSIGNS_READ en AuditLog (NOM-024). Si audit_record
         devuelve None → logger.critical pero el acceso continúa (mismo trade-off
         que MedicalHistoryApi.get — disponibilidad clínica > registro estricto).

    POST: valida input estricto (D-EC-7), resuelve el appointment si se provee,
          y delega la creación al service vital_signs_create.
          Responde 201 con la toma serializada.

    ALTO-1 — Oracle de existencia cross-tenant corregido:
        patient_id se resuelve por TenantManager → 404 si es de otro tenant.
        appointment_id (si se provee) se resuelve con Appointment.objects.get
        seguido de validación explícita de tenant e igualdad de paciente;
        CUALQUIER fallo (inexistente, otro tenant, otro paciente) devuelve
        HTTP 404 con el MISMO mensaje "Cita no encontrada." para no filtrar
        información sobre citas de otras clínicas.

    Permisos (VitalSignsPermission):
        GET  → CLINICAL_READ: owner, admin, doctor, nurse, readonly.
        POST → owner, admin, doctor, nurse (enfermería captura signos).
    """

    permission_classes = [IsAuthenticated, VitalSignsPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Lista las tomas de signos vitales del paciente (-measured_at), paginadas.

        MEDIO-2: registra VITALSIGNS_READ en la bitácora de auditoría (NOM-024).
        MEDIO-3: aplica paginación con envoltura {count, next, previous, results}.
        """
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # MEDIO-2: auditar lectura de signos vitales (NOM-024).
        # resource_repr = UUID del paciente (sin PII clínica).
        tenant = get_current_tenant()
        audit_result = audit_record(
            action=ActionType.VITALSIGNS_READ,
            resource_type="VitalSignsRecord",
            actor=request.user,
            tenant=tenant,
            resource_id=None,
            resource_repr=str(patient.id),
            metadata={"patient_id": str(patient.id)},
        )
        if audit_result is None:
            logger.critical(
                "ACCESO A EXPEDIENTE SIN REGISTRO EN BITÁCORA — "
                "acción VITALSIGNS_READ no pudo guardarse. "
                "tenant_id=%s patient_id=%s actor_id=%s. "
                "Revisar disponibilidad de BD de auditoría.",
                str(tenant.id) if tenant is not None else "None",
                str(patient.id),
                str(getattr(request.user, "pk", "anon")),
            )
            # El acceso continúa (disponibilidad clínica > registro estricto).

        qs = vital_signs_list(patient=patient)

        # MEDIO-3: paginación obligatoria.
        paginator = _VitalSignsPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(
                VitalSignsOutputSerializer(page, many=True).data
            )
        # Fallback defensivo (no debería ocurrir con PAGE_SIZE configurado).
        return Response(
            {"detail": "Paginación no disponible. Configura PAGE_SIZE en settings."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Registra una toma nueva de signos vitales (append-only).

        ALTO-1: cualquier fallo al resolver appointment_id (inexistente, otro
        tenant, otro paciente) devuelve siempre 404 con el mismo mensaje.
        """
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = VitalSignsInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ALTO-1 — Resolución segura de appointment_id.
        # Todos los fallos (inexistente, otro tenant, otro paciente) → 404 idéntico.
        # Esto evita que el cliente infiera la existencia de citas de otras clínicas
        # comparando códigos HTTP diferentes (oracle de existencia cross-tenant).
        appointment = None
        appointment_id = s.validated_data.pop("appointment_id", None)
        if appointment_id is not None:
            from apps.agenda.models import Appointment  # noqa: PLC0415

            _NOT_FOUND = Response(
                {"detail": "Cita no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )
            try:
                appointment = Appointment.objects.get(id=appointment_id)
            except Appointment.DoesNotExist:
                return _NOT_FOUND

            # Validar que la cita pertenezca al tenant activo Y al paciente indicado.
            # Cualquier discrepancia → 404 (mismo mensaje — no revelar existencia).
            if appointment.tenant_id != tenant.id or appointment.patient_id != patient.id:
                return _NOT_FOUND

        try:
            record = vital_signs_create(
                tenant=tenant,
                user=request.user,
                patient=patient,
                appointment=appointment,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            VitalSignsOutputSerializer(record).data,
            status=status.HTTP_201_CREATED,
        )


class VitalSignsSeriesApi(TenantAPIView):
    """GET /api/v1/expediente/<patient_id>/signos/series/

    Devuelve un objeto con una clave por parámetro numérico.
    Cada clave contiene una lista de `{measured_at: <ISO>, value: <número>}` en
    orden ASC por measured_at, omitiendo registros donde el valor es null.

    Uso principal: alimentar gráficas de tendencia en el frontend.

    MEDIO-2: registra VITALSIGNS_READ en AuditLog (NOM-024). Si audit_record
    devuelve None → logger.critical pero el acceso continúa (mismo trade-off que
    MedicalHistoryApi.get — disponibilidad clínica > registro estricto).

    MEDIO-3 — Query param opcional `?since=<YYYY-MM-DD>`:
        Limita el rango temporal. Solo se devuelven los registros con
        measured_at >= since. Además el selector aplica un tope interno de
        730 registros (≈ 2 años de tomas diarias) para proteger contra cargar
        historiales enormes en memoria. El tope es transparente al cliente:
        no aparece en la respuesta (no hay paginación en series).

    Permisos: CLINICAL_READ (GET). Mismo conjunto que la lista de tomas.
    """

    permission_classes = [IsAuthenticated, VitalSignsPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Devuelve las series temporales de todos los parámetros del paciente.

        MEDIO-2: registra VITALSIGNS_READ en la bitácora de auditoría (NOM-024).
        MEDIO-3: acepta ?since=<YYYY-MM-DD> para limitar el rango.
        """
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # MEDIO-3: parsear ?since= (fecha ISO YYYY-MM-DD, opcional).
        since_param: str | None = request.query_params.get("since")
        since_date = None
        if since_param is not None:
            import datetime  # noqa: PLC0415
            try:
                since_date = datetime.date.fromisoformat(since_param)
            except ValueError:
                return Response(
                    {"detail": "El parámetro 'since' debe tener formato YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # MEDIO-2: auditar lectura de series de signos vitales (NOM-024).
        # resource_repr = UUID del paciente (sin PII clínica).
        tenant = get_current_tenant()
        audit_result = audit_record(
            action=ActionType.VITALSIGNS_READ,
            resource_type="VitalSignsRecord",
            actor=request.user,
            tenant=tenant,
            resource_id=None,
            resource_repr=str(patient.id),
            metadata={"patient_id": str(patient.id), "endpoint": "series"},
        )
        if audit_result is None:
            logger.critical(
                "ACCESO A EXPEDIENTE SIN REGISTRO EN BITÁCORA — "
                "acción VITALSIGNS_READ (series) no pudo guardarse. "
                "tenant_id=%s patient_id=%s actor_id=%s. "
                "Revisar disponibilidad de BD de auditoría.",
                str(tenant.id) if tenant is not None else "None",
                str(patient.id),
                str(getattr(request.user, "pk", "anon")),
            )
            # El acceso continúa (disponibilidad clínica > registro estricto).

        data = vital_signs_series(patient=patient, since=since_date)
        return Response(data, status=status.HTTP_200_OK)
