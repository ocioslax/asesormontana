"""
Servicio Web: Asesor de Seguridad en Alta Montaña
Sistema de análisis nivometeorológico y viabilidad Go/No Go con Google Gemini Pro
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, date, timedelta
import asyncio

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Cargar variables de entorno desde archivo .env si existe
load_dotenv()

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("mountain-safety-advisor")

# Inicialización de la aplicación FastAPI
app = FastAPI(
    title="Asesor de Seguridad en Alta Montaña",
    description="Sistema de análisis nivometeorológico y viabilidad Go/No Go con Google Gemini Pro",
    version="1.0.0"
)

# Configuración de CORS para llamadas asíncronas desde el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# System Prompt estricto definido en PASO 4
SYSTEM_PROMPT = """Actúa como un especialista en seguridad en montaña y gestión del riesgo en alta montaña. Tu objetivo es analizar el estado de una zona o ruta de montaña específica que el usuario te consulte y entregar un informe estructurado de viabilidad y riesgo. El análisis lo debes hacer en consideración del diagnóstico del tiempo de las últimas dos semanas, y la proyección de la ventana completa de la expedición solicitada (fechas y horarios de inicio, día y hora de ataque a cumbre, y fecha y hora de término provistos en el prompt).

Estructura tu respuesta EXACTAMENTE en los siguientes 3 apartados:
**1. Estado de la Nieve y Viabilidad del Ascenso:** Analiza la estabilidad, cohesión y estructura del manto nivoso (presencia de nieve fresca, placas de viento, capas débiles o terreno glaciar/hielo) a lo largo de las fechas de la expedición y de manera específica durante el día y hora estimada de cumbre. Considera el ciclo diurno térmico (rehielo nocturno/matinal vs radiación solar y fusión de tarde). Determina si el estado actual y su evolución permiten una progresión segura. Especifica el equipamiento técnico mínimo requerido (piolet, crampones, raquetas, equipo de autorrescate en grietas/avalanchas).
**2. Nivel de Riesgo General:** Asigna un nivel de peligro de avalanchas según la escala EAWS (Nivel 1-Bajo a Nivel 5-Muy Fuerte) e identifica el problema nivológico principal. Evalúa factores meteorológicos críticos en la cota de cumbre para la fecha y hora seleccionadas (sensación térmica por viento/wind chill, ráfagas, visibilidad, tormenta, UV). Define el riesgo residual operativo (Bajo, Moderado, Alto o Extremo).
**3. Recomendación Final y Criterio 'Go / No Go':** Emite una recomendación categórica: [EXPEDICIÓN RECOMENDADA (Go)] / [RECOMENDADA CON CONDICIONANTES / RUTA ALTERNATIVA] / [NO RECOMENDADA / ABORTAR (No Go)]. Valida y califica explícitamente el cronograma operativo propuesto: hora de salida, fecha y hora de cumbre, y hora de retorno. Confirma si el horario en cumbre es seguro o si debe ajustarse (hora límite estricta de cumbre y turn-around time para evitar la pérdida de rehielo, caída de piedras o la noche en el descenso). Enumera los desencadenantes de aborto inmediato en terreno.

