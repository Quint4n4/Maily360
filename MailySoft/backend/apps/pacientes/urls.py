"""
URLs de la app pacientes.

Se incluyen en config/urls.py bajo el prefijo api/v1/.
"""

from django.urls import path

from apps.pacientes.views import PatientDetailApi, PatientListCreateApi

urlpatterns = [
    path("pacientes/", PatientListCreateApi.as_view(), name="patient-list-create"),
    path("pacientes/<uuid:patient_id>/", PatientDetailApi.as_view(), name="patient-detail"),
]
