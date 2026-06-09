"""
URLs de la app tenancy (gestión de miembros).

Se incluyen en config/urls.py bajo el prefijo api/v1/.
"""

from django.urls import path

from apps.tenancy.views import MemberAvatarApi, MemberDetailApi, MemberListCreateApi

urlpatterns = [
    path("miembros/", MemberListCreateApi.as_view(), name="member-list-create"),
    path("miembros/<uuid:membership_id>/", MemberDetailApi.as_view(), name="member-detail"),
    path("miembros/<uuid:membership_id>/avatar/", MemberAvatarApi.as_view(), name="member-avatar"),
]