*Nota: Si el usuario no especifica la ruta precisa o el nivel técnico del grupo, indica en el informe la necesidad de estos datos para una evaluación definitiva.*"""

def normalize_expedition_schedule(
    start_date_str: Optional[str],
    start_time_str: Optional[str],
    summit_date_str: Optional[str],
    summit_time_str: Optional[str],
    end_date_str: Optional[str],
    end_time_str: Optional[str],
    target_date_str: Optional[str] = None
) -> Dict[str, Any]:
    """
    Normaliza y valida cronológicamente el itinerario de la expedición:
      1. Fecha y hora de inicio (partida).
      2. Fecha y hora de ataque a cumbre (hito crítico).
      3. Fecha y hora de término (retorno).
    Calcula duración total en días y horas.
    """
    consultation_date = date.today()

    def clean_time(t_raw: Optional[str], default_h: int, default_m: int):
        if not t_raw:
            return f"{default_h:02d}:{default_m:02d}", default_h, default_m
        try:
            parts = str(t_raw).strip().split(":")
            h = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else default_h
            m = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else default_m
            h = max(0, min(23, h))
            m = max(0, min(59, m))
            return f"{h:02d}:{m:02d}", h, m
        except Exception:
            return f"{default_h:02d}:{default_m:02d}", default_h, default_m

    # 1. Inicio
    s_date = (start_date_str or target_date_str or (consultation_date + timedelta(days=1)).isoformat()).strip()
    try:
        s_d = datetime.strptime(s_date, "%Y-%m-%d").date()
    except Exception:
        s_d = consultation_date + timedelta(days=1)
        s_date = s_d.isoformat()

    s_time_clean, s_h, s_m = clean_time(start_time_str, 5, 0)
    s_dt = datetime(s_d.year, s_d.month, s_d.day, s_h, s_m)

    # 2. Término
    e_date = (end_date_str or (s_d + timedelta(days=2)).isoformat()).strip()
    try:
        e_d = datetime.strptime(e_date, "%Y-%m-%d").date()
    except Exception:
        e_d = s_d + timedelta(days=2)
        e_date = e_d.isoformat()

    e_time_clean, e_h, e_m = clean_time(end_time_str, 16, 0)
    e_dt = datetime(e_d.year, e_d.month, e_d.day, e_h, e_m)

    if e_dt <= s_dt:
        if e_d < s_d:
            e_d = s_d
            e_date = s_d.isoformat()
            e_dt = s_dt + timedelta(hours=8)
            e_time_clean = f"{e_dt.hour:02d}:{e_dt.minute:02d}"
        else:
            e_dt = s_dt + timedelta(hours=6)
            e_time_clean = f"{e_dt.hour:02d}:{e_dt.minute:02d}"

    # 3. Cumbre (por defecto: si es 1 día, mismo día a las 10:00; si es más días, día de cumbre o penúltimo día)
    summit_time_clean, sum_h, sum_m = clean_time(summit_time_str, 10, 0)
    if summit_date_str and summit_date_str.strip():
        try:
            sum_d = datetime.strptime(summit_date_str.strip(), "%Y-%m-%d").date()
        except Exception:
            sum_d = s_d if (e_d - s_d).days <= 1 else (e_d - timedelta(days=1))
    else:
        sum_d = s_d if (e_d - s_d).days <= 1 else (e_d - timedelta(days=1))

    sum_dt = datetime(sum_d.year, sum_d.month, sum_d.day, sum_h, sum_m)

    # Garantizar s_dt <= sum_dt <= e_dt
    if sum_dt < s_dt:
        sum_dt = s_dt + timedelta(hours=4)
        sum_d = sum_dt.date()
        summit_time_clean = f"{sum_dt.hour:02d}:{sum_dt.minute:02d}"
    elif sum_dt > e_dt:
        sum_dt = max(s_dt, e_dt - timedelta(hours=3))
        sum_d = sum_dt.date()
        summit_time_clean = f"{sum_dt.hour:02d}:{sum_dt.minute:02d}"

    summit_date_clean = sum_d.isoformat()
    duration_hours = round((e_dt - s_dt).total_seconds() / 3600.0, 1)
    duration_days = max(1, (e_d - s_d).days + 1)
    hours_to_summit = round((sum_dt - s_dt).total_seconds() / 3600.0, 1)

    return {
        "start_date": s_date,
        "start_time": s_time_clean,
        "summit_date": summit_date_clean,
        "summit_time": summit_time_clean,
        "end_date": e_date,
        "end_time": e_time_clean,
        "start_dt": s_dt,
        "summit_dt": sum_dt,
        "end_dt": e_dt,
        "duration_days": duration_days,
        "duration_hours": duration_hours,
        "hours_to_summit": hours_to_summit
    }

# Modelos Pydantic para validación de datos
class ExpeditionRequest(BaseModel):
    mountain_name: Optional[str] = Field(default="", description="Nombre del cerro, montaña o referencia geográfica (opcional si se selecciona en mapa)", example="Cerro El Plomo")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitud en grados decimales", example=-33.2319)
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitud en grados decimales", example=-70.2172)
    altitude: float = Field(..., ge=0.0, le=9000.0, description="Altitud en m.s.n.m.", example=5424.0)
    start_date: Optional[str] = Field(default=None, description="Fecha de inicio de la expedición (YYYY-MM-DD)", example="2026-11-15")
    start_time: Optional[str] = Field(default="05:00", description="Hora estimada de inicio/partida (HH:MM)", example="04:30")
    summit_date: Optional[str] = Field(default=None, description="Fecha estimada de ataque a cumbre (YYYY-MM-DD)", example="2026-11-17")
    summit_time: Optional[str] = Field(default="10:00", description="Hora estimada en cumbre (HH:MM)", example="10:00")
    end_date: Optional[str] = Field(default=None, description="Fecha de término de la expedición (YYYY-MM-DD)", example="2026-11-18")
    end_time: Optional[str] = Field(default="16:00", description="Hora estimada de retorno o término (HH:MM)", example="15:00")
    target_date: Optional[str] = Field(default=None, description="Fecha objetivo del ascenso (retrocompatibilidad)", example="2026-11-15")
    route: Optional[str] = Field(default="", description="Ruta prevista (opcional)", example="Ruta Normal por La Hoya")
    group_technical_level: Optional[str] = Field(default="", description="Nivel técnico de la cordada (opcional)", example="Intermedio con experiencia en cramponaje")

class WeatherSummary(BaseModel):
    source: str
    consultation_date: str
    start_date: Optional[str] = None
    start_time: Optional[str] = None
    summit_date: Optional[str] = None
    summit_time: Optional[str] = None
    end_date: Optional[str] = None
    end_time: Optional[str] = None
    target_date: str
    expedition_duration_days: Optional[int] = None
    expedition_duration_hours: Optional[float] = None
    zona_consultada: Optional[Dict[str, Any]] = None
    sumas_y_metricas_zona: Optional[Dict[str, Any]] = None
    ventana_expedicion: Optional[Dict[str, Any]] = None
    past_14_days: Dict[str, Any]
    forecast_until_target: Dict[str, Any]
    forecast_7_days: Optional[Dict[str, Any]] = None  # Retrocompatibilidad
    target_day_overview: Dict[str, Any]

class ViabilityResponse(BaseModel):
    success: bool
    mountain_name: str
    consultation_date: Optional[str] = None
    start_date: Optional[str] = None
    start_time: Optional[str] = None
    summit_date: Optional[str] = None
    summit_time: Optional[str] = None
    end_date: Optional[str] = None
    end_time: Optional[str] = None
    target_date: str
    expedition_duration_days: Optional[int] = None
    expedition_duration_hours: Optional[float] = None
    altitude: float
    coordinates: Dict[str, float]
    weather_context: Dict[str, Any]
    analysis_report: str
    verdict: str  # GO, CONDITIONAL, NO_GO, PENDING
    model_used: str
    is_simulation: bool
    timestamp: str

def generate_fallback_weather(
    latitude: float,
    longitude: float,
    altitude: float,
    start_date_str: str,
    end_date_str: str,
    start_time_str: str = "05:00",
    end_time_str: str = "16:00",
    summit_date_str: Optional[str] = None,
    summit_time_str: str = "10:00",
    mountain_name: str = "",
    route: str = ""
) -> Dict[str, Any]:
    """
    Genera un conjunto de datos meteorológicos sintéticos realistas basado en altitud
    en caso de que Open-Meteo no esté disponible o no haya conectividad externa.
    Cubre:
      1. Cronograma completo: Inicio, Cumbre y Término con fechas y horas.
      2. Dos semanas previas a la fecha de consulta.
      3. Pronóstico del tiempo hasta la fecha de término solicitada.
    """
    consultation_date = date.today()
    sched = normalize_expedition_schedule(
        start_date_str=start_date_str,
        start_time_str=start_time_str,
        summit_date_str=summit_date_str,
        summit_time_str=summit_time_str,
        end_date_str=end_date_str,
        end_time_str=end_time_str
    )

    start_d = datetime.strptime(sched["start_date"], "%Y-%m-%d").date()
    end_d = datetime.strptime(sched["end_date"], "%Y-%m-%d").date()
    summit_d = datetime.strptime(sched["summit_date"], "%Y-%m-%d").date()
    expedition_duration_days = sched["duration_days"]
    expedition_duration_hours = sched["duration_hours"]

    # Gradiente térmico aproximado: -6.5°C por cada 1000m
    base_temp = 18.0 - (altitude / 1000.0 * 6.5)
    
    # 1. Dos semanas previas a la fecha de consulta
    past_dates = [(consultation_date - timedelta(days=i)).isoformat() for i in range(14, 0, -1)]
    past_snow = [12.0 if i in (3, 4, 10) else (3.0 if i in (8, 9) else 0.0) for i in range(14)]
    past_precip = [18.0 if i in (3, 4, 10) else (5.0 if i in (8, 9) else 0.0) for i in range(14)]
    past_tmax = [round(base_temp + (i % 3) - 2.0, 1) for i in range(14)]
    past_tmin = [round(base_temp - 8.0 - (i % 4), 1) for i in range(14)]
    past_wind = [round(35.0 + (i * 3.5 % 45.0), 1) for i in range(14)]

    past_14 = {
        "description": "Diagnóstico del clima de 2 semanas previas a la fecha de consulta",
        "date_range": f"{past_dates[0]} al {past_dates[-1]}",
        "dates": past_dates,
        "temp_max_c": past_tmax,
        "temp_min_c": past_tmin,
        "precipitation_sum_mm": past_precip,
        "snowfall_sum_cm": past_snow,
        "wind_gusts_max_kmh": past_wind,
        "dominant_conditions": "Ciclo de nevadas intermitentes con vientos moderados a fuertes en cotas altas."
    }

    # 2. Pronóstico del tiempo hasta el término de la expedición (inclusivo)
    delta_days = (end_d - consultation_date).days
    num_forecast_days = max(1, delta_days + 1)
    future_dates = [(consultation_date + timedelta(days=i)).isoformat() for i in range(0, num_forecast_days)]

    fut_snow = [round(15.0 if (i % 4 == 2) else (2.0 if i % 3 == 0 else 0.0), 1) for i in range(len(future_dates))]
    fut_precip = [round(22.0 if (i % 4 == 2) else (3.5 if i % 3 == 0 else 0.0), 1) for i in range(len(future_dates))]
    fut_tmax = [round(base_temp + 1.0 - ((i % 5) * 0.5), 1) for i in range(len(future_dates))]
    fut_tmin = [round(base_temp - 7.5 - ((i % 5) * 0.8), 1) for i in range(len(future_dates))]
    fut_wind = [round(28.0 + ((i * 7) % 55), 1) for i in range(len(future_dates))]

    forecast_until_target = {
        "description": f"Pronóstico del tiempo desde la fecha de consulta ({consultation_date}) hasta el término de la expedición ({sched['end_date']})",
        "date_range": f"{future_dates[0]} al {future_dates[-1]}",
        "total_days": len(future_dates),
        "dates": future_dates,
        "temp_max_c": fut_tmax,
        "temp_min_c": fut_tmin,
        "precipitation_probability_pct": [min(95, 15 + ((i * 12) % 75)) for i in range(len(future_dates))],
        "precipitation_sum_mm": fut_precip,
        "snowfall_sum_cm": fut_snow,
        "wind_gusts_max_kmh": fut_wind,
        "trend": f"Evolución proyectada para el cronograma: Partida {sched['start_date']} ({sched['start_time']}) ➔ Cumbre {sched['summit_date']} ({sched['summit_time']}) ➔ Retorno {sched['end_date']} ({sched['end_time']})."
    }

    # 3. Ventana específica de la expedición y desglose diario
    expedition_dates = []
    expedition_tmax = []
    expedition_tmin = []
    expedition_snow = []
    expedition_precip = []
    expedition_wind = []
    expedition_daily_breakdown = []

    for idx, d_str in enumerate(future_dates):
        d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
        if start_d <= d_obj <= end_d:
            expedition_dates.append(d_str)
            tmax = fut_tmax[idx]
            tmin = fut_tmin[idx]
            sn = fut_snow[idx]
            pr = fut_precip[idx]
            w = fut_wind[idx]
            expedition_tmax.append(tmax)
            expedition_tmin.append(tmin)
            expedition_snow.append(sn)
            expedition_precip.append(pr)
            expedition_wind.append(w)
            day_num = len(expedition_dates)

            if d_str == sched["summit_date"]:
                role_hint = f"🎯 ATAQUE A CUMBRE (Hora estimada en cumbre: {sched['summit_time']} hrs)"
            elif day_num == 1:
                role_hint = f"Aproximación / Partida ({sched['start_time']} hrs)"
            elif day_num == expedition_duration_days:
                role_hint = f"Descenso final / Retorno ({sched['end_time']} hrs)"
            else:
                role_hint = "Tránsito / Campamento de altura"

            expedition_daily_breakdown.append({
                "dia_numero": day_num,
                "etapa_sugerida": role_hint,
                "es_dia_cumbre": (d_str == sched["summit_date"]),
                "fecha": d_str,
                "temp_max_c": tmax,
                "temp_min_c": tmin,
                "nieve_estimada_cm": sn,
                "precipitacion_estimada_mm": pr,
                "rafagas_max_kmh": w
            })

    if not expedition_daily_breakdown:
        expedition_daily_breakdown.append({
            "dia_numero": 1,
            "etapa_sugerida": f"Ataque a cumbre y retorno ({sched['start_time']} a {sched['end_time']} hrs)",
            "es_dia_cumbre": True,
            "fecha": sched["start_date"],
            "temp_max_c": round(base_temp, 1),
            "temp_min_c": round(base_temp - 8.0, 1),
            "nieve_estimada_cm": 0.0,
            "precipitacion_estimada_mm": 0.0,
            "rafagas_max_kmh": 40.0
        })
        expedition_dates = [sched["start_date"]]
        expedition_snow = [0.0]
        expedition_precip = [0.0]
        expedition_tmin = [round(base_temp - 8.0, 1)]
        expedition_tmax = [round(base_temp, 1)]
        expedition_wind = [40.0]

    ventana_expedicion = {
        "fecha_inicio": sched["start_date"],
        "hora_inicio": sched["start_time"],
        "fecha_cumbre": sched["summit_date"],
        "hora_cumbre": sched["summit_time"],
        "fecha_termino": sched["end_date"],
        "hora_termino": sched["end_time"],
        "duracion_dias": expedition_duration_days,
        "duracion_horas": expedition_duration_hours,
        "horas_hasta_cumbre": sched["hours_to_summit"],
        "cronograma_resumen": f"Partida: {sched['start_date']} ({sched['start_time']}) ➔ Cumbre: {sched['summit_date']} ({sched['summit_time']}) ➔ Retorno: {sched['end_date']} ({sched['end_time']})",
        "fechas_comprendidas": expedition_dates,
        "desglose_diario": expedition_daily_breakdown,
        "metricas_clave": {
            "nieve_acumulada_durante_expedicion_cm": round(sum(expedition_snow), 1),
            "precipitacion_acumulada_durante_expedicion_mm": round(sum(expedition_precip), 1),
            "temperatura_minima_extrema_c": min(expedition_tmin),
            "temperatura_maxima_extrema_c": max(expedition_tmax),
            "rafaga_viento_maxima_esperada_kmh": max(expedition_wind)
        }
    }

    # Datos de la zona consultada y sumas/acumulados
    zona_consultada = {
        "nombre_referencia": mountain_name or f"Zona Coordenadas ({latitude:.4f}, {longitude:.4f})",
        "coordenadas_solicitadas": {
            "latitud": latitude,
            "longitud": longitude
        },
        "altitud_solicitada_msnm": altitude,
        "fecha_consulta": consultation_date.isoformat(),
        "fecha_inicio_expedicion": sched["start_date"],
        "hora_inicio_expedicion": sched["start_time"],
        "fecha_cumbre_expedicion": sched["summit_date"],
        "hora_cumbre_expedicion": sched["summit_time"],
        "fecha_termino_expedicion": sched["end_date"],
        "hora_termino_expedicion": sched["end_time"],
        "duracion_expedicion_dias": expedition_duration_days,
        "duracion_expedicion_horas": expedition_duration_hours,
        "ruta_prevista": route if route else "No especificada",
        "grid_meteorologico": {
            "latitud_grid": latitude,
            "longitud_grid": longitude,
            "elevacion_grid_msnm": altitude,
            "tipo_proveedor": "Simulado Calibrado (Fallback Offline)"
        }
    }

    sumas_y_metricas_zona = {
        "nieve_acumulada_14d_previos_cm": round(sum(past_snow), 1),
        "precipitacion_acumulada_14d_previos_mm": round(sum(past_precip), 1),
        "nieve_acumulada_ventana_expedicion_cm": round(sum(expedition_snow), 1),
        "precipitacion_acumulada_ventana_expedicion_mm": round(sum(expedition_precip), 1),
        "nieve_proyectada_hasta_objetivo_cm": round(sum(fut_snow), 1),
        "precipitacion_proyectada_hasta_objetivo_mm": round(sum(fut_precip), 1),
        "nieve_total_periodo_analizado_cm": round(sum(past_snow + fut_snow), 1),
        "precipitacion_total_periodo_analizado_mm": round(sum(past_precip + fut_precip), 1),
        "temperatura_minima_extrema_c": min(past_tmin + fut_tmin),
        "temperatura_maxima_extrema_c": max(past_tmax + fut_tmax),
        "rafaga_viento_maxima_esperada_kmh": max(past_wind + fut_wind),
        "rafaga_maxima_durante_expedicion_kmh": max(expedition_wind)
    }

    return {
        "source": "Sintético Calibrado por Altitud (Fallback Offline)",
        "consultation_date": consultation_date.isoformat(),
        "start_date": sched["start_date"],
        "start_time": sched["start_time"],
        "summit_date": sched["summit_date"],
        "summit_time": sched["summit_time"],
        "end_date": sched["end_date"],
        "end_time": sched["end_time"],
        "target_date": sched["summit_date"],
        "expedition_duration_days": expedition_duration_days,
        "expedition_duration_hours": expedition_duration_hours,
        "elevation_m": altitude,
        "zona_consultada": zona_consultada,
        "sumas_y_metricas_zona": sumas_y_metricas_zona,
        "ventana_expedicion": ventana_expedicion,
        "past_14_days": past_14,
        "forecast_until_target": forecast_until_target,
        "forecast_7_days": forecast_until_target,  # Compatibilidad
        "target_day_overview": {
            "summit_date": sched["summit_date"],
            "summit_time": sched["summit_time"],
            "start_date": sched["start_date"],
            "end_date": sched["end_date"],
            "target_date": sched["summit_date"],
            "estimated_summit_temp_c": round(base_temp - 3.0, 1),
            "estimated_wind_speed_kmh": max(expedition_wind),
            "freeze_level_m": max(1500.0, round(altitude - 1200.0))
        }
    }

async def fetch_openmeteo_weather(
    latitude: float,
    longitude: float,
    altitude: float,
    start_date_str: str,
    end_date_str: str,
    start_time_str: str = "05:00",
    end_time_str: str = "16:00",
    summit_date_str: Optional[str] = None,
    summit_time_str: str = "10:00",
    mountain_name: str = "",
    route: str = ""
) -> Dict[str, Any]:
    """
    Consulta la API de Open-Meteo para obtener:
      1. Cronograma completo: Inicio, Ataque a Cumbre y Término con fechas y horas.
      2. Clima de dos semanas previas a la fecha de consulta (past_days=14).
      3. Pronóstico del tiempo cubriendo todo el rango de la expedición.
      4. Aislamiento y desglose diario con foco en la jornada y hora de cumbre.
    """
    consultation_date = date.today()
    sched = normalize_expedition_schedule(
        start_date_str=start_date_str,
        start_time_str=start_time_str,
        summit_date_str=summit_date_str,
        summit_time_str=summit_time_str,
        end_date_str=end_date_str,
        end_time_str=end_time_str
    )

    start_d = datetime.strptime(sched["start_date"], "%Y-%m-%d").date()
    end_d = datetime.strptime(sched["end_date"], "%Y-%m-%d").date()
    summit_d = datetime.strptime(sched["summit_date"], "%Y-%m-%d").date()
    expedition_duration_days = sched["duration_days"]
    expedition_duration_hours = sched["duration_hours"]

    delta_days = (end_d - consultation_date).days
    # Días requeridos desde hoy hasta la fecha de término (inclusive)
    requested_forecast_days = max(1, delta_days + 1)
    # Límite máximo de pronóstico de Open-Meteo estándar es 16 días
    api_forecast_days = min(requested_forecast_days, 16)

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "elevation": altitude,
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "snowfall_sum",
            "wind_speed_10m_max",
            "wind_gusts_10m_max"
        ],
        "past_days": 14,
        "forecast_days": api_forecast_days,
        "timezone": "auto"
    }

    try:
        async with httpx.AsyncClient(timeout=7.0) as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                daily = data.get("daily", {})
                dates = daily.get("time", [])
                
                # Las primeras 14 posiciones corresponden a las 2 semanas previas a hoy
                idx_today = min(14, len(dates))
                past_dates = dates[:idx_today]
                future_dates = dates[idx_today:]
                
                temp_max = [float(x) if x is not None else 0.0 for x in daily.get("temperature_2m_max", [])]
                temp_min = [float(x) if x is not None else -5.0 for x in daily.get("temperature_2m_min", [])]
                precip = [float(x) if x is not None else 0.0 for x in daily.get("precipitation_sum", [])]
                snowfall = [float(x) if x is not None else 0.0 for x in daily.get("snowfall_sum", [])]
                wind_gusts = [float(x) if x is not None else 20.0 for x in daily.get("wind_gusts_10m_max", [])]

                past_snow = snowfall[:idx_today]
                past_precip = precip[:idx_today]
                past_tmax = temp_max[:idx_today]
                past_tmin = temp_min[:idx_today]
                past_wind = wind_gusts[:idx_today]

                past_14 = {
                    "description": "Diagnóstico del clima de 2 semanas previas a la fecha de consulta",
                    "date_range": f"{past_dates[0]} al {past_dates[-1]}" if past_dates else "14 días previos",
                    "dates": past_dates,
                    "temp_max_c": past_tmax,
                    "temp_min_c": past_tmin,
                    "precipitation_sum_mm": past_precip,
                    "snowfall_sum_cm": past_snow,
                    "wind_gusts_max_kmh": past_wind,
                }

                # Si la fecha de término excede el límite directo de 16 días de Open-Meteo,
                # se proyectan tendencialmente los días restantes hasta la fecha de término
                if requested_forecast_days > len(future_dates) and future_dates:
                    last_date_obj = datetime.strptime(future_dates[-1], "%Y-%m-%d").date()
                    extra_days = (end_d - last_date_obj).days
                    for i in range(1, extra_days + 1):
                        ext_date = (last_date_obj + timedelta(days=i)).isoformat()
                        future_dates.append(ext_date)
                        temp_max.append(temp_max[-1] if temp_max else 0.0)
                        temp_min.append(temp_min[-1] if temp_min else -5.0)
                        precip.append(0.0)
                        snowfall.append(0.0)
                        wind_gusts.append(wind_gusts[-1] if wind_gusts else 30.0)

                fut_snow = snowfall[idx_today:idx_today + len(future_dates)]
                fut_precip = precip[idx_today:idx_today + len(future_dates)]
                fut_tmax = temp_max[idx_today:idx_today + len(future_dates)]
                fut_tmin = temp_min[idx_today:idx_today + len(future_dates)]
                fut_wind = wind_gusts[idx_today:idx_today + len(future_dates)]

                forecast_until_target = {
                    "description": f"Pronóstico del tiempo desde la fecha de consulta ({consultation_date}) hasta el término de la expedición ({sched['end_date']})",
                    "date_range": f"{future_dates[0]} al {future_dates[-1]}" if future_dates else f"Hasta {sched['end_date']}",
                    "total_days": len(future_dates),
                    "dates": future_dates,
                    "temp_max_c": fut_tmax,
                    "temp_min_c": fut_tmin,
                    "precipitation_sum_mm": fut_precip,
                    "snowfall_sum_cm": fut_snow,
                    "wind_gusts_max_kmh": fut_wind,
                }

                # Aislamiento y análisis diario específico de la ventana de expedición
                expedition_dates = []
                expedition_tmax = []
                expedition_tmin = []
                expedition_snow = []
                expedition_precip = []
                expedition_wind = []
                expedition_daily_breakdown = []

                for idx, d_str in enumerate(future_dates):
                    d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
                    if start_d <= d_obj <= end_d:
                        expedition_dates.append(d_str)
                        tmax = fut_tmax[idx]
                        tmin = fut_tmin[idx]
                        sn = fut_snow[idx]
                        pr = fut_precip[idx]
                        w = fut_wind[idx]
                        expedition_tmax.append(tmax)
                        expedition_tmin.append(tmin)
                        expedition_snow.append(sn)
                        expedition_precip.append(pr)
                        expedition_wind.append(w)
                        day_num = len(expedition_dates)

                        if d_str == sched["summit_date"]:
                            role_hint = f"🎯 ATAQUE A CUMBRE (Hora estimada en cumbre: {sched['summit_time']} hrs)"
                        elif day_num == 1:
                            role_hint = f"Aproximación / Partida ({sched['start_time']} hrs)"
                        elif day_num == expedition_duration_days:
                            role_hint = f"Descenso final / Retorno ({sched['end_time']} hrs)"
                        else:
                            role_hint = "Tránsito / Altura"

                        expedition_daily_breakdown.append({
                            "dia_numero": day_num,
                            "etapa_sugerida": role_hint,
                            "es_dia_cumbre": (d_str == sched["summit_date"]),
                            "fecha": d_str,
                            "temp_max_c": tmax,
                            "temp_min_c": tmin,
                            "nieve_estimada_cm": sn,
                            "precipitacion_estimada_mm": pr,
                            "rafagas_max_kmh": w
                        })

                if not expedition_daily_breakdown:
                    expedition_daily_breakdown.append({
                        "dia_numero": 1,
                        "etapa_sugerida": f"Ataque a cumbre y retorno ({sched['start_time']} - {sched['end_time']} hrs)",
                        "es_dia_cumbre": True,
                        "fecha": sched["start_date"],
                        "temp_max_c": fut_tmax[0] if fut_tmax else 0.0,
                        "temp_min_c": fut_tmin[0] if fut_tmin else -5.0,
                        "nieve_estimada_cm": 0.0,
                        "precipitacion_estimada_mm": 0.0,
                        "rafagas_max_kmh": fut_wind[0] if fut_wind else 30.0
                    })
                    expedition_dates = [sched["start_date"]]
                    expedition_snow = [0.0]
                    expedition_precip = [0.0]
                    expedition_tmin = [fut_tmin[0] if fut_tmin else -5.0]
                    expedition_tmax = [fut_tmax[0] if fut_tmax else 0.0]
                    expedition_wind = [fut_wind[0] if fut_wind else 30.0]

                ventana_expedicion = {
                    "fecha_inicio": sched["start_date"],
                    "hora_inicio": sched["start_time"],
                    "fecha_cumbre": sched["summit_date"],
                    "hora_cumbre": sched["summit_time"],
                    "fecha_termino": sched["end_date"],
                    "hora_termino": sched["end_time"],
                    "duracion_dias": expedition_duration_days,
                    "duracion_horas": expedition_duration_hours,
                    "horas_hasta_cumbre": sched["hours_to_summit"],
                    "cronograma_resumen": f"Partida: {sched['start_date']} ({sched['start_time']}) ➔ Cumbre: {sched['summit_date']} ({sched['summit_time']}) ➔ Retorno: {sched['end_date']} ({sched['end_time']})",
                    "fechas_comprendidas": expedition_dates,
                    "desglose_diario": expedition_daily_breakdown,
                    "metricas_clave": {
                        "nieve_acumulada_durante_expedicion_cm": round(sum(expedition_snow), 1),
                        "precipitacion_acumulada_durante_expedicion_mm": round(sum(expedition_precip), 1),
                        "temperatura_minima_extrema_c": min(expedition_tmin) if expedition_tmin else None,
                        "temperatura_maxima_extrema_c": max(expedition_tmax) if expedition_tmax else None,
                        "rafaga_viento_maxima_esperada_kmh": max(expedition_wind) if expedition_wind else None
                    }
                }

                # Datos de la zona consultada
                zona_consultada = {
                    "nombre_referencia": mountain_name or f"Zona Coordenadas ({latitude:.4f}, {longitude:.4f})",
                    "coordenadas_solicitadas": {
                        "latitud": latitude,
                        "longitud": longitude
                    },
                    "altitud_solicitada_msnm": altitude,
                    "fecha_consulta": consultation_date.isoformat(),
                    "fecha_inicio_expedicion": sched["start_date"],
                    "hora_inicio_expedicion": sched["start_time"],
                    "fecha_cumbre_expedicion": sched["summit_date"],
                    "hora_cumbre_expedicion": sched["summit_time"],
                    "fecha_termino_expedicion": sched["end_date"],
                    "hora_termino_expedicion": sched["end_time"],
                    "duracion_expedicion_dias": expedition_duration_days,
                    "duracion_expedicion_horas": expedition_duration_hours,
                    "ruta_prevista": route if route else "No especificada",
                    "grid_openmeteo": {
                        "latitud_grid": data.get("latitude", latitude),
                        "longitud_grid": data.get("longitude", longitude),
                        "elevacion_grid_msnm": data.get("elevation", altitude),
                        "zona_horaria": data.get("timezone", "auto"),
                        "desfase_utc_segundos": data.get("utc_offset_seconds", 0),
                        "tiempo_generacion_ms": data.get("generationtime_ms", 0.0)
                    }
                }

                # Sumas y métricas acumuladas de la zona
                all_tmin = past_tmin + fut_tmin
                all_tmax = past_tmax + fut_tmax
                all_wind = past_wind + fut_wind

                sumas_y_metricas_zona = {
                    "nieve_acumulada_14d_previos_cm": round(sum(past_snow), 1),
                    "precipitacion_acumulada_14d_previos_mm": round(sum(past_precip), 1),
                    "nieve_acumulada_ventana_expedicion_cm": round(sum(expedition_snow), 1),
                    "precipitacion_acumulada_ventana_expedicion_mm": round(sum(expedition_precip), 1),
                    "nieve_proyectada_hasta_objetivo_cm": round(sum(fut_snow), 1),
                    "precipitacion_proyectada_hasta_objetivo_mm": round(sum(fut_precip), 1),
                    "nieve_total_periodo_analizado_cm": round(sum(past_snow + fut_snow), 1),
                    "precipitacion_total_periodo_analizado_mm": round(sum(past_precip + fut_precip), 1),
                    "temperatura_minima_extrema_c": min(all_tmin) if all_tmin else None,
                    "temperatura_maxima_extrema_c": max(all_tmax) if all_tmax else None,
                    "rafaga_viento_maxima_esperada_kmh": max(all_wind) if all_wind else None,
                    "rafaga_maxima_durante_expedicion_kmh": max(expedition_wind) if expedition_wind else (max(all_wind) if all_wind else None)
                }
                
                logger.info(
                    f"Datos meteorológicos obtenidos de Open-Meteo para {zona_consultada['nombre_referencia']}: "
                    f"Historial ({past_14['date_range']}) | Cronograma (Partida {sched['start_date']} {sched['start_time']} ➔ Cumbre {sched['summit_date']} {sched['summit_time']} ➔ Retorno {sched['end_date']} {sched['end_time']})"
                )
                return {
                    "source": "Open-Meteo Live API",
                    "consultation_date": consultation_date.isoformat(),
                    "start_date": sched["start_date"],
                    "start_time": sched["start_time"],
                    "summit_date": sched["summit_date"],
                    "summit_time": sched["summit_time"],
                    "end_date": sched["end_date"],
                    "end_time": sched["end_time"],
                    "target_date": sched["summit_date"],
                    "expedition_duration_days": expedition_duration_days,
                    "expedition_duration_hours": expedition_duration_hours,
                    "elevation_m": data.get("elevation", altitude),
                    "zona_consultada": zona_consultada,
                    "sumas_y_metricas_zona": sumas_y_metricas_zona,
                    "ventana_expedicion": ventana_expedicion,
                    "past_14_days": past_14,
                    "forecast_until_target": forecast_until_target,
                    "forecast_7_days": forecast_until_target,  # Compatibilidad
                    "target_day_overview": {
                        "summit_date": sched["summit_date"],
                        "summit_time": sched["summit_time"],
                        "start_date": sched["start_date"],
                        "end_date": sched["end_date"],
                        "target_date": sched["summit_date"],
                        "elevation_used": data.get("elevation", altitude)
                    }
                }
            else:
                logger.warning(f"Open-Meteo devolvió código {response.status_code}. Usando fallback sintético.")
                return generate_fallback_weather(
                    latitude=latitude,
                    longitude=longitude,
                    altitude=altitude,
                    start_date_str=start_date_str,
                    end_date_str=end_date_str,
                    start_time_str=start_time_str,
                    end_time_str=end_time_str,
                    summit_date_str=summit_date_str,
                    summit_time_str=summit_time_str,
                    mountain_name=mountain_name,
                    route=route
                )
    except Exception as exc:
        logger.warning(f"No fue posible conectar con Open-Meteo ({exc}). Usando fallback sintético.")
        return generate_fallback_weather(
            latitude=latitude,
            longitude=longitude,
            altitude=altitude,
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            start_time_str=start_time_str,
            end_time_str=end_time_str,
            summit_date_str=summit_date_str,
            summit_time_str=summit_time_str,
            mountain_name=mountain_name,
            route=route
        )

def call_gemini_pro(
    prompt: str,
    system_instruction: str,
    mountain_name: str = "",
    altitude: float = 3000.0,
    weather_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Envía el prompt al modelo Gemini Pro utilizando el SDK oficial google-generativeai.
    Gestiona compatibilidad de versiones de modelos y contingencia experta dinámica.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    
    if not api_key:
        logger.warning("GEMINI_API_KEY no encontrada en el entorno. Generando informe en modo contingencia.")
        return {
            "text": simulate_expert_response(mountain_name, altitude, weather_data),
            "model": "simulated-engine (GEMINI_API_KEY no configurada)",
            "is_simulation": True
        }

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        # Candidatos prioritarios compatibles con la versión actual de la API de Gemini
        model_candidates = [
            "gemini-3.8-flash",
            "gemini-pro-latest",
            "gemini-flash-latest",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-pro"
        ]

        last_error = None
        
        for candidate in model_candidates:
            try:
                try:
                    model = genai.GenerativeModel(
                        model_name=candidate,
                        system_instruction=system_instruction
                    )
                    full_prompt = prompt
                except TypeError:
                    model = genai.GenerativeModel(model_name=candidate)
                    full_prompt = f"INSTRUCCIÓN DEL SISTEMA:\n{system_instruction}\n\n---\nSOLICITUD:\n{prompt}"

                response = model.generate_content(full_prompt)
                if response and response.text:
                    logger.info(f"¡Éxito! Respuesta generada directamente por Google Gemini ({candidate}) para '{mountain_name}'")
                    return {
                        "text": response.text,
                        "model": candidate,
                        "is_simulation": False
                    }
            except Exception as e:
                last_error = e
                logger.debug(f"Candidato '{candidate}' no disponible: {e}")

        # Si ninguno de la lista directa respondió, intentar auto-descubrimiento en list_models()
        try:
            for m in genai.list_models():
                if "generateContent" in m.supported_generation_methods:
                    cand_name = m.name.replace("models/", "")
                    try:
                        model = genai.GenerativeModel(model_name=cand_name)
                        full_prompt = f"INSTRUCCIÓN DEL SISTEMA:\n{system_instruction}\n\n---\nSOLICITUD:\n{prompt}"
                        response = model.generate_content(full_prompt)
                        if response and response.text:
                            logger.info(f"Respuesta generada mediante modelo auto-descubierto: {cand_name}")
                            return {
                                "text": response.text,
                                "model": cand_name,
                                "is_simulation": False
                            }
                    except Exception:
                        continue
        except Exception as e_discover:
            logger.warning(f"Fallo en auto-descubrimiento de modelos: {e_discover}")

        raise RuntimeError(f"No fue posible invocar ningún modelo de Gemini: {last_error}")

    except Exception as err:
        logger.error(f"Error al conectar con la API de Google Gemini: {err}")
        simulated_text = simulate_expert_response(mountain_name, altitude, weather_data)
        error_note = (
            f"> [!WARNING]\n"
            f"> **Aviso de Conexión Gemini:** Hubo una incidencia con la API ({str(err)}). "
            f"Se muestra a continuación el análisis generado por el motor de contingencia para **{mountain_name}**.\n\n"
        )
        return {
            "text": error_note + simulated_text,
            "model": "fallback-simulation",
            "is_simulation": True
        }

def simulate_expert_response(
    mountain_name: str,
    altitude: float,
    weather_data: Optional[Dict[str, Any]] = None
) -> str:
    """
    Genera un informe nivometeorológico dinámico y personalizado para la zona y altitud
    específica en caso de indisponibilidad de la API externa.
    """
    target_name = mountain_name or "Zona de montaña seleccionada"
    metrics = (weather_data or {}).get("sumas_y_metricas_zona", {})
    ventana = (weather_data or {}).get("ventana_expedicion", {})
    snow_sum = metrics.get("nieve_total_periodo_analizado_cm", 25.0)
    wind_max = metrics.get("rafaga_viento_maxima_esperada_kmh", 55.0)
    t_min = metrics.get("temperatura_minima_extrema_c", -15.0)

    start_date_str = ventana.get("fecha_inicio") or (weather_data or {}).get("start_date", "Inicio")
    start_time_str = ventana.get("hora_inicio") or (weather_data or {}).get("start_time", "05:00")
    summit_date_str = ventana.get("fecha_cumbre") or (weather_data or {}).get("summit_date", start_date_str)
    summit_time_str = ventana.get("hora_cumbre") or (weather_data or {}).get("summit_time", "10:00")
    end_date_str = ventana.get("fecha_termino") or (weather_data or {}).get("end_date", "Término")
    end_time_str = ventana.get("hora_termino") or (weather_data or {}).get("end_time", "16:00")
    duration_days = ventana.get("duracion_dias", 1)
    duration_hours = ventana.get("duracion_horas", 24.0)
    cronograma_resumen = ventana.get("cronograma_resumen") or f"Partida {start_date_str} ({start_time_str}) ➔ Cumbre {summit_date_str} ({summit_time_str}) ➔ Retorno {end_date_str} ({end_time_str})"

    # Determinar si la hora de cumbre es tardía (> 12:30)
    try:
        sh_val = int(summit_time_str.split(":")[0])
    except Exception:
        sh_val = 10
    summit_timing_warning = ""
    if sh_val >= 13:
        summit_timing_warning = (
            f" ⚠️ Advertencia: El horario propuesto en cumbre ({summit_time_str} hrs) es tardío; "
            f"se recomienda adelantar el ataque para alcanzar la cumbre antes de las 11:30 hrs y evitar nieve sopa o tormentas vespertinas."
        )

    # Determinar veredicto y nivel EAWS basado en métricas reales de la zona
    if wind_max > 70.0 or snow_sum > 60.0 or altitude > 6000:
        verdict = "[NO RECOMENDADA / ABORTAR (No Go)]"
        risk_level = "Nivel 4 (Fuerte)"
        op_risk = "Extremo"
        snow_state = (
            f"En {target_name} ({altitude} m.s.n.m.), el manto nivoso presenta alta inestabilidad durante el periodo de expedición "
            f"({start_date_str} a {end_date_str}) y especialmente durante la jornada de cumbre ({summit_date_str} a las {summit_time_str} hrs), "
            f"debido a acumulaciones recientes de {snow_sum} cm de nieve con severo transporte eólico. Se observan placas de viento reactivas en pendientes "
            f"superiores a 28° y riesgo inminente de desencadenamiento espontáneo en laderas de sotavento."
        )
    elif wind_max > 45.0 or snow_sum > 20.0 or altitude > 4000:
        verdict = "[RECOMENDADA CON CONDICIONANTES / RUTA ALTERNATIVA]"
        risk_level = "Nivel 3 (Marcado)"
        op_risk = "Alto"
        snow_state = (
            f"Para {target_name} ({altitude} m.s.n.m.), durante el cronograma propuesto ({start_date_str} a {end_date_str}), el manto presenta cohesión variable con costras de rehielo matinales "
            f"y presencia de placas de viento en aristas expuestas. Con {snow_sum} cm acumulados y ráfagas estimadas de {wind_max} km/h para el día de cumbre ({summit_date_str}), "
            f"la progresión solo es viable evitando canales cerrados y transitando estrictamente por laderas protegidas o aristas de roca firme."
        )
    else:
        verdict = "[EXPEDICIÓN RECOMENDADA (Go)]"
        risk_level = "Nivel 2 (Limitado)"
        op_risk = "Moderado"
        snow_state = (
            f"Las condiciones en {target_name} ({altitude} m.s.n.m.) durante la expedición ({start_date_str} a {end_date_str}) muestran un manto nivoso en proceso de consolidación favorable. "
            f"Con ráfagas contenidas ({wind_max} km/h) y temperaturas mínimas de {t_min}°C, el manto nivoso permite una progresión "
            f"firme durante la ventana matinal, alcanzando la cumbre en el horario planificado ({summit_date_str} {summit_time_str} hrs) aprovechando el buen rehielo nocturno."
        )

    equip = (
        "Piolet de tracción o travesía, crampones de 12 puntas con antibott debidamente ajustados, casco homologado, "
        "sonda nival de 240 cm, pala metálica de avalanchas, DVA/Arva de triple antena en frecuencia 457 kHz y botiquín térmico."
    )

    return (
        f"**1. Estado de la Nieve y Viabilidad del Ascenso:**\n"
        f"{snow_state}\n\n"
        f"*Equipamiento técnico mínimo requerido:* {equip}\n\n"
        f"**2. Nivel de Riesgo General:**\n"
        f"Se asigna un **{risk_level}** según la escala europea EAWS. Problema nivológico predominante: "
        f"Placas de viento y capas débiles persistentes por gradiente térmico. Factores críticos: ráfagas de hasta {wind_max} km/h, "
        f"sensación térmica extrema de {t_min - 8.0:.1f}°C y visibilidad reducida en cotas altas durante las fechas analizadas.\n"
        f"Riesgo residual operativo: **{op_risk}**.\n\n"
        f"**3. Recomendación Final y Criterio 'Go / No Go':**\n"
        f"**{verdict}**\n\n"
        f"- **Zona evaluada:** {target_name} ({altitude} m.s.n.m.)\n"
        f"- **Cronograma operativo:** {cronograma_resumen} (Total: {duration_days} {'día' if duration_days == 1 else 'días'} / {duration_hours} hrs)\n"
        f"- **Jornada y Horario de Cumbre Propuesto:** {summit_date_str} a las {summit_time_str} hrs.{summit_timing_warning}\n"
        f"- **Ventana horaria y hora límite (turn-around time):** Salida a las {start_time_str} hrs. Hora límite de retorno de cumbre: 12:00 PM sin excepción.\n"
        f"- **Desencadenantes de aborto inmediato en terreno:** Ráfagas sostenidas sobre 60 km/h, desprendimientos o colapsos tipo 'whoomf', "
        f"pérdida de visibilidad por niebla/viento blanco o reblandecimiento acelerado de la nieve antes de mediodía.\n\n"
        f"*Nota: Si el usuario no especifica la ruta precisa o el nivel técnico de la cordada, se requiere validar de antemano "
        f"la experiencia técnica del grupo para una evaluación definitiva.*"
    )

def extract_verdict(analysis_text: str) -> str:
    """
    Extrae la clasificación del veredicto a partir de la Sección 3 del informe generado.
    Evita falsos positivos provocados por la frase 'Go / No Go' en el título o en el texto explicativo.
    """
    if not analysis_text:
        return "CONDITIONAL"

    # 1. Localizar la Sección 3 (Recomendación Final)
    idx_sec3 = -1
    for marker in ["3. Recomendación Final", "3. RECOMENDACIÓN FINAL", "3. Recomendación", "3. RECOMENDACIÓN"]:
        pos = analysis_text.find(marker)
        if pos != -1:
            idx_sec3 = pos
            break

    # Si se encontró la Sección 3, descartar la línea del encabezado para no capturar "No Go" del título
    if idx_sec3 != -1:
        sec3_text = analysis_text[idx_sec3:]
        lines = sec3_text.split("\n", 1)
        target_text = lines[1] if len(lines) > 1 else lines[0]
    else:
        target_text = analysis_text

    upper = target_text.upper()

    # 2. Búsqueda jerárquica de patrones
    # Prioridad A: NO RECOMENDADA / ABORTAR (debe ser una recomendación explícita de aborto)
    is_no_go = (
        "[NO RECOMENDADA" in upper or
        "NO RECOMENDADA / ABORTAR" in upper or
        "ABORTAR (NO GO)" in upper or
        "[ABORTAR" in upper or
        "EXPEDICIÓN NO RECOMENDADA" in upper or
        "VEREDICTO: NO GO" in upper or
        "VEREDICTO: [NO GO]" in upper or
        "[NO GO]" in upper
    )

    # Prioridad B: RECOMENDADA CON CONDICIONANTES / RUTA ALTERNATIVA
    is_conditional = (
        "RECOMENDADA CON CONDICIONANTES" in upper or
        "CONDICIONANTES / RUTA ALTERNATIVA" in upper or
        "RUTA ALTERNATIVA" in upper or
        "CONDICIONANTES" in upper or
        "[CONDICIONADA" in upper
    )

    # Prioridad C: EXPEDICIÓN RECOMENDADA (GO)
    is_go = (
        "EXPEDICIÓN RECOMENDADA" in upper or
        "[EXPEDICIÓN RECOMENDADA" in upper or
        "[RECOMENDADA (GO)]" in upper or
        "VEREDICTO: GO" in upper or
        "VEREDICTO: [GO]" in upper or
        "[GO]" in upper or
        "ASCENSO RECOMENDADO" in upper
    )

    # Evaluación coherente
    if is_no_go and not is_conditional and not is_go:
        return "NO_GO"
    elif is_conditional:
        return "CONDITIONAL"
    elif is_go:
        return "GO"
    elif is_no_go:
        return "NO_GO"

    # Si el análisis asigna peligro bajo y riesgo residual bajo
    if "NIVEL 1" in upper or "NIVEL 1 - BAJO" in upper or "BAJO RIESGO" in upper:
        return "GO"

    return "CONDITIONAL"

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Sirve la interfaz web Frontend estilo Adminator."""
    index_file = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(
        content="<h1>Asesor de Seguridad en Alta Montaña</h1><p>Archivo index.html no encontrado.</p>",
        status_code=404
    )

