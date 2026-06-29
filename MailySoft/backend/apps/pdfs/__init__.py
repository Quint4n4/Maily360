"""Infraestructura genérica de generación de PDFs en segundo plano (Celery).

Un solo `PdfJob` + una tarea + endpoints de estado/descarga sirven a TODOS los
PDFs de la app (recetas, libro clínico, cotizaciones, reportes…). Cada módulo
registra su generador con `register_pdf_kind` (ver apps.pdfs.registry).
"""
