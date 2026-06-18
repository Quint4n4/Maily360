"""
Management command: seed_medicamentos

Carga el catálogo global de medicamentos comunes en GlobalMedication.

Características:
- Idempotente: usa get_or_create por (generic_name, concentration, form).
  Re-ejecutar no duplica entradas.
- Solo incluye denominaciones genéricas reales y concentraciones estándar
  bien conocidas del Cuadro Básico de Medicamentos / genéricos de uso frecuente
  en México (DR-7: no inventar datos clínicos).
- Concentraciones o presentaciones con incertidumbre se dejan en blanco.
- La dosis/indicación NUNCA va en este catálogo (DR-7). Es responsabilidad
  del médico al emitir la receta.

Uso:
    docker compose exec backend python manage.py seed_medicamentos
    python manage.py seed_medicamentos         # (fuera de Docker)
    python manage.py seed_medicamentos --dry-run  # solo cuenta sin insertar

Categorías incluidas:
  - Analgésicos / antipiréticos
  - AINEs
  - Antibióticos (betalactámicos, macrólidos, quinolonas, otros)
  - Antidiabéticos
  - Antihipertensivos (IECA, ARA-II, BCC, diuréticos, betabloqueadores)
  - Hipolipemiantes
  - Antiulcerosos / protectores gástricos
  - Antihistamínicos
  - Broncodilatadores / antiasmáticos
  - Corticoides (sistémicos y tópicos)
  - Anticonvulsivantes
  - Antidepresivos / ansiolíticos
  - Antiparasitarios
  - Antimicóticos
  - Antivirales
  - Vitaminas / minerales / suplementos básicos
  - Hormonas / tiroides
  - Hematología
  - Urológicos
  - Oftalmológicos
  - Dermatológicos
  - Ginecológicos
  - Gastrointestinales
  - Anestésicos / relajantes musculares (uso ambulatorio)
"""

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.recetas.models import GlobalMedication, MedicationForm

logger = logging.getLogger("apps.recetas.management.seed_medicamentos")

# ---------------------------------------------------------------------------
# Datos del catálogo: (generic_name, concentration, form, commercial_name, presentation)
# commercial_name y presentation son opcionales (pueden quedar en "").
# Fuente: Cuadro Básico y Catálogo de Medicamentos del Sector Salud (CBCM),
#         formularios farmacológicos de uso común en México.
# DR-7: solo datos identificativos; NUNCA indicaciones, dosis máximas ni CI.
# ---------------------------------------------------------------------------