@app.get("/planificador", response_class=HTMLResponse)
async def serve_planner():
    """Sirve la herramienta especializada de Planificación de Ascenso y Gestión del Riesgo."""
    planner_file = os.path.join(os.path.dirname(__file__), "planificador.html")
    if os.path.exists(planner_file):
        with open(planner_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(
        content="<h1>Planificador de Ascenso</h1><p>Archivo planificador.html no encontrado.</p>",
        status_code=404
    )

@app.get("/api/health")
async def health_check():
    """Endpoint de estado y diagnóstico del servicio."""
    gemini_key_set = bool(os.getenv("GEMINI_API_KEY", "").strip())
    return {
        "status": "healthy",
        "service": "Asesor de Seguridad en Alta Montaña",
        "gemini_api_configured": gemini_key_set,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/geocode")
async def geocode_location(q: str):
    """
    Busca zonas geográficas y cumbres por nombre en OpenStreetMap (Nominatim API),
    complementando con la elevación topográfica de Open-Meteo.
    """
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Debe ingresar un término de búsqueda.")

    results = []
    headers = {"User-Agent": "MountainSafetyAdvisor/1.0 (info@mountainsafety.org)"}
    
    # 1. Búsqueda primaria en OpenStreetMap (Nominatim)
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "addressdetails": 1, "limit": 5},
                headers=headers
            )
            if resp.status_code == 200:
                raw_items = resp.json()
                for item in raw_items:
                    lat = round(float(item["lat"]), 4)
                    lon = round(float(item["lon"]), 4)
                    display_name = item.get("display_name", "")
                    
                    # Consultar elevación para estas coordenadas en Open-Meteo Elevation
                    elevation = None
                    try:
                        elev_resp = await client.get(
                            "https://api.open-meteo.com/v1/elevation",
                            params={"latitude": lat, "longitude": lon},
                            timeout=3.0
                        )
                        if elev_resp.status_code == 200:
                            elev_data = elev_resp.json()
                            elev_list = elev_data.get("elevation", [])
                            if elev_list and elev_list[0] is not None:
                                elevation = round(float(elev_list[0]))
                    except Exception as e_elev:
                        logger.debug(f"No fue posible obtener elevación: {e_elev}")

                    results.append({
                        "name": item.get("name") or query,
                        "display_name": display_name,
                        "latitude": lat,
                        "longitude": lon,
                        "elevation": elevation,
                        "type": item.get("type", "montaña"),
                        "source": "OpenStreetMap Nominatim"
                    })
    except Exception as e:
        logger.warning(f"Error consultando OpenStreetMap Nominatim: {e}")

    # 2. Fallback a Open-Meteo Geocoding si no hubo resultados de OpenStreetMap
    if not results:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                om_resp = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": query, "count": 5, "language": "es", "format": "json"}
                )
                if om_resp.status_code == 200:
                    om_data = om_resp.json()
                    for r in om_data.get("results", []):
                        lat = round(float(r["latitude"]), 4)
                        lon = round(float(r["longitude"]), 4)
                        country = r.get("country", "")
                        admin1 = r.get("admin1", "")
                        disp = f"{r.get('name')}, {admin1}, {country}".strip(", ")
                        results.append({
                            "name": r.get("name"),
                            "display_name": disp,
                            "latitude": lat,
                            "longitude": lon,
                            "elevation": round(float(r.get("elevation"))) if r.get("elevation") else None,
                            "type": "cumbre/relieve",
                            "source": "Open-Meteo Geocoding"
                        })
        except Exception as e2:
            logger.warning(f"Error en fallback de geocodificación: {e2}")

    return {"query": query, "count": len(results), "results": results}

