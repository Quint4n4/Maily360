"""
URLs de la app pacientes.

Se incluyen en config/urls.py bajo el prefijo api/v1/.
"""

from django.urls import path

from apps.pacientes.views import (
    PatientDetailApi,
    PatientListCreateApi,
    PatientQuickCreateApi,
)

urlpatterns = [
    path("pacientes/", PatientListCreateApi.as_view(), name="patient-list-create"),
    # Alta provisional ('rapido' no es UUID, no choca con el detalle <uuid>).
    path("pacientes/rapido/", PatientQuickCreateApi.as_view(), name="patient-quick-create"),
    path("pacientes/<uuid:patient_id>/", PatientDetailApi.as_view(), name="patient-detail"),
]
