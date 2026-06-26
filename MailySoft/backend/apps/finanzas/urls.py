"""
URLs de la app finanzas.

Se incluyen en config/urls.py bajo el prefijo api/v1/ → /api/v1/finanzas/...
"""

from django.urls import path

from apps.finanzas.views import (
    AccountStatementApi,
    CfdiCancelApi,
    CfdiDetailApi,
    CfdiListCreateApi,
    ChargeDetailApi,
    ChargeListCreateApi,
    ConceptDetailApi,
    ConceptListCreateApi,
    DailySheetApi,
    DashboardApi,
    FiscalConfigApi,
    PaymentDetailApi,
    PaymentListCreateApi,
    PeriodReportApi,
    PeriodReportPdfApi,
    QuoteAcceptApi,
    QuoteDetailApi,
    QuoteListCreateApi,
    QuotePdfApi,
    QuoteSendApi,
    RetentionPanelApi,
)

urlpatterns = [
    # Catálogo de conceptos
    path("finanzas/conceptos/", ConceptListCreateApi.as_view(), name="finanzas-concept-list"),
    path("finanzas/conceptos/<uuid:concept_id>/", ConceptDetailApi.as_view(), name="finanzas-concept-detail"),
    # Configuración fiscal
    path("finanzas/config/", FiscalConfigApi.as_view(), name="finanzas-config"),
    # Cotizaciones
    path("finanzas/cotizaciones/", QuoteListCreateApi.as_view(), name="finanzas-quote-list"),
    path("finanzas/cotizaciones/<uuid:quote_id>/", QuoteDetailApi.as_view(), name="finanzas-quote-detail"),
    path("finanzas/cotizaciones/<uuid:quote_id>/enviar/", QuoteSendApi.as_view(), name="finanzas-quote-send"),
    path("finanzas/cotizaciones/<uuid:quote_id>/aceptar/", QuoteAcceptApi.as_view(), name="finanzas-quote-accept"),
    path("finanzas/cotizaciones/<uuid:quote_id>/pdf/", QuotePdfApi.as_view(), name="finanzas-quote-pdf"),
    # Cargos
    path("finanzas/cargos/", ChargeListCreateApi.as_view(), name="finanzas-charge-list"),
    path("finanzas/cargos/<uuid:charge_id>/", ChargeDetailApi.as_view(), name="finanzas-charge-detail"),
    # Pagos
    path("finanzas/pagos/", PaymentListCreateApi.as_view(), name="finanzas-payment-list"),
    path("finanzas/pagos/<uuid:payment_id>/", PaymentDetailApi.as_view(), name="finanzas-payment-detail"),
    # Estado de cuenta
    path("finanzas/estado-cuenta/<uuid:patient_id>/", AccountStatementApi.as_view(), name="finanzas-statement"),
    # CFDI
    path("finanzas/cfdi/", CfdiListCreateApi.as_view(), name="finanzas-cfdi-list"),
    path("finanzas/cfdi/<uuid:cfdi_id>/", CfdiDetailApi.as_view(), name="finanzas-cfdi-detail"),
    path("finanzas/cfdi/<uuid:cfdi_id>/cancelar/", CfdiCancelApi.as_view(), name="finanzas-cfdi-cancel"),
    # Dashboard
    path("finanzas/dashboard/", DashboardApi.as_view(), name="finanzas-dashboard"),
    # Fase 2 — Reporte de periodo + PDF + Cierre diario
    path("finanzas/reporte/", PeriodReportApi.as_view(), name="finanzas-period-report"),
    path("finanzas/reporte/pdf/", PeriodReportPdfApi.as_view(), name="finanzas-period-report-pdf"),
    path("finanzas/cierre-diario/", DailySheetApi.as_view(), name="finanzas-daily-sheet"),
    # Fase 3 — Panel de retención / analítica RFM
    path("finanzas/retencion/", RetentionPanelApi.as_view(), name="finanzas-retention-panel"),
]