@app.post("/api/analyze", response_model=ViabilityResponse)
async def analyze_expedition(req: ExpeditionRequest):
    """
    Endpoint principal: recibe los datos de la montaña y expedición,
    normaliza el cronograma (partida, cumbre y retorno con fechas y horas),
    recopila el contexto meteorológico (últimas 2 semanas y ventana completa de expedición),
    y genera el informe de viabilidad técnica mediante Gemini Pro.
    """
    try:
        # Si el usuario no especificó nombre o usó el mapa, usar coordenadas como referencia
        display_name = req.mountain_name.strip() if (req.mountain_name and req.mountain_name.strip()) else f"Zona Coordenadas ({req.latitude:.4f}, {req.longitude:.4f})"
        
        # Normalizar cronograma completo (inicio, cumbre y retorno con fechas y horas)
        sched = normalize_expedition_schedule(
            start_date_str=req.start_date,
            start_time_str=req.start_time,
            summit_date_str=req.summit_date,
            summit_time_str=req.summit_time,
            end_date_str=req.end_date,
            end_time_str=req.end_time,
            target_date_str=req.target_date
        )

        start_date_str = sched["start_date"]
        start_time_str = sched["start_time"]
        summit_date_str = sched["summit_date"]
        summit_time_str = sched["summit_time"]
        end_date_str = sched["end_date"]
        end_time_str = sched["end_time"]
        expedition_days = sched["duration_days"]
        expedition_hours = sched["duration_hours"]
        
        logger.info(
            f"Iniciando evaluación para: {display_name} (Alt: {req.altitude}m | "
            f"Cronograma: Partida {start_date_str} {start_time_str} ➔ Cumbre {summit_date_str} {summit_time_str} ➔ Retorno {end_date_str} {end_time_str} "
            f"[{expedition_days} días / {expedition_hours} hrs])"
        )

        # 1. Recopilación de datos meteorológicos (Open-Meteo con fallback automático)
        weather_data = await fetch_openmeteo_weather(
            latitude=req.latitude,
            longitude=req.longitude,
            altitude=req.altitude,
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            start_time_str=start_time_str,
            end_time_str=end_time_str,
            summit_date_str=summit_date_str,
            summit_time_str=summit_time_str,
            mountain_name=display_name,
            route=req.route or ""
        )

        # 2. Formulación del Prompt para Gemini
        past_info = weather_data.get('past_14_days', {})
        forecast_info = weather_data.get('forecast_until_target') or weather_data.get('forecast_7_days', {})
        ventana_info = weather_data.get('ventana_expedicion', {})
        consultation_date_str = weather_data.get('consultation_date', str(date.today()))

        user_prompt = f"""EVALUACIÓN DE EXPEDICIÓN EN ALTA MONTAÑA

PARÁMETROS DE LA EXPEDICIÓN Y ZONA CONSULTADA:
{json.dumps(weather_data.get('zona_consultada', {}), indent=2, ensure_ascii=False)}

CRONOGRAMA OPERATIVO PROPUESTO (DURACIÓN TOTAL: {expedition_days} DÍAS / {expedition_hours} HORAS):
- Partida / Inicio: {start_date_str} a las {start_time_str} hrs
- Ataque a Cumbre (Hito Crítico): {summit_date_str} a las {summit_time_str} hrs (Tiempo estimado hasta cumbre: {sched['hours_to_summit']} hrs)
- Retorno al campamento base o término: {end_date_str} a las {end_time_str} hrs
- Resumen: {ventana_info.get('cronograma_resumen', f'{start_date_str} a {end_date_str}')}

VENTANA DE LA EXPEDICIÓN Y DESGLOSE DIARIO:
{json.dumps(ventana_info, indent=2, ensure_ascii=False)}

MÉTRICAS Y SUMAS ACUMULADAS DE LA ZONA:
{json.dumps(weather_data.get('sumas_y_metricas_zona', {}), indent=2, ensure_ascii=False)}

CONTEXTO METEOROLÓGICO DETALLADO:
Fuente de datos: {weather_data.get('source')}

1. Diagnóstico del clima de las dos semanas previas a la fecha de consulta ({past_info.get('date_range', '14 días previos')}):
{json.dumps(past_info, indent=2, ensure_ascii=False)}

2. Proyección meteorológica desde la fecha de consulta hasta el término de la expedición ({forecast_info.get('date_range', f'hasta {end_date_str}')}):
{json.dumps(forecast_info, indent=2, ensure_ascii=False)}

INSTRUCCIONES CLAVE DE ANÁLISIS:
1. Evalúa de forma prioritaria la jornada y horario de cumbre propuestos ({summit_date_str} a las {summit_time_str} hrs). Analiza si las condiciones de viento, temperatura, radiación solar y estabilidad nival a esa hora específica son viables o si se debe ajustar el horario de ataque.
2. Analiza detalladamente la evolución del manto nivoso y el clima a lo largo de TODO el cronograma (días de aproximación, tránsito en altura, ataque a cumbre y descenso final).
3. En la Sección 3, califica explícitamente el cronograma (hora de partida, horario en cumbre y hora de retorno) y valida la hora límite estricta de retorno (turn-around time) para evitar descensos peligrosos por nieve transformada o falta de luz.
4. Entrega tu veredicto considerando si existe una ventana viable y segura para completar la expedición completa (ida, cumbre y regreso seguro).

Por favor, elabora el informe técnico de seguridad siguiendo estrictamente los 3 apartados indicados en la instrucción del sistema."""

        # 3. Invocación asíncrona a Gemini Pro sin bloquear el loop de Uvicorn
        gemini_result = await asyncio.to_thread(
            call_gemini_pro,
            prompt=user_prompt,
            system_instruction=SYSTEM_PROMPT,
            mountain_name=display_name,
            altitude=req.altitude,
            weather_data=weather_data
        )
        analysis_text = gemini_result.get("text", "")
        verdict = extract_verdict(analysis_text)

        return ViabilityResponse(
            success=True,
            mountain_name=display_name,
            consultation_date=consultation_date_str,
            start_date=start_date_str,
            start_time=start_time_str,
            summit_date=summit_date_str,
            summit_time=summit_time_str,
            end_date=end_date_str,
            end_time=end_time_str,
            target_date=summit_date_str,
            expedition_duration_days=expedition_days,
            expedition_duration_hours=expedition_hours,
            altitude=req.altitude,
            coordinates={"latitude": req.latitude, "longitude": req.longitude},
            weather_context=weather_data,
            analysis_report=analysis_text,
            verdict=verdict,
            model_used=gemini_result.get("model", "gemini-pro"),
            is_simulation=gemini_result.get("is_simulation", False),
            timestamp=datetime.utcnow().isoformat()
        )

    except Exception as exc:
        logger.error(f"Error inesperado procesando la expedición: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno al procesar el análisis de montaña: {str(exc)}"
        )

    except Exception as exc:
        logger.error(f"Error inesperado procesando la expedición: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno al procesar el análisis de montaña: {str(exc)}"
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)