MEDICAMENTOS: list[tuple[str, str, str, str, str]] = [
    # (generic_name, concentration, form, commercial_name, presentation)

    # --- Analgésicos / antipiréticos ---
    ("Paracetamol", "500 mg", MedicationForm.TABLETA, "Tempra / Panadol", "Caja con 20 tabletas"),
    ("Paracetamol", "1 g", MedicationForm.TABLETA, "", ""),
    ("Paracetamol", "250 mg/5 mL", MedicationForm.JARABE, "Tempra / Panadol", "Frasco 120 mL"),
    ("Paracetamol", "160 mg/5 mL", MedicationForm.JARABE, "", "Frasco 120 mL"),
    ("Paracetamol", "100 mg/mL", MedicationForm.GOTAS, "", "Frasco 15 mL"),

    # --- AINEs ---
    ("Ibuprofeno", "200 mg", MedicationForm.TABLETA, "Advil / Motrin", "Caja con 20 tabletas"),
    ("Ibuprofeno", "400 mg", MedicationForm.TABLETA, "Advil / Motrin", "Caja con 20 tabletas"),
    ("Ibuprofeno", "600 mg", MedicationForm.TABLETA, "", ""),
    ("Ibuprofeno", "100 mg/5 mL", MedicationForm.SUSPENSION, "Motrin pediátrico", "Frasco 120 mL"),
    ("Naproxeno", "250 mg", MedicationForm.TABLETA, "Naprosyn", ""),
    ("Naproxeno", "500 mg", MedicationForm.TABLETA, "Naprosyn", "Caja con 20 tabletas"),
    ("Naproxeno sódico", "275 mg", MedicationForm.TABLETA, "Flanax", "Caja con 24 tabletas"),
    ("Naproxeno sódico", "550 mg", MedicationForm.TABLETA, "Flanax forte", ""),
    ("Diclofenaco", "50 mg", MedicationForm.TABLETA, "Voltaren", "Caja con 20 tabletas"),
    ("Diclofenaco", "75 mg/3 mL", MedicationForm.SOLUCION_INYECTABLE, "", "Ampolleta 3 mL"),
    ("Diclofenaco", "1%", MedicationForm.GEL, "Voltaren gel", "Tubo 50 g"),
    ("Ketorolaco", "10 mg", MedicationForm.TABLETA, "Dolac", ""),
    ("Ketorolaco", "30 mg/mL", MedicationForm.SOLUCION_INYECTABLE, "Dolac", "Ampolleta 1 mL"),
    ("Meloxicam", "7.5 mg", MedicationForm.TABLETA, "Mobic", ""),
    ("Meloxicam", "15 mg", MedicationForm.TABLETA, "Mobic", ""),
    ("Celecoxib", "100 mg", MedicationForm.CAPSULA, "Celebrex", ""),
    ("Celecoxib", "200 mg", MedicationForm.CAPSULA, "Celebrex", ""),
    ("Metamizol sódico", "500 mg", MedicationForm.TABLETA, "Nolotil / Dipirona", ""),
    ("Metamizol sódico", "1 g/2 mL", MedicationForm.SOLUCION_INYECTABLE, "Dipirona", "Ampolleta 2 mL"),

    # --- Antibióticos — Betalactámicos ---
    ("Amoxicilina", "250 mg", MedicationForm.CAPSULA, "", ""),
    ("Amoxicilina", "500 mg", MedicationForm.CAPSULA, "Amoxil", "Caja con 12 cápsulas"),
    ("Amoxicilina", "875 mg", MedicationForm.TABLETA, "", ""),
    ("Amoxicilina", "250 mg/5 mL", MedicationForm.SUSPENSION, "Amoxil", "Frasco 100 mL"),
    ("Amoxicilina / Ácido clavulánico", "500 mg/125 mg", MedicationForm.TABLETA, "Augmentin", "Caja con 14 tabletas"),
    ("Amoxicilina / Ácido clavulánico", "875 mg/125 mg", MedicationForm.TABLETA, "Augmentin", ""),
    ("Amoxicilina / Ácido clavulánico", "200 mg/28.5 mg/5 mL", MedicationForm.SUSPENSION, "Augmentin ES", "Frasco 100 mL"),
    ("Ampicilina", "500 mg", MedicationForm.CAPSULA, "", ""),
    ("Ampicilina", "1 g", MedicationForm.SOLUCION_INYECTABLE, "", "Frasco ampolleta"),
    ("Cefalexina", "500 mg", MedicationForm.CAPSULA, "Keflex", "Caja con 12 cápsulas"),
    ("Cefalexina", "250 mg/5 mL", MedicationForm.SUSPENSION, "Keflex pediátrico", "Frasco 100 mL"),
    ("Cefuroxima", "250 mg", MedicationForm.TABLETA, "Zinnat", ""),
    ("Cefuroxima", "500 mg", MedicationForm.TABLETA, "Zinnat", ""),
    ("Ceftriaxona", "1 g", MedicationForm.SOLUCION_INYECTABLE, "Rocefin", "Frasco ampolleta"),
    ("Ceftriaxona", "500 mg", MedicationForm.SOLUCION_INYECTABLE, "", "Frasco ampolleta"),
    ("Cefixima", "400 mg", MedicationForm.TABLETA, "Suprax", ""),
    ("Cefixima", "100 mg/5 mL", MedicationForm.SUSPENSION, "Suprax", "Frasco 50 mL"),
    ("Dicloxacilina", "500 mg", MedicationForm.CAPSULA, "Posipen", ""),
    ("Penicilina G benzatínica", "1,200,000 UI", MedicationForm.SOLUCION_INYECTABLE, "Benzetacil", "Frasco ampolleta"),

    # --- Antibióticos — Macrólidos ---
    ("Azitromicina", "500 mg", MedicationForm.TABLETA, "Zithromax", "Caja con 3 tabletas"),
    ("Azitromicina", "250 mg", MedicationForm.TABLETA, "Zithromax", ""),
    ("Azitromicina", "200 mg/5 mL", MedicationForm.SUSPENSION, "Zithromax", "Frasco 15 mL"),
    ("Claritromicina", "250 mg", MedicationForm.TABLETA, "Klaricid", ""),
    ("Claritromicina", "500 mg", MedicationForm.TABLETA, "Klaricid", "Caja con 14 tabletas"),
    ("Claritromicina", "125 mg/5 mL", MedicationForm.SUSPENSION, "Klaricid", "Frasco 100 mL"),
    ("Eritromicina", "500 mg", MedicationForm.TABLETA, "", ""),

    # --- Antibióticos — Quinolonas ---
    ("Ciprofloxacino", "250 mg", MedicationForm.TABLETA, "Cipro", ""),
    ("Ciprofloxacino", "500 mg", MedicationForm.TABLETA, "Cipro", "Caja con 14 tabletas"),
    ("Levofloxacino", "500 mg", MedicationForm.TABLETA, "Tavanic", ""),
    ("Levofloxacino", "750 mg", MedicationForm.TABLETA, "Tavanic", ""),
    ("Norfloxacino", "400 mg", MedicationForm.TABLETA, "Urobacid", ""),

    # --- Antibióticos — Otros ---
    ("Metronidazol", "500 mg", MedicationForm.TABLETA, "Flagyl", "Caja con 14 tabletas"),
    ("Metronidazol", "250 mg/5 mL", MedicationForm.SUSPENSION, "Flagyl", "Frasco 120 mL"),
    ("Metronidazol", "500 mg/100 mL", MedicationForm.SOLUCION_INYECTABLE, "Flagyl IV", "Bolsa 100 mL"),
    ("Trimetoprim / Sulfametoxazol", "80 mg/400 mg", MedicationForm.TABLETA, "Bactrim", ""),
    ("Trimetoprim / Sulfametoxazol", "160 mg/800 mg", MedicationForm.TABLETA, "Bactrim forte", "Caja con 14 tabletas"),
    ("Trimetoprim / Sulfametoxazol", "40 mg/200 mg/5 mL", MedicationForm.SUSPENSION, "Bactrim pediátrico", "Frasco 100 mL"),
    ("Doxiciclina", "100 mg", MedicationForm.CAPSULA, "Vibramicina", "Caja con 10 cápsulas"),
    ("Clindamicina", "300 mg", MedicationForm.CAPSULA, "Cleocin / Dalacin C", ""),
    ("Clindamicina", "600 mg/4 mL", MedicationForm.SOLUCION_INYECTABLE, "Dalacin C", "Ampolleta 4 mL"),
    ("Nitrofurantoína", "100 mg", MedicationForm.CAPSULA, "Macrobid", ""),
    ("Fosfomicina trometamol", "3 g", MedicationForm.POLVO, "Monurol", "Sobre 3 g"),
    ("Gentamicina", "80 mg/2 mL", MedicationForm.SOLUCION_INYECTABLE, "", "Ampolleta 2 mL"),

    # --- Antidiabéticos ---
    ("Metformina", "500 mg", MedicationForm.TABLETA, "Glucophage", "Caja con 30 tabletas"),
    ("Metformina", "850 mg", MedicationForm.TABLETA, "Glucophage", "Caja con 30 tabletas"),
    ("Metformina", "1 g", MedicationForm.TABLETA, "Glucophage XR", ""),
    ("Glibenclamida", "5 mg", MedicationForm.TABLETA, "Daonil", "Caja con 30 tabletas"),
    ("Glipizida", "5 mg", MedicationForm.TABLETA, "Glucotrol", ""),
    ("Glimepirida", "2 mg", MedicationForm.TABLETA, "Amaryl", ""),
    ("Glimepirida", "4 mg", MedicationForm.TABLETA, "Amaryl", ""),
    ("Sitagliptina", "100 mg", MedicationForm.TABLETA, "Januvia", ""),
    ("Empagliflozina", "10 mg", MedicationForm.TABLETA, "Jardiance", ""),
    ("Empagliflozina", "25 mg", MedicationForm.TABLETA, "Jardiance", ""),
    ("Insulina NPH (isofánica)", "100 UI/mL", MedicationForm.SOLUCION_INYECTABLE, "Humulin N", "Frasco 10 mL"),
    ("Insulina glargina", "100 UI/mL", MedicationForm.SOLUCION_INYECTABLE, "Lantus", "Cartucho 3 mL"),

    # --- Antihipertensivos — IECA ---
    ("Enalapril", "5 mg", MedicationForm.TABLETA, "Renitec", ""),
    ("Enalapril", "10 mg", MedicationForm.TABLETA, "Renitec", "Caja con 30 tabletas"),
    ("Enalapril", "20 mg", MedicationForm.TABLETA, "Renitec", ""),
    ("Lisinopril", "5 mg", MedicationForm.TABLETA, "Prinivil / Zestril", ""),
    ("Lisinopril", "10 mg", MedicationForm.TABLETA, "Prinivil / Zestril", ""),
    ("Lisinopril", "20 mg", MedicationForm.TABLETA, "Prinivil / Zestril", ""),
    ("Ramipril", "5 mg", MedicationForm.TABLETA, "Altace / Tritace", ""),
    ("Ramipril", "10 mg", MedicationForm.TABLETA, "Altace", ""),
    ("Captopril", "25 mg", MedicationForm.TABLETA, "Capoten", ""),
    ("Captopril", "50 mg", MedicationForm.TABLETA, "Capoten", ""),

    # --- Antihipertensivos — ARA-II ---
    ("Losartán", "25 mg", MedicationForm.TABLETA, "Cozaar", ""),
    ("Losartán", "50 mg", MedicationForm.TABLETA, "Cozaar", "Caja con 30 tabletas"),
    ("Losartán", "100 mg", MedicationForm.TABLETA, "Cozaar", ""),
    ("Valsartán", "80 mg", MedicationForm.TABLETA, "Diovan", ""),
    ("Valsartán", "160 mg", MedicationForm.TABLETA, "Diovan", ""),
    ("Telmisartán", "40 mg", MedicationForm.TABLETA, "Micardis", ""),
    ("Telmisartán", "80 mg", MedicationForm.TABLETA, "Micardis", ""),
    ("Irbesartán", "150 mg", MedicationForm.TABLETA, "Avapro", ""),
    ("Irbesartán", "300 mg", MedicationForm.TABLETA, "Avapro", ""),

    # --- Antihipertensivos — BCC ---
    ("Amlodipino", "5 mg", MedicationForm.TABLETA, "Norvasc", "Caja con 30 tabletas"),
    ("Amlodipino", "10 mg", MedicationForm.TABLETA, "Norvasc", ""),
    ("Nifedipino", "30 mg", MedicationForm.TABLETA, "Adalat", ""),
    ("Nifedipino", "60 mg", MedicationForm.TABLETA, "Adalat OROS", ""),
    ("Diltiazem", "60 mg", MedicationForm.TABLETA, "Cardizem", ""),
    ("Diltiazem", "120 mg", MedicationForm.TABLETA, "Cardizem CD", ""),
    ("Verapamilo", "80 mg", MedicationForm.TABLETA, "Isoptin", ""),
    ("Verapamilo", "120 mg", MedicationForm.TABLETA, "Isoptin SR", ""),

    # --- Antihipertensivos — Diuréticos ---
    ("Hidroclorotiazida", "25 mg", MedicationForm.TABLETA, "Esidrex", ""),
    ("Furosemida", "20 mg", MedicationForm.TABLETA, "Lasix", ""),
    ("Furosemida", "40 mg", MedicationForm.TABLETA, "Lasix", "Caja con 20 tabletas"),
    ("Furosemida", "10 mg/mL", MedicationForm.SOLUCION_INYECTABLE, "Lasix", "Ampolleta 2 mL"),
    ("Espironolactona", "25 mg", MedicationForm.TABLETA, "Aldactone", ""),
    ("Espironolactona", "100 mg", MedicationForm.TABLETA, "Aldactone", ""),

    # --- Antihipertensivos — Betabloqueadores ---
    ("Metoprolol", "50 mg", MedicationForm.TABLETA, "Lopressor", ""),
    ("Metoprolol", "100 mg", MedicationForm.TABLETA, "Lopressor", ""),
    ("Atenolol", "50 mg", MedicationForm.TABLETA, "Tenormin", ""),
    ("Atenolol", "100 mg", MedicationForm.TABLETA, "Tenormin", ""),
    ("Carvedilol", "6.25 mg", MedicationForm.TABLETA, "Coreg", ""),
    ("Carvedilol", "12.5 mg", MedicationForm.TABLETA, "Coreg", ""),
    ("Carvedilol", "25 mg", MedicationForm.TABLETA, "Coreg", ""),
    ("Bisoprolol", "5 mg", MedicationForm.TABLETA, "Concor", ""),
    ("Bisoprolol", "10 mg", MedicationForm.TABLETA, "Concor", ""),
    ("Propranolol", "10 mg", MedicationForm.TABLETA, "Inderal", ""),
    ("Propranolol", "40 mg", MedicationForm.TABLETA, "Inderal", ""),

    # --- Hipolipemiantes ---
    ("Atorvastatina", "10 mg", MedicationForm.TABLETA, "Lipitor", ""),
    ("Atorvastatina", "20 mg", MedicationForm.TABLETA, "Lipitor", "Caja con 30 tabletas"),
    ("Atorvastatina", "40 mg", MedicationForm.TABLETA, "Lipitor", ""),
    ("Atorvastatina", "80 mg", MedicationForm.TABLETA, "Lipitor", ""),
    ("Rosuvastatina", "10 mg", MedicationForm.TABLETA, "Crestor", ""),
    ("Rosuvastatina", "20 mg", MedicationForm.TABLETA, "Crestor", ""),
    ("Simvastatina", "20 mg", MedicationForm.TABLETA, "Zocor", ""),
    ("Simvastatina", "40 mg", MedicationForm.TABLETA, "Zocor", ""),
    ("Pravastatina", "20 mg", MedicationForm.TABLETA, "Pravachol", ""),
    ("Ezetimiba", "10 mg", MedicationForm.TABLETA, "Zetia", ""),
    ("Fenofibrato", "160 mg", MedicationForm.TABLETA, "Tricor", ""),
    ("Fenofibrato micronizado", "200 mg", MedicationForm.CAPSULA, "Lipanthyl", ""),

    # --- Antiulcerosos / Protectores gástricos ---
    ("Omeprazol", "20 mg", MedicationForm.CAPSULA, "Prilosec / Losec", "Caja con 28 cápsulas"),
    ("Omeprazol", "40 mg", MedicationForm.CAPSULA, "Prilosec", ""),
    ("Omeprazol", "40 mg", MedicationForm.SOLUCION_INYECTABLE, "Losec IV", "Frasco ampolleta"),
    ("Pantoprazol", "20 mg", MedicationForm.TABLETA, "Protonix", ""),
    ("Pantoprazol", "40 mg", MedicationForm.TABLETA, "Protonix", "Caja con 28 tabletas"),
    ("Esomeprazol", "20 mg", MedicationForm.CAPSULA, "Nexium", ""),
    ("Esomeprazol", "40 mg", MedicationForm.CAPSULA, "Nexium", ""),
    ("Lansoprazol", "15 mg", MedicationForm.CAPSULA, "Prevacid", ""),
    ("Lansoprazol", "30 mg", MedicationForm.CAPSULA, "Prevacid", ""),
    ("Ranitidina", "150 mg", MedicationForm.TABLETA, "Zantac", ""),
    ("Ranitidina", "300 mg", MedicationForm.TABLETA, "Zantac", ""),
    ("Sucralfato", "1 g", MedicationForm.TABLETA, "Carafate", ""),
    ("Sucralfato", "200 mg/mL", MedicationForm.SUSPENSION, "Carafate", "Frasco 420 mL"),
    ("Bismuto subcitrato potásico", "120 mg", MedicationForm.TABLETA, "De-Nol", ""),

    # --- Antihistamínicos ---
    ("Loratadina", "10 mg", MedicationForm.TABLETA, "Claritin", "Caja con 10 tabletas"),
    ("Loratadina", "5 mg/5 mL", MedicationForm.JARABE, "Claritin", "Frasco 120 mL"),
    ("Cetirizina", "10 mg", MedicationForm.TABLETA, "Zyrtec", "Caja con 10 tabletas"),
    ("Cetirizina", "1 mg/mL", MedicationForm.JARABE, "Zyrtec", "Frasco 120 mL"),
    ("Fexofenadina", "120 mg", MedicationForm.TABLETA, "Allegra", ""),
    ("Fexofenadina", "180 mg", MedicationForm.TABLETA, "Allegra", ""),
    ("Levocetirizina", "5 mg", MedicationForm.TABLETA, "Xyzal", ""),
    ("Clorfeniramina", "4 mg", MedicationForm.TABLETA, "Chlor-Trimeton", ""),
    ("Dimenhidrinato", "50 mg", MedicationForm.TABLETA, "Dramamine", ""),
    ("Prometazina", "25 mg", MedicationForm.TABLETA, "Phenergan", ""),

    # --- Broncodilatadores / Antiasmáticos ---
    ("Salbutamol", "100 mcg/dosis", MedicationForm.AEROSOL, "Ventolin", "Inhalador 200 dosis"),
    ("Salbutamol", "2 mg/5 mL", MedicationForm.JARABE, "Ventolin", "Frasco 200 mL"),
    ("Salbutamol", "5 mg/mL", MedicationForm.SOLUCION, "Ventolin solución nebulización", "Frasco 20 mL"),
    ("Ipratropio", "20 mcg/dosis", MedicationForm.AEROSOL, "Atrovent", "Inhalador 200 dosis"),
    ("Budesonida", "200 mcg/dosis", MedicationForm.AEROSOL, "Pulmicort", "Inhalador 200 dosis"),
    ("Budesonida / Formoterol", "160 mcg/4.5 mcg/dosis", MedicationForm.AEROSOL, "Symbicort", ""),
    ("Fluticasona / Salmeterol", "250 mcg/50 mcg/dosis", MedicationForm.AEROSOL, "Seretide / Advair", ""),
    ("Montelukast", "10 mg", MedicationForm.TABLETA, "Singulair", ""),
    ("Montelukast", "4 mg", MedicationForm.TABLETA, "Singulair", "Caja con 30 tabletas"),
    ("Teofilina", "200 mg", MedicationForm.TABLETA, "Theo-Dur", ""),

    # --- Corticoides sistémicos ---
    ("Prednisona", "5 mg", MedicationForm.TABLETA, "Deltasone", ""),
    ("Prednisona", "20 mg", MedicationForm.TABLETA, "Deltasone", ""),
    ("Prednisona", "50 mg", MedicationForm.TABLETA, "Deltasone", ""),
    ("Prednisolona", "5 mg", MedicationForm.TABLETA, "Prelone", ""),
    ("Prednisolona", "1 mg/mL", MedicationForm.SOLUCION, "Prelone", "Frasco 120 mL"),
    ("Metilprednisolona", "500 mg", MedicationForm.SOLUCION_INYECTABLE, "Solu-Medrol", "Frasco ampolleta"),
    ("Dexametasona", "4 mg/mL", MedicationForm.SOLUCION_INYECTABLE, "Decadron", "Ampolleta 1 mL"),
    ("Betametasona", "0.05%", MedicationForm.CREMA, "Diprosone", "Tubo 20 g"),
    ("Triamcinolona", "0.1%", MedicationForm.CREMA, "Kenalog", "Tubo 15 g"),

    # --- Anticonvulsivantes ---
    ("Ácido valproico", "250 mg", MedicationForm.CAPSULA, "Depakene", ""),
    ("Ácido valproico", "500 mg", MedicationForm.TABLETA, "Depakote ER", ""),
    ("Carbamazepina", "200 mg", MedicationForm.TABLETA, "Tegretol", ""),
    ("Carbamazepina", "400 mg", MedicationForm.TABLETA, "Tegretol CR", ""),
    ("Fenitoína", "100 mg", MedicationForm.CAPSULA, "Dilantin", ""),
    ("Lamotrigina", "25 mg", MedicationForm.TABLETA, "Lamictal", ""),
    ("Lamotrigina", "50 mg", MedicationForm.TABLETA, "Lamictal", ""),
    ("Levetiracetam", "500 mg", MedicationForm.TABLETA, "Keppra", ""),
    ("Levetiracetam", "1000 mg", MedicationForm.TABLETA, "Keppra", ""),
    ("Topiramato", "25 mg", MedicationForm.TABLETA, "Topamax", ""),
    ("Topiramato", "100 mg", MedicationForm.TABLETA, "Topamax", ""),
    ("Gabapentina", "300 mg", MedicationForm.CAPSULA, "Neurontin", ""),
    ("Gabapentina", "600 mg", MedicationForm.TABLETA, "Neurontin", ""),
    ("Pregabalina", "75 mg", MedicationForm.CAPSULA, "Lyrica", ""),
    ("Pregabalina", "150 mg", MedicationForm.CAPSULA, "Lyrica", ""),
    ("Clonazepam", "0.5 mg", MedicationForm.TABLETA, "Rivotril", ""),
    ("Clonazepam", "2 mg", MedicationForm.TABLETA, "Rivotril", ""),

    # --- Antidepresivos / Ansiolíticos ---
    ("Sertralina", "50 mg", MedicationForm.TABLETA, "Zoloft", "Caja con 14 tabletas"),
    ("Sertralina", "100 mg", MedicationForm.TABLETA, "Zoloft", ""),
    ("Fluoxetina", "20 mg", MedicationForm.CAPSULA, "Prozac", "Caja con 14 cápsulas"),
    ("Escitalopram", "10 mg", MedicationForm.TABLETA, "Lexapro", ""),
    ("Escitalopram", "20 mg", MedicationForm.TABLETA, "Lexapro", ""),
    ("Paroxetina", "20 mg", MedicationForm.TABLETA, "Paxil", ""),
    ("Venlafaxina", "75 mg", MedicationForm.CAPSULA, "Effexor XR", ""),
    ("Venlafaxina", "150 mg", MedicationForm.CAPSULA, "Effexor XR", ""),
    ("Amitriptilina", "25 mg", MedicationForm.TABLETA, "Elavil", ""),
    ("Bupropión", "150 mg", MedicationForm.TABLETA, "Wellbutrin SR", ""),
    ("Mirtazapina", "15 mg", MedicationForm.TABLETA, "Remeron", ""),
    ("Alprazolam", "0.25 mg", MedicationForm.TABLETA, "Xanax", ""),
    ("Alprazolam", "0.5 mg", MedicationForm.TABLETA, "Xanax", ""),
    ("Diazepam", "5 mg", MedicationForm.TABLETA, "Valium", ""),
    ("Diazepam", "10 mg/2 mL", MedicationForm.SOLUCION_INYECTABLE, "Valium IV", "Ampolleta 2 mL"),
    ("Lorazepam", "1 mg", MedicationForm.TABLETA, "Ativan", ""),
    ("Zolpidem", "10 mg", MedicationForm.TABLETA, "Ambien", ""),
    ("Quetiapina", "25 mg", MedicationForm.TABLETA, "Seroquel", ""),
    ("Quetiapina", "100 mg", MedicationForm.TABLETA, "Seroquel", ""),

    # --- Antiparasitarios ---
    ("Metronidazol", "250 mg", MedicationForm.TABLETA, "Flagyl", ""),
    ("Albendazol", "200 mg", MedicationForm.TABLETA, "Albenza / Zentel", ""),
    ("Albendazol", "400 mg", MedicationForm.TABLETA, "Zentel", "Caja con 1 tableta"),
    ("Albendazol", "100 mg/5 mL", MedicationForm.SUSPENSION, "Zentel", "Frasco 20 mL"),
    ("Mebendazol", "100 mg", MedicationForm.TABLETA, "Vermox", "Caja con 6 tabletas"),
    ("Ivermectina", "6 mg", MedicationForm.TABLETA, "Stromectol / Ivexterm", ""),
    ("Nitazoxanida", "500 mg", MedicationForm.TABLETA, "Alinia", ""),
    ("Nitazoxanida", "100 mg/5 mL", MedicationForm.SUSPENSION, "Alinia pediátrico", "Frasco 60 mL"),
    ("Prazicuantel", "600 mg", MedicationForm.TABLETA, "Biltricide", ""),

    # --- Antimicóticos ---
    ("Fluconazol", "50 mg", MedicationForm.CAPSULA, "Diflucan", ""),
    ("Fluconazol", "150 mg", MedicationForm.CAPSULA, "Diflucan", "Caja con 1 cápsula"),
    ("Clotrimazol", "1%", MedicationForm.CREMA, "Lotrimin", "Tubo 20 g"),
    ("Ketoconazol", "200 mg", MedicationForm.TABLETA, "Nizoral", ""),
    ("Ketoconazol", "2%", MedicationForm.CREMA, "Nizoral", "Tubo 30 g"),
    ("Itraconazol", "100 mg", MedicationForm.CAPSULA, "Sporanox", ""),
    ("Terbinafina", "250 mg", MedicationForm.TABLETA, "Lamisil", ""),
    ("Terbinafina", "1%", MedicationForm.CREMA, "Lamisil", "Tubo 15 g"),
    ("Nistatina", "100,000 UI/g", MedicationForm.CREMA, "Mycostatin", "Tubo 30 g"),
    ("Nistatina", "100,000 UI/mL", MedicationForm.SUSPENSION, "Mycostatin", "Frasco 60 mL"),

    # --- Antivirales ---
    ("Aciclovir", "200 mg", MedicationForm.TABLETA, "Zovirax", ""),
    ("Aciclovir", "400 mg", MedicationForm.TABLETA, "Zovirax", ""),
    ("Aciclovir", "5%", MedicationForm.CREMA, "Zovirax", "Tubo 10 g"),
    ("Valaciclovir", "500 mg", MedicationForm.TABLETA, "Valtrex", ""),
    ("Valaciclovir", "1 g", MedicationForm.TABLETA, "Valtrex", ""),
    ("Oseltamivir", "75 mg", MedicationForm.CAPSULA, "Tamiflu", "Caja con 10 cápsulas"),

    # --- Vitaminas / Minerales / Suplementos ---
    ("Ácido fólico", "0.4 mg", MedicationForm.TABLETA, "Folicet", ""),
    ("Ácido fólico", "5 mg", MedicationForm.TABLETA, "", ""),
    ("Vitamina D3 (colecalciferol)", "1000 UI", MedicationForm.TABLETA, "", ""),
    ("Vitamina D3 (colecalciferol)", "2000 UI", MedicationForm.CAPSULA, "", ""),
    ("Vitamina B12 (cianocobalamina)", "1000 mcg/mL", MedicationForm.SOLUCION_INYECTABLE, "", "Ampolleta 1 mL"),
    ("Complejo B", "", MedicationForm.TABLETA, "", ""),
    ("Sulfato ferroso", "300 mg", MedicationForm.TABLETA, "Fer-In-Sol", ""),
    ("Hierro polimaltosado", "100 mg", MedicationForm.TABLETA, "Maltofer", ""),
    ("Calcio carbonato", "500 mg", MedicationForm.TABLETA, "Caltrate", ""),
    ("Calcio carbonato / Vitamina D3", "500 mg/400 UI", MedicationForm.TABLETA, "Caltrate Plus D", ""),
    ("Magnesio", "400 mg", MedicationForm.TABLETA, "", ""),
    ("Zinc", "220 mg", MedicationForm.CAPSULA, "", ""),
    ("Potasio cloruro", "600 mg", MedicationForm.TABLETA, "K-Dur", ""),
    ("Ácido ascórbico (Vitamina C)", "500 mg", MedicationForm.TABLETA, "", ""),
    ("Vitamina E (tocoferol)", "400 UI", MedicationForm.CAPSULA, "", ""),

    # --- Hormonas / Tiroides ---
    ("Levotiroxina sódica", "25 mcg", MedicationForm.TABLETA, "Synthroid / Eutirox", ""),
    ("Levotiroxina sódica", "50 mcg", MedicationForm.TABLETA, "Synthroid / Eutirox", ""),
    ("Levotiroxina sódica", "100 mcg", MedicationForm.TABLETA, "Synthroid / Eutirox", "Caja con 30 tabletas"),
    ("Levotiroxina sódica", "150 mcg", MedicationForm.TABLETA, "Synthroid", ""),
    ("Medroxiprogesterona", "150 mg/mL", MedicationForm.SOLUCION_INYECTABLE, "Depo-Provera", "Frasco 1 mL"),
    ("Anticonceptivo oral combinado (etinilestradiol/levonorgestrel)", "30 mcg/150 mcg", MedicationForm.TABLETA, "Microgynon", "Caja con 21 tabletas"),
    ("Anticonceptivo oral combinado (etinilestradiol/desogestrel)", "20 mcg/150 mcg", MedicationForm.TABLETA, "Mercilon", ""),
    ("Progesterona micronizada", "100 mg", MedicationForm.CAPSULA, "Prometrium / Utrogestan", ""),
    ("Progesterona micronizada", "200 mg", MedicationForm.CAPSULA, "Prometrium / Utrogestan", ""),

    # --- Hematología ---
    ("Enoxaparina", "40 mg/0.4 mL", MedicationForm.SOLUCION_INYECTABLE, "Clexane", "Jeringa prellenada 0.4 mL"),
    ("Enoxaparina", "60 mg/0.6 mL", MedicationForm.SOLUCION_INYECTABLE, "Clexane", "Jeringa prellenada 0.6 mL"),
    ("Warfarina", "5 mg", MedicationForm.TABLETA, "Coumadin", ""),
    ("Ácido acetilsalicílico", "81 mg", MedicationForm.TABLETA, "Aspirina protect", "Caja con 30 tabletas"),
    ("Ácido acetilsalicílico", "100 mg", MedicationForm.TABLETA, "Aspirina", ""),
    ("Clopidogrel", "75 mg", MedicationForm.TABLETA, "Plavix", ""),

    # --- Urológicos ---
    ("Tamsulosina", "0.4 mg", MedicationForm.CAPSULA, "Flomax", ""),
    ("Finasterida", "5 mg", MedicationForm.TABLETA, "Proscar", ""),
    ("Desmopresina", "0.1 mg", MedicationForm.TABLETA, "DDAVP", ""),
    ("Solifenacina", "5 mg", MedicationForm.TABLETA, "VESIcare", ""),
    ("Oxybutinina", "5 mg", MedicationForm.TABLETA, "Ditropan", ""),

    # --- Oftalmológicos ---
    ("Timolol", "0.5%", MedicationForm.GOTAS, "Timoptic", "Frasco 5 mL"),
    ("Latanoprost", "0.005%", MedicationForm.GOTAS, "Xalatan", "Frasco 2.5 mL"),
    ("Tobramicina / Dexametasona", "0.3%/0.1%", MedicationForm.GOTAS, "TobraDex", "Frasco 5 mL"),
    ("Ciprofloxacino oftálmico", "0.3%", MedicationForm.GOTAS, "Ciloxan", "Frasco 5 mL"),
    ("Lubricante ocular (carboximetilcelulosa)", "0.5%", MedicationForm.GOTAS, "Refresh Plus", "Monodosis"),

    # --- Dermatológicos ---
    ("Mupirocina", "2%", MedicationForm.UNGUENTO, "Bactroban", "Tubo 15 g"),
    ("Hidrocortisona", "1%", MedicationForm.CREMA, "Cortaid", "Tubo 30 g"),
    ("Permetrina", "1%", MedicationForm.CREMA, "Nix", "Frasco 60 mL"),
    ("Peróxido de benzoílo", "2.5%", MedicationForm.GEL, "Benzac AC", "Tubo 50 g"),
    ("Tretinoína", "0.025%", MedicationForm.CREMA, "Retin-A", "Tubo 20 g"),
    ("Tretinoína", "0.05%", MedicationForm.CREMA, "Retin-A", "Tubo 20 g"),
    ("Adapaleno", "0.1%", MedicationForm.GEL, "Differin", "Tubo 30 g"),
    ("Eritromicina tópica", "2%", MedicationForm.GEL, "Ery-Gel", "Tubo 30 g"),

    # --- Ginecológicos / Óvulos ---
    ("Clotrimazol", "100 mg", MedicationForm.OVULO, "Canesten", "Caja con 6 óvulos"),
    ("Clotrimazol", "500 mg", MedicationForm.OVULO, "Canesten 500", "Caja con 1 óvulo"),
    ("Metronidazol", "500 mg", MedicationForm.OVULO, "Flagyl vaginal", "Caja con 7 óvulos"),

    # --- Gastrointestinales ---
    ("Metoclopramida", "10 mg", MedicationForm.TABLETA, "Plasil / Reglan", ""),
    ("Metoclopramida", "5 mg/mL", MedicationForm.SOLUCION_INYECTABLE, "Plasil", "Ampolleta 2 mL"),
    ("Domperidona", "10 mg", MedicationForm.TABLETA, "Motilium", ""),
    ("Ondansetrón", "4 mg", MedicationForm.TABLETA, "Zofran", ""),
    ("Ondansetrón", "8 mg", MedicationForm.TABLETA, "Zofran", ""),
    ("Ondansetrón", "2 mg/mL", MedicationForm.SOLUCION_INYECTABLE, "Zofran", "Ampolleta 2 mL"),
    ("Loperamida", "2 mg", MedicationForm.CAPSULA, "Imodium", "Caja con 12 cápsulas"),
    ("Polietilenglicol 3350", "17 g", MedicationForm.POLVO, "MiraLax / Movicol", "Sobre"),
    ("Lactulosa", "10 g/15 mL", MedicationForm.SOLUCION, "Duphalac", "Frasco 300 mL"),
    ("Trimebutina", "200 mg", MedicationForm.TABLETA, "Debridat / Modulon", ""),
    ("Hioscina (butilbromuro)", "10 mg", MedicationForm.TABLETA, "Buscopan", ""),
    ("Hioscina (butilbromuro)", "20 mg/mL", MedicationForm.SOLUCION_INYECTABLE, "Buscopan", "Ampolleta 1 mL"),
    ("Simethicona", "80 mg", MedicationForm.TABLETA, "Gas-X", ""),
    ("Simethicona", "40 mg/0.6 mL", MedicationForm.GOTAS, "Mylicon", "Frasco 30 mL"),
    ("Simeticona / Dimeticona", "120 mg", MedicationForm.CAPSULA, "", ""),

    # --- Otros de uso frecuente ---
    ("Alopurinol", "100 mg", MedicationForm.TABLETA, "Zyloprim", ""),
    ("Alopurinol", "300 mg", MedicationForm.TABLETA, "Zyloprim", ""),
    ("Colchicina", "0.5 mg", MedicationForm.TABLETA, "Colcrys", ""),
    ("Metotrexato", "2.5 mg", MedicationForm.TABLETA, "Rheumatrex", ""),
    ("Hidroxicloroquina", "200 mg", MedicationForm.TABLETA, "Plaquenil", ""),
    ("Betahistina", "16 mg", MedicationForm.TABLETA, "Serc", ""),
    ("Piridoxina (Vitamina B6)", "10 mg", MedicationForm.TABLETA, "", ""),
    ("Ginkgo biloba", "40 mg", MedicationForm.TABLETA, "", ""),
]


