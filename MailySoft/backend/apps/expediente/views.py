"""
Vistas de la app expediente (sub-fases A1, A2, A3 y A4).

Vistas delgadas: parsean el request, llaman un selector o service, devuelven Response.
Cero lógica de negocio aquí. Heredan de TenantAPIView.

Endpoints A1:
    GET    /api/v1/expediente/<patient_id>/alergias/   — lista alergias del paciente.
    POST   /api/v1/expediente/<patient_id>/alergias/   — registra una alergia nueva.
    DELETE /api/v1/expediente/alergias/<id>/           — baja lógica (resolve).

Endpoints A2:
    GET /api/v1/expediente/<patient_id>/historia/  — devuelve la HC (o estructura vacía).
    PUT /api/v1/expediente/<patient_id>/historia/  — upsert de la HC.

Endpoints A3:
    GET  /api/v1/expediente/<patient_id>/signos/         — lista tomas (-measured_at).
    POST /api/v1/expediente/<patient_id>/signos/         — registra una toma nueva.
    GET  /api/v1/expediente/<patient_id>/signos/series/  — datos de series para gráficas.

Endpoints A4:
    GET  /api/v1/expediente/<patient_id>/evoluciones/          — lista notas de evolución.
    POST /api/v1/expediente/<patient_id>/evoluciones/          — crea nota (cita ATTENDED).
    POST /api/v1/expediente/evoluciones/<id>/addendum/         — agrega addendum.
    GET  /api/v1/expediente/<patient_id>/diagnosticos/         — lista diagnósticos.
    POST /api/v1/expediente/<patient_id>/diagnosticos/         — crea diagnóstico.
    POST /api/v1/expediente/diagnosticos/<id>/resolver/        — marca como resuelto.

IMPORTANTE — Inmutabilidad (D-EC-1):
    EvolutionNote es INMUTABLE: no existen PATCH, PUT ni DELETE.
    Los métodos no ruteados devuelven 405.

Anti-IDOR (ALTO-1):
    Todos los IDs en la URL se resuelven por TenantManager o con validación
    explícita de tenant. Recurso de otro tenant → 404 con mismo mensaje.
    NUNCA 403 para recursos ajenos (evita oracle de existencia cross-tenant).

Manejo de bitácora (ALTO-2 ruidoso):
    audit_record devuelve None en fallo de BD de auditoría. El GET de evoluciones
    registra EVOLUTION_READ y si falla → logger.critical pero el acceso continúa
    (disponibilidad clínica > registro estricto — mismo trade-off que HC y signos).
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
    AllergyPermission,
    DiagnosisPermission,
    EvolutionPermission,
    MedicalHistoryPermission,
    MedicalHistoryQuestionPermission,
    NursingInstructionPermission,
    VitalSignsPermission,
)
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.expediente.models import Allergy, Diagnosis, EvolutionImage, EvolutionNote
from apps.expediente.selectors import (
    allergy_get,
    allergy_list,
    diagnosis_get,
    diagnosis_list,
    evolution_image_get,
    evolution_images_list,
    evolution_note_get,
    evolution_note_list,
    evolution_nursing_instructions_for_patient,
    medical_history_get_for_patient,
    medical_history_question_get,
    medical_history_questions_list,
    vital_signs_list,
    vital_signs_series,
)
from apps.expediente.serializers import (
    AddendumInputSerializer,
    AddendumOutputSerializer,
    AllergyInputSerializer,
    AllergyOutputSerializer,
    DiagnosisInputSerializer,
    DiagnosisOutputSerializer,
    EvolutionImageInputSerializer,
    EvolutionImageOutputSerializer,
    EvolutionNoteInputSerializer,
    EvolutionNoteOutputSerializer,
    MedicalHistoryInputSerializer,
    MedicalHistoryOutputSerializer,
    MedicalHistoryQuestionInputSerializer,
    MedicalHistoryQuestionOutputSerializer,
    NursingInstructionOutputSerializer,
    VitalSignsInputSerializer,
    VitalSignsOutputSerializer,
)
from apps.expediente.services import (
    addendum_create,
    allergy_create,
    allergy_resolve,
    diagnosis_create,
    diagnosis_resolve,
    evolution_image_add,
    evolution_image_remove,
    evolution_note_create,
    medical_history_question_create,
    medical_history_question_deactivate,
    medical_history_question_update,
    medical_history_upsert,
    vital_signs_create,
)
from apps.expediente.views_libro import (  # noqa: F401
    PatientBookApi,
    PatientBookPdfApi,
)
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get

logger = logging.getLogger("apps.expediente.views")


class AllergyListCreateApi(TenantAPIView):
    """GET /api/v1/expediente/<patient_id>/alergias/  — lista alergias del paciente.
    POST /api/v1/expediente/<patient_id>/alergias/  — registra una alergia nueva.

    Query params para GET:
        include_resolved: bool — si True, incluye también las resueltas (is_active=False).
                                  Default: False (solo vigentes).
    """

    permission_classes = [IsAuthenticated, AllergyPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Lista las alergias del paciente (vigentes por defecto)."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Parsear include_resolved del query param (D-EC-5: podemos ver las resueltas).
        include_resolved_raw: str = request.query_params.get("include_resolved", "false")
        include_resolved: bool = include_resolved_raw.lower() in ("true", "1", "yes")
        only_active: bool = not include_resolved

        qs = allergy_list(patient=patient, only_active=only_active)
        return Response(AllergyOutputSerializer(qs, many=True).data)

    def post(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Registra una alergia nueva para el paciente."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = AllergyInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            allergy = allergy_create(
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
            AllergyOutputSerializer(allergy).data,
            status=status.HTTP_201_CREATED,
        )


class AllergyResolveApi(TenantAPIView):
    """DELETE /api/v1/expediente/alergias/<id>/  — baja lógica de la alergia.

    No borra el registro (D-EC-5). Pone is_active=False (resuelta clínicamente).
    Responde 204 No Content en éxito.
    """

    permission_classes = [IsAuthenticated, AllergyPermission]

    def delete(self, request: Request, allergy_id: uuid.UUID) -> Response:
        """Marca la alergia como resuelta (baja lógica, sin borrado físico)."""
        try:
            allergy = allergy_get(allergy_id=allergy_id)
        except Allergy.DoesNotExist:
            return Response(
                {"detail": "Alergia no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        allergy_resolve(allergy=allergy, user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Historia Clínica (A2)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Signos Vitales (A3) — Append-only
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Notas de Evolución (A4) — Inmutables (D-EC-1)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Indicaciones de enfermería (A4 — sub-vista especializada)
# ---------------------------------------------------------------------------


class NursingInstructionListApi(TenantAPIView):
    """GET /api/v1/expediente/<patient_id>/indicaciones-enfermeria/

    Devuelve las notas de evolución del paciente que tienen indicaciones de
    enfermería (campo `indicaciones_enfermeria` no vacío), ordenadas por
    -created_at (más reciente primero), limitadas a los últimos 20 registros.

    Caso de uso principal: la enfermera consulta las indicaciones del médico
    para un paciente antes de o durante la atención.

    Anti-IDOR (ALTO-1):
        patient_id se resuelve por TenantManager. Un patient_id de otro tenant
        → 404 con el mismo mensaje. NUNCA 403 (no revelar existencia cross-tenant).

    Paginación:
        El selector ya aplica limit=20. La respuesta NO usa envoltura de
        paginación (la cantidad máxima es fija y conocida); devuelve lista directa.
        Si en el futuro se necesitara paginación completa, cambiar a PageNumberPagination.

    Permisos:
        GET → CLINICAL_READ: owner, admin, doctor, nurse, readonly.
        Recepción y finanzas NO tienen acceso (contenido clínico sensible).
    """

    permission_classes = [IsAuthenticated, NursingInstructionPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Lista las indicaciones de enfermería del paciente (máx. últimas 20).

        Responde 404 si el paciente no existe o es de otro tenant (anti-IDOR).
        Responde 200 con lista (puede ser [] si no hay indicaciones aún).
        """
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        qs = evolution_nursing_instructions_for_patient(patient=patient)
        return Response(
            NursingInstructionOutputSerializer(qs, many=True).data,
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Imágenes de Evolución
# ---------------------------------------------------------------------------


class EvolutionImageListCreateApi(TenantAPIView):
    """GET  /api/v1/expediente/evoluciones/<evolution_id>/imagenes/ — lista imágenes.
    POST /api/v1/expediente/evoluciones/<evolution_id>/imagenes/ — sube imagen.

    GET: devuelve las imágenes activas de la nota (excluye soft-deleted).
         Permiso: CLINICAL_READ (EvolutionPermission.GET).

    POST: valida el archivo multipart con Pillow (barrera real en el service),
          crea el registro. Responde 201 con la imagen serializada.
          Permiso: escritura clínica (EvolutionPermission.POST = owner/admin/doctor).

    Anti-IDOR: evolution_id se resuelve con el TenantManager → 404 si es de otro
    tenant. Mismo mensaje para existente-pero-otro-tenant que para inexistente.

    Multipart: el cliente debe enviar Content-Type: multipart/form-data con
    el campo 'image' como archivo binario.
    """

    permission_classes = [IsAuthenticated, EvolutionPermission]

    def get(self, request: Request, evolution_id: uuid.UUID) -> Response:
        """Lista las imágenes activas de la nota de evolución."""
        try:
            evolution = evolution_note_get(evolution_id=evolution_id)
        except EvolutionNote.DoesNotExist:
            return Response(
                {"detail": "Nota de evolución no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        qs = evolution_images_list(evolution=evolution)
        return Response(
            EvolutionImageOutputSerializer(
                qs, many=True, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request: Request, evolution_id: uuid.UUID) -> Response:
        """Sube una imagen a la nota de evolución (multipart/form-data).

        El campo 'image' debe ser un archivo binario JPEG, PNG o WEBP.
        La validación de contenido real la hace validate_evolution_image() en el
        service (Pillow). El serializer aquí solo verifica que el campo exista.
        """
        try:
            evolution = evolution_note_get(evolution_id=evolution_id)
        except EvolutionNote.DoesNotExist:
            return Response(
                {"detail": "Nota de evolución no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = EvolutionImageInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            evo_image = evolution_image_add(
                tenant=tenant,
                user=request.user,
                evolution=evolution,
                image=s.validated_data["image"],
                caption=s.validated_data.get("caption", ""),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            EvolutionImageOutputSerializer(evo_image, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class EvolutionImageDeleteApi(TenantAPIView):
    """DELETE /api/v1/expediente/imagenes/<image_id>/ — baja lógica de imagen.

    No borra el archivo físico ni el registro (D-EC-5). Pone deleted_at = ahora.
    Responde 204 No Content en éxito.

    Anti-IDOR: image_id se resuelve con el TenantManager → 404 si es de otro
    tenant. NUNCA 403 para recursos ajenos (no revelar existencia cross-tenant).

    Permiso: escritura clínica (EvolutionPermission.DELETE = owner/admin/doctor).
    """

    permission_classes = [IsAuthenticated, EvolutionPermission]

    def delete(self, request: Request, image_id: uuid.UUID) -> Response:
        """Baja lógica de la imagen (sin borrado físico, D-EC-5)."""
        try:
            evo_image = evolution_image_get(image_id=image_id)
        except EvolutionImage.DoesNotExist:
            return Response(
                {"detail": "Imagen no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            evolution_image_remove(image=evo_image, user=request.user)
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# MedicalHistoryQuestion — Fase 2 (preguntas extra configurables)
# ---------------------------------------------------------------------------


class MedicalHistoryQuestionListCreateApi(TenantAPIView):
    """GET  /api/v1/expediente/preguntas-hc/ — lista preguntas extra del tenant.
    POST /api/v1/expediente/preguntas-hc/ — crea una pregunta nueva.

    Anti-IDOR: el TenantManager garantiza aislamiento por tenant automáticamente.

    Query params para GET:
        include_inactive: bool — si True, incluye preguntas inactivas.
                                  Default: False (solo activas).
    """

    permission_classes = [IsAuthenticated, MedicalHistoryQuestionPermission]

    def get(self, request: Request) -> Response:
        """Lista las preguntas extra de la clínica (activas por defecto)."""
        only_active = request.query_params.get("include_inactive", "").lower() not in (
            "true", "1", "yes"
        )
        qs = medical_history_questions_list(only_active=only_active)
        return Response(MedicalHistoryQuestionOutputSerializer(qs, many=True).data)

    def post(self, request: Request) -> Response:
        """Crea una pregunta extra para el formulario de HC de la clínica."""
        s = MedicalHistoryQuestionInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            question = medical_history_question_create(
                tenant=tenant,
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            MedicalHistoryQuestionOutputSerializer(question).data,
            status=status.HTTP_201_CREATED,
        )


class MedicalHistoryQuestionDetailApi(TenantAPIView):
    """PATCH  /api/v1/expediente/preguntas-hc/<question_id>/ — edita pregunta.
    DELETE /api/v1/expediente/preguntas-hc/<question_id>/ — desactiva pregunta.

    Anti-IDOR: toda lectura por id pasa por el selector (TenantManager filtra).
    Recurso de otro tenant → DoesNotExist → 404 (no 403).
    """

    permission_classes = [IsAuthenticated, MedicalHistoryQuestionPermission]

    def patch(self, request: Request, question_id: uuid.UUID) -> Response:
        """Edita campos mutables de la pregunta (label, field_type, options, section, order, is_required)."""
        from apps.expediente.models import MedicalHistoryQuestion  # noqa: PLC0415

        try:
            question = medical_history_question_get(question_id=question_id)
        except MedicalHistoryQuestion.DoesNotExist:
            return Response(
                {"detail": "Pregunta no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = MedicalHistoryQuestionInputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        try:
            question = medical_history_question_update(
                question=question,
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(MedicalHistoryQuestionOutputSerializer(question).data)

    def delete(self, request: Request, question_id: uuid.UUID) -> Response:
        """Desactiva la pregunta (baja lógica — D-EC-5, idempotente)."""
        from apps.expediente.models import MedicalHistoryQuestion  # noqa: PLC0415

        try:
            question = medical_history_question_get(question_id=question_id)
        except MedicalHistoryQuestion.DoesNotExist:
            return Response(
                {"detail": "Pregunta no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            medical_history_question_deactivate(
                question=question,
                user=request.user,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)

