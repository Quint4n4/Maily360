"""
Vistas de la app notas.

Vistas delgadas: parsean el request, llaman un selector o service, devuelven Response.
Cero lógica de negocio aquí.

Hereda de TenantAPIView para resolución de tenant + contexto RLS vía JWT.

Manejo de errores:
  Note.DoesNotExist      → 404 (no 403; no revelar existencia en otro tenant).
  ValidationError django → 400 con exc.messages.

Decisión de permisos:
  NotePermission abre GET y POST a ALL_ROLES porque:
    a) el selector note_list_visible ya filtra lo que cada usuario puede ver;
    b) la restricción owner-only para notas globales la hace el SERVICE (note_create),
       no el permiso HTTP. Esto permite que CUALQUIER usuario cree notas personales
       (POST al endpoint) mientras que solo el owner puede usar scope=role|all.
  PATCH/DELETE igual: cualquier rol autenticado llega al service, que verifica author/owner.

Multi-sede (cierre de hueco — 2026-07-16): las vistas resuelven el contexto
de sede del request (header X-Sucursal-Id) y lo pasan a selectors/services,
que son quienes deciden — la vista NUNCA calcula alcance de sede por su
cuenta:
  - Lecturas (GET lista/recordatorios) → `sucursal_scope_ids(request)`
    (alcance de VISIBILIDAD del viewer; None = alcance total).
  - Detalle para mutación (PATCH/DELETE/toggle-done) → mismo
    `sucursal_scope_ids(request)`, pasado a `note_get` — "si no la veo, no
    la puedo tocar por id" (404, no revela existencia en otra sede).
  - Creación (POST) → `resolve_active_sucursal(request)` para resolver la
    sede de un actor NO-owner (precedencia igual a agenda/personal); el
    `sucursal_id` explícito del body solo lo usa libremente el OWNER (ver
    `note_create` / `_resolve_broadcast_sucursal` en services.py).
"""

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.clinica.sucursal_scope import resolve_active_sucursal, sucursal_scope_ids
from apps.core.permissions import NotePermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.notas.models import Note, NoteScope
from apps.notas.selectors import note_get, note_list_visible, note_reminders_for_user
from apps.notas.serializers import NoteOutputSerializer
from apps.notas.services import note_create, note_delete, note_toggle_done, note_update
from apps.tenancy.models import Tenant


