"""
Endpoint público de verificación de autenticidad de receta médica (F5).

Este módulo es deliberadamente independiente de `views.py` (que usa TenantAPIView
y requiere autenticación). La vista pública NO usa TenantAPIView, NO requiere JWT
y NO filtra por tenant del contexto — el acceso se autoriza ÚNICAMENTE por la firma
HMAC del QR.

Política de privacidad (información de salud — NOM-024, LGPDPPSO):
    El endpoint responde ÚNICAMENTE con datos no sensibles:
        folio, estado (vigente|anulada), fecha_emision,
        medico {nombre, cedula_profesional}, clinica {nombre}.
    NUNCA expone: nombre del paciente, medicamentos, diagnóstico, signos vitales
    ni ningún otro dato clínico o PII del paciente.

Anti-enumeración:
    - Firma inválida → 404 (mismo código que receta inexistente).
    - Receta inexistente → 404.
    - No se distingue entre "firma mala" y "receta no encontrada" en la respuesta.
    - Throttle dedicado: 30 req/min por IP (scope "prescription_verify").

Multi-tenant:
    La receta se busca con `Prescription.all_objects` (sin filtro de tenant),
    porque el endpoint es transversal a tenants — cualquier farmacia puede
    escanear el QR de cualquier clínica. El acceso se garantiza SOLO por la firma.
    No se expone información del tenant (solo nombre comercial de la clínica).
"""

import logging
import uuid

from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.recetas.serializers import PrescriptionVerifyOutputSerializer
from apps.recetas.verification import verify_token

logger = logging.getLogger("apps.recetas.views_public")


class PrescriptionVerifyThrottle(AnonRateThrottle):
    """Throttle dedicado al endpoint público de verificación de receta.

    Scope "prescription_verify" → 30 req/min por IP (configurado en settings).
    Protege contra scraping de folios y enumeración de recetas.
    """

    scope = "prescription_verify"


class PrescriptionVerifyApi(APIView):
    """GET /api/v1/verificar-receta/<prescription_id>/?sig=<token>

    Verifica la autenticidad de una receta médica. Endpoint PÚBLICO —
    diseñado para ser escaneado por farmacias, pacientes o autoridades.

    Parámetros:
        prescription_id (path): UUID de la receta.
        sig (query):            Token HMAC-SHA256 generado al emitir el PDF.

    Respuesta 200 — datos no sensibles de la receta:
        folio          (int)  — número de folio consecutivo por clínica.
        estado         (str)  — "vigente" | "anulada".
        fecha_emision  (date) — fecha de emisión (YYYY-MM-DD).
        medico         (obj)  — {nombre: str, cedula_profesional: str}.
        clinica        (str)  — nombre comercial o razón social de la clínica.

    Respuesta 404 — firma inválida O receta inexistente (indistinguible).

    Seguridad:
        - AllowAny: no requiere autenticación JWT.
        - Throttle: PrescriptionVerifyThrottle (30 req/min por IP).
        - hmac.compare_digest en verify_token: resistente a timing attacks.
        - 404 uniforme: no permite distinguir "firma mala" de "receta no encontrada".
        - Sin PII: la respuesta nunca incluye datos del paciente ni medicamentos.
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # sin JWT; reduce overhead y evita errores 401 por token ausente
    throttle_classes = [PrescriptionVerifyThrottle]

    def get(self, request: Request, prescription_id: uuid.UUID) -> Response:
        """Verifica autenticidad de la receta y devuelve datos mínimos no sensibles."""
        from apps.recetas.models import Prescription, PrescriptionStatus

        sig: str = request.query_params.get("sig", "")

        # --- 1. Validar la firma ANTES de tocar la BD ---
        # Si la firma es inválida no hacemos ninguna query (no revelamos existencia).
        if not verify_token(prescription_id=prescription_id, sig=sig):
            return Response(status=404)

        # --- 2. Buscar la receta SIN filtro de tenant (endpoint cross-tenant) ---
        # Usamos all_objects (sin TenantManager) porque la autorización ya ocurrió
        # en el paso anterior mediante la firma HMAC. Si la receta no existe,
        # devolvemos 404 igual que firma inválida (no distinguir).
        # F6: prefetch items para is_controlled (evita N+1) y carga valid_until.
        try:
            prescription = (
                Prescription.all_objects.select_related(
                    "doctor",
                    "doctor__membership",
                    "tenant",
                )
                .prefetch_related("items")
                .get(id=prescription_id)
            )
        except Prescription.DoesNotExist:
            return Response(status=404)

        # --- 3. Construir respuesta con SOLO datos no sensibles ---
        estado = (
            "anulada"
            if prescription.status == PrescriptionStatus.CANCELLED
            else "vigente"
        )

        # Nombre del médico — sin PII del paciente
        doctor = prescription.doctor
        doctor_name: str = ""
        try:
            doctor_name = doctor.full_name
        except Exception:  # noqa: BLE001
            doctor_name = str(doctor.id)

        cedula: str = getattr(doctor, "cedula_profesional", "") or ""

        # Nombre de la clínica: commercial_name > tenant.name
        clinic_name: str = ""
        try:
            from apps.clinica.models import ClinicSettings

            settings_obj = ClinicSettings.objects.filter(
                tenant=prescription.tenant,
                deleted_at__isnull=True,
            ).only("commercial_name").first()
            if settings_obj is not None:
                clinic_name = settings_obj.commercial_name or ""
        except Exception:  # noqa: BLE001
            pass
        if not clinic_name:
            clinic_name = getattr(prescription.tenant, "name", "") or ""

        # Bitácora opcional (sin PII): solo folio y resultado.
        # No se registra IP ni el token `sig` (podría usarse para revalidar).
        try:
            from apps.audit.models import ActionType
            from apps.audit.services import audit_record

            audit_record(
                action=ActionType.PRESCRIPTION_VERIFY,
                resource_type="Prescription",
                actor=None,
                tenant=prescription.tenant,
                resource_id=prescription.id,
                resource_repr=f"folio={prescription.folio}",
                metadata={
                    "folio": prescription.folio,
                    "estado": estado,
                },
            )
        except Exception:  # noqa: BLE001
            # La auditoría no debe bloquear la respuesta al verificador.
            logger.warning(
                "PrescriptionVerifyApi: no se pudo registrar PRESCRIPTION_VERIFY "
                "en bitácora — prescription_id=%s folio=%s.",
                str(prescription_id),
                prescription.folio,
            )

        # F6: datos de controlado (sin PII — solo bool + vigencia).
        # Usamos valid_until como indicador de si es controlada: el servicio lo
        # calcula correctamente al crear y es inmutable (DR-1). Esto evita tener
        # que re-consultar items en un contexto sin tenant (endpoint cross-tenant).
        # El campo controlled_folio NO se expone en verify (privacidad operativa).
        valid_until = prescription.valid_until
        is_controlled: bool = valid_until is not None or bool(
            getattr(prescription, "controlled_folio", "")
        )

        payload = {
            "folio": prescription.folio,
            "estado": estado,
            "fecha_emision": prescription.issued_at.date(),
            "medico": {
                "nombre": doctor_name,
                "cedula_profesional": cedula,
            },
            "clinica": clinic_name,
            # F6: sin PII — solo indica si es controlada y su vigencia
            "controlado": is_controlled,
            "vigencia": valid_until,
        }

        out = PrescriptionVerifyOutputSerializer(payload)
        return Response(out.data, status=200)
