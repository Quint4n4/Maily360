"""
Migración A4-IMG: agrega la tabla expediente_evolution_images.

EvolutionImage almacena fotos clínicas adjuntas a una nota de evolución
(equivalente al botón "Nueva Imagen" del legacy).

Campos:
    id          — UUID primario (heredado de TenantAwareModel).
    created_at  — timestamp de creación automático.
    updated_at  — timestamp de última modificación automático.
    deleted_at  — NULL = activo; rellenado = baja lógica (D-EC-5).
    tenant      — FK a tenancy_tenant (PROTECT, indexado).
    created_by  — FK a authn_user (SET_NULL, nullable — quien subió la imagen).
    evolution   — FK a expediente_evolution_notes (CASCADE, indexado).
    image       — ImageField → ruta relativa bajo MEDIA_ROOT.
    caption     — CharField(255), blank, default="".

Índice:
    evol_image_evol_time_idx — (evolution_id, created_at) para listados en orden.

Reversible: la dirección inversa elimina la tabla completa.
"""

import apps.core.files
import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Crea la tabla expediente_evolution_images."""

    dependencies = [
        ("expediente", "0011_evolutionnote_evolution_note_appointment_uniq_and_more"),
        ("tenancy", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EvolutionImage",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "deleted_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        help_text="NULL = activo. Rellenar para borrado lógico.",
                        null=True,
                    ),
                ),
                (
                    "image",
                    models.ImageField(
                        help_text=(
                            "Imagen clínica (JPEG/PNG/WEBP, máx 10 MB). "
                            "El nombre se aleatoriza al guardar (anti path-traversal)."
                        ),
                        upload_to=apps.core.files.evolution_image_path,
                    ),
                ),
                (
                    "caption",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Descripción breve de la imagen (opcional).",
                        max_length=255,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        help_text=(
                            "Usuario que creó el registro. "
                            "Null en imports/seeds o si el usuario fue borrado."
                        ),
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "evolution",
                    models.ForeignKey(
                        db_index=True,
                        help_text="Nota de evolución a la que pertenece esta imagen.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="expediente.evolutionnote",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=True,
                        help_text="Clínica a la que pertenece este registro.",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="tenancy.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "expediente_evolution_images",
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="evolutionimage",
            index=models.Index(
                fields=["evolution", "created_at"],
                name="evol_image_evol_time_idx",
            ),
        ),
    ]