class Command(BaseCommand):
    """Carga el catálogo global de medicamentos comunes.

    Idempotente: usa get_or_create por (generic_name, concentration, form).
    Re-ejecutar no duplica ni modifica entradas existentes.
    """

    help = "Carga (o actualiza idempotentemente) el catálogo global de medicamentos."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo muestra cuántos se crearían sin insertar en la BD.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = options["dry_run"]
        created_count = 0
        skipped_count = 0

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"seed_medicamentos: procesando {len(MEDICAMENTOS)} entradas "
                f"({'DRY-RUN' if dry_run else 'real'}) ..."
            )
        )

        for generic_name, concentration, form, commercial_name, presentation in MEDICAMENTOS:
            if dry_run:
                # En dry-run, contar sin tocar la BD.
                exists = GlobalMedication.objects.filter(
                    generic_name=generic_name,
                    concentration=concentration,
                    form=form,
                ).exists()
                if exists:
                    skipped_count += 1
                else:
                    created_count += 1
                continue

            _, was_created = GlobalMedication.objects.get_or_create(
                generic_name=generic_name,
                concentration=concentration,
                form=form,
                defaults={
                    "commercial_name": commercial_name,
                    "presentation": presentation,
                    "is_active": True,
                },
            )
            if was_created:
                created_count += 1
            else:
                skipped_count += 1

        total = GlobalMedication.objects.filter(is_active=True).count() if not dry_run else "N/A"

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY-RUN] Se crearían {created_count} medicamentos, "
                    f"{skipped_count} ya existirían."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"seed_medicamentos completado: "
                    f"{created_count} creados, {skipped_count} ya existían. "
                    f"Total activos en catálogo: {total}."
                )
            )

        logger.info(
            "seed_medicamentos: created=%d skipped=%d dry_run=%s",
            created_count,
            skipped_count,
            dry_run,
        )
