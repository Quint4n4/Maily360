"""
URLs de la app clinica — Mi Consultorio.

Se incluyen en config/urls.py bajo el prefijo api/v1/.

Rutas:
    clinica/configuracion/                               ClinicSettingsApi
    clinica/plantillas/                                  ClinicTemplateListCreateApi
    clinica/plantillas/<template_id>/                    ClinicTemplateDetailApi
    clinica/categorias/                                  PatientCategoryListCreateApi
    clinica/categorias/<category_id>/                    PatientCategoryDetailApi
    clinica/doctores/<doctor_id>/perfil/                 DoctorProfileApi
    clinica/doctores/<doctor_id>/universidades/          DoctorUniversityListCreateApi
    clinica/universidades/<university_id>/               DoctorUniversityDetailApi
"""

from django.urls import path

from apps.clinica.views import (
    ClinicSettingsApi,
    ClinicTemplateDetailApi,
    ClinicTemplateListCreateApi,
    DoctorProfileApi,
    DoctorUniversityDetailApi,
    DoctorUniversityListCreateApi,
    PatientCategoryDetailApi,
    PatientCategoryListCreateApi,
)

urlpatterns = [
    # Configuración de la clínica
    path(
        "clinica/configuracion/",
        ClinicSettingsApi.as_view(),
        name="clinic-settings",
    ),
    # Plantillas clínicas
    path(
        "clinica/plantillas/",
        ClinicTemplateListCreateApi.as_view(),
        name="clinic-template-list-create",
    ),
    path(
        "clinica/plantillas/<uuid:template_id>/",
        ClinicTemplateDetailApi.as_view(),
        name="clinic-template-detail",
    ),
    # Categorías de paciente
    path(
        "clinica/categorias/",
        PatientCategoryListCreateApi.as_view(),
        name="clinic-category-list-create",
    ),
    path(
        "clinica/categorias/<uuid:category_id>/",
        PatientCategoryDetailApi.as_view(),
        name="clinic-category-detail",
    ),
    # Perfil ampliado del médico (sello, foto, cédulas adicionales)
    path(
        "clinica/doctores/<uuid:doctor_id>/perfil/",
        DoctorProfileApi.as_view(),
        name="doctor-profile-images",
    ),
    # Universidades del médico
    path(
        "clinica/doctores/<uuid:doctor_id>/universidades/",
        DoctorUniversityListCreateApi.as_view(),
        name="doctor-university-list-create",
    ),
    path(
        "clinica/universidades/<uuid:university_id>/",
        DoctorUniversityDetailApi.as_view(),
        name="doctor-university-detail",
    ),
]
