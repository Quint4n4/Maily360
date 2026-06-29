"""
Vistas de notas de evolución (A4 — inmutables) y diagnósticos.

Extraído de expediente/views.py. Comparten la paginación _EvolutionPagination,
por eso viven juntas. Las notas de evolución son INMUTABLES (D-EC-1): sin PATCH/
PUT/DELETE. Vistas delgadas con bitácora NOM-024.
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
from apps.core.permissions import (
    AddendumPermission,
    DiagnosisPermission,
    EvolutionPermission,
)
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.expediente.models import Diagnosis, EvolutionNote
from apps.expediente.selectors import (
    diagnosis_get,
    diagnosis_list,
    evolution_note_get,
    evolution_note_list,
)
from apps.expediente.serializers import (
    AddendumInputSerializer,
    AddendumOutputSerializer,
    DiagnosisInputSerializer,
    DiagnosisOutputSerializer,
    EvolutionNoteInputSerializer,
    EvolutionNoteOutputSerializer,
)
from apps.expediente.services import (
    addendum_create,
    diagnosis_create,
    diagnosis_resolve,
    evolution_note_create,
)
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get

logger = logging.getLogger("apps.expediente.views_evoluciones")


class _EvolutionPagination(PageNumberPagination):
    """Paginación para el listado de notas de evolución.

    page_size=20 con máximo 100. Las notas contienen texto extenso; páginas
    más pequeñas reducen la carga de serialización.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class EvolutionNoteListCreateApi(TenantAPIView):
    """GET  /api/v1/expediente/<patient_id>/evoluciones/ — lista notas de evolución.
    POST /api/v1/expediente/<patient_id>/evoluciones/ — crea nota (cita ATTENDED).

    INMUTABLE (D-EC-1): PATCH, PUT y DELETE no están ruteados → 405.

    GET: devuelve notas del paciente paginadas (-created_at), con addenda incluidos.
         Registra EVOLUTION_READ en AuditLog (NOM-024); si falla → logger.critical
         pero el acceso continúa (disponibilidad clínica > registro estricto).

    POST: valida input (D-EC-7), resuelve appointment, doctor y vital_signs,
          aplica la regla del médico (inyecta active_role en el service vía
          _active_role_cache), y delega la creación a evolution_note_create.
          Responde 201 con la nota serializada.

    ALTO-1 — Oracle de existencia cross-tenant:
        appointment_id, doctor_id y vital_signs_id se resuelven con selector +
        validación explícita de tenant. Cualquier fallo (inexistente, otro tenant)
        → 404 con el MISMO mensaje. No se revelan recursos ajenos.

    Regla del médico (D-EC-2): si el actor tiene rol 'doctor', solo puede crear
        evoluciones sobre citas cuyo appointment.doctor.membership.user == request.user.
        La validación se hace en el service (defensa en profundidad). La view inyecta
        el active_role en un atributo _active_role_cache del usuario para que el
        service lo lea sin necesidad de acceder al request.

    Permisos:
        GET  → CLINICAL_READ: owner, admin, doctor, nurse, readonly.
        POST → owner, admin, doctor (D-EC-2; nurse y readonly NO crean evoluciones).
    """

    permission_classes = [IsAuthenticated, EvolutionPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Lista las notas de evolución del paciente (-created_at), paginadas.

        Registra EVOLUTION_READ en la bitácora de auditoría (NOM-024).
        Fallo de bitácora → logger.critical, el acceso continúa.
        """
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        tenant = get_current_tenant()
        audit_result = audit_record(
            action=ActionType.EVOLUTION_READ,
            resource_type="EvolutionNote",
            actor=request.user,
            tenant=tenant,
            resource_id=None,
            resource_repr=str(patient.id),
            metadata={"patient_id": str(patient.id)},
        )
        if audit_result is None:
            logger.critical(
                "ACCESO A EXPEDIENTE SIN REGISTRO EN BITÁCORA — "
                "acción EVOLUTION_READ no pudo guardarse. "
                "tenant_id=%s patient_id=%s actor_id=%s. "
                "Revisar disponibilidad de BD de auditoría.",
                str(tenant.id) if tenant is not None else "None",
                str(patient.id),
                str(getattr(request.user, "pk", "anon")),
            )

        qs = evolution_note_list(patient=patient)
        paginator = _EvolutionPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(
                EvolutionNoteOutputSerializer(page, many=True).data
            )
        return Response(
            {"detail": "Paginación no disponible."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Crea una nota de evolución inmutable (D-EC-1, D-EC-2).

        Resuelve appointment, doctor y vital_signs con validación anti-IDOR.
        Inyecta active_role en el usuario para la regla del médico en el service.
        """
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = EvolutionNoteInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        _NOT_FOUND_APPT = Response(
            {"detail": "Cita no encontrada."},
            status=status.HTTP_404_NOT_FOUND,
        )
        _NOT_FOUND_DOCTOR = Response(
            {"detail": "Médico no encontrado."},
            status=status.HTTP_404_NOT_FOUND,
        )

        # Resolver appointment_id (ALTO-1: mismo mensaje para cualquier fallo).
        from apps.agenda.models import Appointment  # noqa: PLC0415
        try:
            appointment = Appointment.objects.select_related(
                "doctor", "doctor__membership"
            ).get(id=data["appointment_id"])
        except Appointment.DoesNotExist:
            return _NOT_FOUND_APPT
        if appointment.tenant_id != tenant.id or appointment.patient_id != patient.id:
            return _NOT_FOUND_APPT

        # Resolver doctor_id (ALTO-1).
        from apps.personal.models import Doctor  # noqa: PLC0415
        try:
            doctor = Doctor.objects.select_related("membership").get(
                id=data["doctor_id"]
            )
        except Doctor.DoesNotExist:
            return _NOT_FOUND_DOCTOR
        if doctor.tenant_id != tenant.id:
            return _NOT_FOUND_DOCTOR

        # Resolver vital_signs_id (opcional, ALTO-1).
        from apps.expediente.models import VitalSignsRecord  # noqa: PLC0415
        vital_signs = None
        vital_signs_id = data.pop("vital_signs_id", None)
        if vital_signs_id is not None:
            try:
                vital_signs = VitalSignsRecord.objects.get(id=vital_signs_id)
            except VitalSignsRecord.DoesNotExist:
                return Response(
                    {"detail": "Signos vitales no encontrados."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            if vital_signs.tenant_id != tenant.id or vital_signs.patient_id != patient.id:
                return Response(
                    {"detail": "Signos vitales no encontrados."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        # ALTO-1: pasar actor_role como argumento explícito al service.
        # La view no inyecta atributos en el usuario; el service recibe el rol
        # directamente y la regla del médico no puede omitirse silenciosamente
        # en llamadas desde Celery o management commands.
        actor_role: str = getattr(request, "active_role", "") or ""

        # Extraer appointment_id y doctor_id del dict (ya resueltos a objetos).
        data.pop("appointment_id", None)
        data.pop("doctor_id", None)

        try:
            note = evolution_note_create(
                tenant=tenant,
                user=request.user,
                patient=patient,
                appointment=appointment,
                doctor=doctor,
                vital_signs=vital_signs,
                actor_role=actor_role,
                **data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        note_with_addenda = evolution_note_get(evolution_id=note.id)
        return Response(
            EvolutionNoteOutputSerializer(note_with_addenda).data,
            status=status.HTTP_201_CREATED,
        )


class AddendumCreateApi(TenantAPIView):
    """POST /api/v1/expediente/evoluciones/<evolution_id>/addendum/

    Agrega un addendum a una nota de evolución existente (append-only, D-EC-1).

    ALTO-1: evolution_id se resuelve con validación de tenant; cualquier fallo
    → 404 con el mismo mensaje.

    Permisos:
        POST → owner, admin, doctor.
    """

    permission_classes = [IsAuthenticated, AddendumPermission]

    def post(self, request: Request, evolution_id: uuid.UUID) -> Response:
        """Agrega un addendum a la nota de evolución indicada."""
        try:
            evolution = evolution_note_get(evolution_id=evolution_id)
        except EvolutionNote.DoesNotExist:
            return Response(
                {"detail": "Nota de evolución no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = AddendumInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            addendum = addendum_create(
                tenant=tenant,
                user=request.user,
                evolution=evolution,
                body=s.validated_data["body"],
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            AddendumOutputSerializer(addendum).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Diagnósticos (A4)
# ---------------------------------------------------------------------------


class DiagnosisListCreateApi(TenantAPIView):
    """GET  /api/v1/expediente/<patient_id>/diagnosticos/ — lista diagnósticos.
    POST /api/v1/expediente/<patient_id>/diagnosticos/ — crea diagnóstico.

    GET: devuelve todos los diagnósticos del paciente (activos + resueltos).
         Query param `?only_active=true` para solo los activos.
         Paginado con la misma clase que evoluciones.

    POST: valida input (D-EC-7), resuelve evolution_id (opcional, anti-IDOR),
          y delega la creación a diagnosis_create.
          description, cie_code y kind son inmutables tras crear.
          Responde 201 con el diagnóstico serializado.

    ALTO-1: evolution_id (si se provee) se valida que pertenezca al tenant
        y al paciente; cualquier fallo → 404 con el mismo mensaje.

    Permisos:
        GET  → CLINICAL_READ.
        POST → owner, admin, doctor.
    """

    permission_classes = [IsAuthenticated, DiagnosisPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Lista diagnósticos del paciente.

        ALTO-2: registra DIAGNOSIS_READ en AuditLog (NOM-024). Si audit_record
        devuelve None → logger.critical pero el acceso continúa (mismo trade-off
        que MedicalHistoryApi.get — disponibilidad clínica > registro estricto).
        """
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ALTO-2: auditar lectura de diagnósticos (NOM-024).
        # resource_repr = UUID del paciente (sin PII clínica).
        tenant = get_current_tenant()
        audit_result = audit_record(
            action=ActionType.DIAGNOSIS_READ,
            resource_type="Diagnosis",
            actor=request.user,
            tenant=tenant,
            resource_id=None,
            resource_repr=str(patient.id),
            metadata={"patient_id": str(patient.id)},
        )
        if audit_result is None:
            logger.critical(
                "ACCESO A EXPEDIENTE SIN REGISTRO EN BITÁCORA — "
                "acción DIAGNOSIS_READ no pudo guardarse. "
                "tenant_id=%s patient_id=%s actor_id=%s. "
                "Revisar disponibilidad de BD de auditoría.",
                str(tenant.id) if tenant is not None else "None",
                str(patient.id),
                str(getattr(request.user, "pk", "anon")),
            )
            # El acceso continúa (disponibilidad clínica > registro estricto).

        only_active_raw: str = request.query_params.get("only_active", "false")
        only_active: bool = only_active_raw.lower() in ("true", "1", "yes")

        qs = diagnosis_list(patient=patient, only_active=only_active)
        paginator = _EvolutionPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(
                DiagnosisOutputSerializer(page, many=True).data
            )
        return Response(
            {"detail": "Paginación no disponible."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Crea un diagnóstico para el paciente."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = DiagnosisInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Resolver evolution_id (opcional, ALTO-1).
        evolution = None
        evolution_id = data.pop("evolution_id", None)
        if evolution_id is not None:
            try:
                evolution = evolution_note_get(evolution_id=evolution_id)
            except EvolutionNote.DoesNotExist:
                return Response(
                    {"detail": "Nota de evolución no encontrada."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            # Validar que pertenezca al paciente y tenant (defensa en profundidad).
            if evolution.patient_id != patient.id or evolution.tenant_id != tenant.id:
                return Response(
                    {"detail": "Nota de evolución no encontrada."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        try:
            diagnosis = diagnosis_create(
                tenant=tenant,
                user=request.user,
                patient=patient,
                evolution=evolution,
                **data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            DiagnosisOutputSerializer(diagnosis).data,
            status=status.HTTP_201_CREATED,
        )


class DiagnosisResolveApi(TenantAPIView):
    """POST /api/v1/expediente/diagnosticos/<id>/resolver/ — baja lógica del diagnóstico.

    Marca el diagnóstico como resuelto (status=resuelto). No borra físicamente (D-EC-5).
    La operación es idempotente (resolver un diagnóstico ya resuelto no da error).

    ALTO-1: diagnosis_id se resuelve por TenantManager → 404 si es de otro tenant.

    Permisos:
        POST → owner, admin, doctor.
    """

    permission_classes = [IsAuthenticated, DiagnosisPermission]

    def post(self, request: Request, diagnosis_id: uuid.UUID) -> Response:
        """Marca el diagnóstico como resuelto (baja lógica)."""
        try:
            diag = diagnosis_get(diagnosis_id=diagnosis_id)
        except Diagnosis.DoesNotExist:
            return Response(
                {"detail": "Diagnóstico no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            diag = diagnosis_resolve(diagnosis=diag, user=request.user)
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            DiagnosisOutputSerializer(diag).data,
            status=status.HTTP_200_OK,
        )
