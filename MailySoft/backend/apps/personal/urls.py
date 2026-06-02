"""
URLs de la app personal.

Se incluyen en config/urls.py bajo el prefijo api/v1/.

Rutas:
    personal/doctores/                               DoctorListCreateApi
    personal/doctores/<doctor_id>/                   DoctorDetailApi
    personal/consultorios/                           ConsultorioListCreateApi
    personal/consultorios/<consultorio_id>/          ConsultorioDetailApi
    personal/doctores/<doctor_id>/horarios/          DoctorScheduleListCreateApi
    personal/horarios/<schedule_id>/                 DoctorScheduleDetailApi
"""

from django.urls import path

from apps.personal.views import (
    ConsultorioDetailApi,
    ConsultorioListCreateApi,
    DoctorDetailApi,
    DoctorListCreateApi,
    DoctorScheduleDetailApi,
    DoctorScheduleListCreateApi,
)

urlpatterns = [
    # Doctores
    path(
        "personal/doctores/",
        DoctorListCreateApi.as_view(),
        name="doctor-list-create",
    ),
    path(
        "personal/doctores/<uuid:doctor_id>/",
        DoctorDetailApi.as_view(),
        name="doctor-detail",
    ),
    # Consultorios
    path(
        "personal/consultorios/",
        ConsultorioListCreateApi.as_view(),
        name="consultorio-list-create",
    ),
    path(
        "personal/consultorios/<uuid:consultorio_id>/",
        ConsultorioDetailApi.as_view(),
        name="consultorio-detail",
    ),
    # Horarios — sub-recurso de doctor
    path(
        "personal/doctores/<uuid:doctor_id>/horarios/",
        DoctorScheduleListCreateApi.as_view(),
        name="doctor-schedule-list-create",
    ),
    # Horario individual (solo DELETE/soft por ahora)
    path(
        "personal/horarios/<uuid:schedule_id>/",
        DoctorScheduleDetailApi.as_view(),
        name="doctor-schedule-detail",
    ),
]
