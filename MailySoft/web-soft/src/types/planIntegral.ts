/**
 * Tipos del "Plan Integral de Longevidad y Medicina Regenerativa" — una
 * constancia entregable AL PACIENTE (nivel paciente, no de una consulta).
 *
 * Reflejan EXACTAMENTE el CONTRATO del backend (apps/expediente):
 *   GET  /expediente/<patient_id>/plan-integral/borrador/?treatment_plan_id=<uuid?>
 *   POST /expediente/<patient_id>/plan-integral/
 *   GET  /expediente/plan-integral/<id>/pdf/        (flujo PDF async)
 *   GET  /expediente/<patient_id>/plan-integral/    (lista paginada)
 *
 * El borrador trae 4 secciones auto-rellenadas (alergias/antecedentes/
 * tratamientos_actuales/condiciones_mejorar) y 4 vacías (estudios/reporte_medico/
 * interconsulta/seguimiento). El `esquema` describe los tratamientos calendarizados
 * (proviene de un TreatmentPlan opcional). Regla: nada de `any`.
 */

/**
 * Encabezado NO editable del Plan Integral (datos de la clínica y del paciente).
 * `paciente_edad` puede venir null si no se conoce la fecha de nacimiento.
 */
export interface PlanIntegralEncabezado {
  paciente_nombre: string
  paciente_edad: number | null
  /** Fecha de emisión (YYYY-MM-DD o ISO). */
  fecha: string
  clinica_nombre: string
}

/**
 * Las 8 secciones EDITABLES del Plan Integral (texto libre). Las 4 primeras
 * llegan auto-rellenadas desde el expediente; las 4 restantes llegan vacías.
 * Mismo shape en el borrador y en el POST de creación.
 */
export interface PlanIntegralSecciones {
  /** Alergias (auto-rellenada). */
  alergias: string
  /** Antecedentes de importancia (auto-rellenada). */
  antecedentes: string
  /** Tratamientos actuales (auto-rellenada). */
  tratamientos_actuales: string
  /** Principales condiciones a mejorar (auto-rellenada). */
  condiciones_mejorar: string
  /** Reporte de estudios de laboratorio y gabinete (vacía). */
  estudios: string
  /** Reporte médico (vacía). */
  reporte_medico: string
  /** Interconsulta de departamentos (vacía). */
  interconsulta: string
  /** Seguimiento y acompañamiento (vacía). */
  seguimiento: string
}

/**
 * Un tratamiento del esquema (calendarización). `clinical_description` viene del
 * catálogo de servicios (ServiceConcept.clinical_description) — se edita ahí, no aquí.
 */
export interface PlanIntegralEsquemaItem {
  description: string
  quantity: number
  clinical_description: string
}

/** Un plan de tratamiento (TreatmentPlan) disponible para elegir en el selector. */
export interface PlanIntegralPlanDisponible {
  id: string
  title: string
  created_at: string
  items_count: number
}

/**
 * Un resultado de laboratorio ESTRUCTURADO capturado en el Plan Integral (Fase 3).
 * `analyte_id` es opcional (referencia al catálogo de analitos); nombre/unidad/
 * rango se snapshotean para que el documento no dependa de futuros cambios del
 * catálogo. `result` es el valor capturado (texto: puede ser numérico o no).
 *
 * REGLA: el front NO manda `out_of_range`; el backend lo calcula y snapshotea.
 * La UI solo lo colorea en vivo con el mismo criterio (fuera de [ref_low, ref_high]).
 */
export interface PlanIntegralLabResult {
  /** UUID del analito del catálogo, si se eligió uno (opcional). */
  analyte_id?: string
  name: string
  unit: string
  /** Límite inferior de referencia como string decimal, o null. */
  ref_low: string | null
  /** Límite superior de referencia como string decimal, o null. */
  ref_high: string | null
  /** Resultado capturado (texto libre; numérico para poder colorear el rango). */
  result: string
}

/** Un estudio de gabinete ESTRUCTURADO capturado en el Plan Integral (Fase 3). */
export interface PlanIntegralGabineteStudy {
  name: string
  conclusion: string
}

/**
 * Un integrante del equipo de la clínica mostrado (solo lectura) en el Plan
 * Integral (Fase 4). Se configura en "Mi Consultorio"; el backend lo snapshotea
 * al crear la constancia (NO se manda en el create).
 */
export interface PlanIntegralEquipoItem {
  departamento: string
  nombre: string
}

/**
 * Borrador del Plan Integral (GET .../plan-integral/borrador/): encabezado NO
 * editable + las 8 secciones + el esquema del plan elegido (o base) + los planes
 * de tratamiento disponibles para calendarizar.
 */
export interface PlanIntegralBorrador {
  encabezado: PlanIntegralEncabezado
  secciones: PlanIntegralSecciones
  esquema: PlanIntegralEsquemaItem[]
  planes_disponibles: PlanIntegralPlanDisponible[]
  /** Resultados de laboratorio capturados (arranca vacío en el borrador). */
  lab_results: PlanIntegralLabResult[]
  /** Estudios de gabinete capturados (arranca vacío en el borrador). */
  gabinete_studies: PlanIntegralGabineteStudy[]
  /** Equipo de la clínica (solo lectura; snapshot desde la configuración). */
  equipo: PlanIntegralEquipoItem[]
}

/**
 * Cuerpo del POST de creación: el plan de tratamiento elegido (opcional) + el
 * texto (ya editado) de las 8 secciones + los estudios estructurados (Fase 3).
 * El `equipo` NO se manda: el backend lo snapshotea desde la configuración.
 */
export interface PlanIntegralInput extends PlanIntegralSecciones {
  /** UUID del TreatmentPlan elegido para calendarizar (opcional). */
  treatment_plan_id?: string
  /** Resultados de laboratorio capturados (sin `out_of_range`: lo calcula el backend). */
  lab_results?: PlanIntegralLabResult[]
  /** Estudios de gabinete capturados. */
  gabinete_studies?: PlanIntegralGabineteStudy[]
}

/**
 * Constancia de Plan Integral guardada (respuesta del POST y de la lista).
 * El PDF se genera aparte por el flujo async (endpoint /pdf/).
 */
export interface PlanIntegral {
  id: string
  created_at: string
  doctor_name: string
}