def _tenant_or_403(request: Request) -> "tuple[Tenant | None, Response | None]":
    """Obtiene el tenant del contexto o devuelve 403."""
    tenant = get_current_tenant()
    if tenant is None:
        return None, Response(
            {"detail": "No se encontró un tenant activo para este request."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return tenant, None


def _note_get_or_404(request: Request, note_id: uuid.UUID) -> "tuple[Note | None, Response | None]":
    """Recupera una nota por id, acotada al alcance de sede del actor, o 404.

    Usada por PATCH/DELETE/toggle-done (nunca por el listado, que usa
    `note_list_visible`). Pasa `sucursal_scope_ids(request)` a `note_get`
    para que un no-owner reciba 404 (no 400) al intentar tocar un aviso de
    otra sede o uno importante ajeno — "si no la veo, no la puedo tocar".
    """
    try:
        note = note_get(
            note_id=note_id,
            user=request.user,
            sucursal_ids=sucursal_scope_ids(request),
        )
        return note, None
    except Note.DoesNotExist:
        return None, Response(
            {"detail": "Nota no encontrada."},
            status=status.HTTP_404_NOT_FOUND,
        )


class NoteListCreateApi(TenantAPIView):
    """GET  /api/v1/notas/  — mis notas visibles con filtros opcionales.
    POST /api/v1/notas/  — crear una nota o tarea.
    """

    permission_classes = [IsAuthenticated, NotePermission]

    class InputSerializer(serializers.Serializer):
        """Campos para crear una nota (POST).

        sucursal_id/is_important solo tienen efecto real para avisos
        (scope=role|all) creados por el OWNER — para cualquier otro actor
        el service los re-resuelve/rechaza sin importar lo que se mande
        aquí (ver note_create / _resolve_broadcast_sucursal). Se exponen
        igual para todos los actores para no bifurcar el contrato del
        endpoint por rol.
        """

        title = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
        body = serializers.CharField(
            max_length=10_000, required=False, allow_blank=True, default=""
        )
        scope = serializers.ChoiceField(
            choices=NoteScope.choices,
            required=False,
            default=NoteScope.PERSONAL,
        )
        target_role = serializers.CharField(
            max_length=20, required=False, allow_blank=True, default=""
        )
        is_task = serializers.BooleanField(required=False, default=False)
        remind_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
        pinned = serializers.BooleanField(required=False, default=False)
        sucursal_id = serializers.UUIDField(required=False, allow_null=True, default=None)
        is_important = serializers.BooleanField(required=False, default=False)

    def get(self, request: Request) -> Response:
        """Lista paginada de notas visibles para el usuario autenticado.

        Query params:
            is_task: bool — filtrar solo tareas (true) o solo notas (false).
            done:    bool — filtrar por estado done/pendiente.
            scope:   str  — filtrar por scope (aún no en selector; se aplica en query param).

        Multi-sede (cierre de hueco — 2026-07-16): SIEMPRE se acota al
        alcance de sedes del usuario (`sucursal_scope_ids`), con o sin
        header X-Sucursal-Id. Un admin de una sola sede ya no puede ver
        avisos de otra sede con solo omitir el header; el owner (alcance
        total) sigue viendo todo, incluidos los avisos de "todas las
        sedes".
        """
        tenant, error = _tenant_or_403(request)
        if error is not None:
            return error

        class _FilterSerializer(serializers.Serializer):
            is_task = serializers.BooleanField(required=False)
            done = serializers.BooleanField(required=False)

        filter_s = _FilterSerializer(data=request.query_params)
        filter_s.is_valid(raise_exception=True)

        qs = note_list_visible(
            user=request.user,
            tenant=tenant,
            sucursal_ids=sucursal_scope_ids(request),
            **filter_s.validated_data,
        )

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(NoteOutputSerializer(page, many=True).data)

        return Response(
            {"detail": "Paginación no disponible. Configura PAGE_SIZE en settings."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request) -> Response:
        """Crea una nueva nota o tarea.

        Multi-sede: resuelve la sede ACTIVA del request (header
        X-Sucursal-Id, si viene) y la pasa al service como
        `active_sucursal_id` — el service la usa únicamente para resolver
        la sede de un actor NO-owner (ver note_create). El `sucursal_id`
        explícito del body llega tal cual; el owner lo usa libremente
        (None = todas las sedes), cualquier otro actor lo ve re-resuelto/
        validado contra su propia sede.
        """
        tenant, error = _tenant_or_403(request)
        if error is not None:
            return error

        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        active_sucursal = resolve_active_sucursal(request)

        try:
            note = note_create(
                tenant=tenant,
                user=request.user,
                active_sucursal_id=(active_sucursal.id if active_sucursal is not None else None),
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            NoteOutputSerializer(note).data,
            status=status.HTTP_201_CREATED,
        )


class NoteDetailApi(TenantAPIView):
    """PATCH  /api/v1/notas/<note_id>/  — edición parcial de una nota.
    DELETE /api/v1/notas/<note_id>/  — borrado (soft-delete).
    """

    permission_classes = [IsAuthenticated, NotePermission]

    class InputSerializer(serializers.Serializer):
        """Campos editables de una nota (PATCH).

        EXCLUIDO: done — solo via NoteToggleDoneApi.
                  author, tenant, id, timestamps — inmutables.
        """

        title = serializers.CharField(max_length=120, required=False, allow_blank=True)
        body = serializers.CharField(required=False, allow_blank=True)
        scope = serializers.ChoiceField(choices=NoteScope.choices, required=False)
        target_role = serializers.CharField(max_length=20, required=False, allow_blank=True)
        is_task = serializers.BooleanField(required=False)
        remind_at = serializers.DateTimeField(required=False, allow_null=True)
        pinned = serializers.BooleanField(required=False)

    def patch(self, request: Request, note_id: uuid.UUID) -> Response:
        """Actualización parcial de campos editables.

        No acepta 'done' (use /notas/<id>/done/).

        Multi-sede: usa `_note_get_or_404` (mismo criterio que
        `NoteToggleDoneApi` y el listado) — un aviso fuera del alcance de
        sede del actor, o uno importante ajeno, devuelve 404.
        """
        tenant, error = _tenant_or_403(request)
        if error is not None:
            return error

        note, error = _note_get_or_404(request, note_id)
        if error is not None:
            return error

        s = self.InputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            note = note_update(
                note=note,
                user=request.user,
                tenant=tenant,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(NoteOutputSerializer(note).data)

    def delete(self, request: Request, note_id: uuid.UUID) -> Response:
        """Borra una nota (soft-delete).

        Multi-sede: usa `_note_get_or_404` — mismo criterio de alcance que patch/toggle-done.
        """
        tenant, error = _tenant_or_403(request)
        if error is not None:
            return error

        note, error = _note_get_or_404(request, note_id)
        if error is not None:
            return error

        try:
            note_delete(note=note, user=request.user, tenant=tenant)
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


class NoteToggleDoneApi(TenantAPIView):
    """POST /api/v1/notas/<note_id>/done/  — alterna done de una tarea."""

    permission_classes = [IsAuthenticated, NotePermission]

    def post(self, request: Request, note_id: uuid.UUID) -> Response:
        """Alterna el estado done/pendiente de una tarea (is_task=True).

        Multi-sede: usa `_note_get_or_404` — mismo criterio de alcance que patch/delete.
        """
        tenant, error = _tenant_or_403(request)
        if error is not None:
            return error

        note, error = _note_get_or_404(request, note_id)
        if error is not None:
            return error

        try:
            note = note_toggle_done(note=note, user=request.user, tenant=tenant)
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(NoteOutputSerializer(note).data)


class NoteRemindersApi(TenantAPIView):
    """GET /api/v1/notas/recordatorios/?date_from=&date_to=

    Devuelve las notas visibles del usuario con remind_at en el rango dado.
    Usado por el widget "Mis recordatorios" de la barra lateral de Agenda.
    """

    permission_classes = [IsAuthenticated, NotePermission]

    def get(self, request: Request) -> Response:
        """Lista notas con recordatorio en el rango [date_from, date_to).

        Query params:
            date_from: ISO datetime UTC (requerido).
            date_to:   ISO datetime UTC (requerido).

        Multi-sede: acota por `sucursal_scope_ids(request)`, mismo criterio
        que el listado principal (cierre de hueco — 2026-07-16).
        """
        tenant, error = _tenant_or_403(request)
        if error is not None:
            return error

        class _FilterSerializer(serializers.Serializer):
            date_from = serializers.DateTimeField()
            date_to = serializers.DateTimeField()

        filter_s = _FilterSerializer(data=request.query_params)
        filter_s.is_valid(raise_exception=True)

        qs = note_reminders_for_user(
            user=request.user,
            tenant=tenant,
            date_from=filter_s.validated_data["date_from"],
            date_to=filter_s.validated_data["date_to"],
            sucursal_ids=sucursal_scope_ids(request),
        )

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(NoteOutputSerializer(page, many=True).data)

        return Response(
            {"detail": "Paginación no disponible. Configura PAGE_SIZE en settings."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
