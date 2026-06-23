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
    clinica/doctores/<doctor_id>/credenciales/           DoctorCredentialListCreateApi  [F2]
    clinica/credenciales/<credential_id>/                DoctorCredentialDetailApi      [F2]
"""

from django.urls import path

from apps.clinica.views import (
    ClinicSettingsApi,
    ClinicTemplateDetailApi,
    ClinicTemplateListCreateApi,
    DoctorCredentialDetailApi,
    DoctorCredentialListCreateApi,
    DoctorCredentialTenantListApi,
    DoctorCredentialValidationApi,
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
    # Credenciales del médico (COFEPRIS F2)
    path(
        "clinica/doctores/<uuid:doctor_id>/credenciales/",
        DoctorCredentialListCreateApi.as_view(),
        name="doctor-credential-list-create",
    ),
    # Bandeja de validación del administrador (todas las del tenant)
    path(
        "clinica/credenciales/",
        DoctorCredentialTenantListApi.as_view(),
        name="doctor-credential-tenant-list",
    ),
    path(
        "clinica/credenciales/<uuid:credential_id>/validar/",
        DoctorCredentialValidationApi.as_view(),
        name="doctor-credential-validate",
    ),
    path(
        "clinica/credenciales/<uuid:credential_id>/",
        DoctorCredentialDetailApi.as_view(),
        name="doctor-credential-detail",
    ),
]
