"""
URLs de la app audit.

Se incluye bajo el prefijo /api/v1/audit/ en config/urls.py.

Endpoints:
    GET /api/v1/audit/logs/  — bitácora paginada (solo owner/admin).
"""

from django.urls import path

from apps.audit.views import AuditLogListApi

urlpatterns = [
    path("logs/", AuditLogListApi.as_view(), name="audit-log-list"),
]
