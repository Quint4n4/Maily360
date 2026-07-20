"""
Data migration: backfill de `Note.sucursal` / `Note.is_important` (cierre de
hueco de sedes en la app notas — 2026-07-16).

A diferencia de otros backfills de sucursal del proyecto (personal/0009,
agenda/0015, finanzas/0008), que asignan la "Sucursal Principal" del tenant a
los registros legado, aquí el backfill es un NO-OP INTENCIONAL: las
notas/avisos existentes se quedan con `sucursal=NULL`, que para ESTE modelo
significa "toda la clínica / todas las sedes" (NO "sin sede asignada
todavía", como en agenda/personal/finanzas).

Es exactamente el comportamiento anterior a este cambio (todo aviso legado
era visible en toda la clínica, sin noción de sede) — reasignarlos a la
Sucursal Principal los OCULTARÍA de las demás sedes, cambiando su
significado retroactivamente. `is_important` ya nace en False por default de
campo; tampoco requiere backfill.

Se deja como migración de datos explícita (en vez de omitirla) para seguir
el patrón del proyecto: todo AddField de `sucursal` va acompañado de una
migración de backfill documentada, aunque en este caso no toque ninguna
fila.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("notas", "0003_note_sucursal_is_important"),
    ]

    operations = [
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
    ]
