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
SYSTEM_PROMPT = """Actúa como un especialista en seguridad en montaña y gestión del riesgo en alta montaña. Tu objetivo es analizar el estado de una zona o ruta de montaña específica que el usuario te consulte y entregar un informe estructurado de viabilidad y riesgo. El análisis lo debes hacer en consideración del diagnóstico del tiempo de las últimas dos semanas, y la proyección de la semana siguiente (datos provistos en el prompt).

Estructura tu respuesta EXACTAMENTE en los siguientes 3 apartados:
**1. Estado de la Nieve y Viabilidad del Ascenso:** Analiza la estabilidad, cohesión y estructura del manto nivoso (presencia de nieve fresca, placas de viento, capas débiles o terreno glaciar/hielo). Determina si el estado actual permite una progresión segura. Especifica el equipamiento técnico mínimo requerido (piolet, crampones, raquetas, equipo de autorrescate en grietas/avalanchas).
**2. Nivel de Riesgo General:** Asigna un nivel de peligro de avalanchas según la escala EAWS (Nivel 1-Bajo a Nivel 5-Muy Fuerte) e identifica el problema nivológico principal. Evalúa factores meteorológicos críticos (viento blanco, ráfagas, visibilidad, térmica, UV). Define el riesgo residual operativo (Bajo, Moderado, Alto o Extremo).
**3. Recomendación Final y Criterio 'Go / No Go':** Emite una recomendación categórica: [EXPEDICIÓN RECOMENDADA (Go)] / [RECOMENDADA CON CONDICIONANTES / RUTA ALTERNATIVA] / [NO RECOMENDADA / ABORTAR (No Go)]. Establece la ventana horaria óptima y la hora límite de retorno (turn-around time). Enumera los desencadenantes de aborto inmediato en terreno.

*Nota: Si el usuario no especifica la ruta precisa o el nivel técnico del grupo, indica en el informe la necesidad de estos datos para una evaluación definitiva.*"""

# Modelos Pydantic para validación de datos
class ExpeditionRequest(BaseModel):
    mountain_name: Optional[str] = Field(default="", description="Nombre del cerro, montaña o referencia geográfica (opcional si se selecciona en mapa)", example="Cerro El Plomo")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitud en grados decimales", example=-33.2319)
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitud en grados decimales", example=-70.2172)
    altitude: float = Field(..., ge=0.0, le=9000.0, description="Altitud en m.s.n.m.", example=5424.0)
    target_date: str = Field(..., description="Fecha objetivo del ascenso (YYYY-MM-DD)", example="2026-11-15")
    route: Optional[str] = Field(default="", description="Ruta prevista (opcional)", example="Ruta Normal por La Hoya")
    group_technical_level: Optional[str] = Field(default="", description="Nivel técnico de la cordada (opcional)", example="Intermedio con experiencia en cramponaje")

class WeatherSummary(BaseModel):
    source: str
    consultation_date: str
    target_date: str
    zona_consultada: Optional[Dict[str, Any]] = None
    sumas_y_metricas_zona: Optional[Dict[str, Any]] = None
    past_14_days: Dict[str, Any]
    forecast_until_target: Dict[str, Any]
    forecast_7_days: Optional[Dict[str, Any]] = None  # Retrocompatibilidad
    target_day_overview: Dict[str, Any]

class ViabilityResponse(BaseModel):
    success: bool
    mountain_name: str
    consultation_date: Optional[str] = None
    target_date: str
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
    target_date_str: str,
    mountain_name: str = "",
    route: str = ""
) -> Dict[str, Any]:
    """
    Genera un conjunto de datos meteorológicos sintéticos realistas basado en altitud
    en caso de que Open-Meteo no esté disponible o no haya conectividad externa.
    Cubre:
      1. Datos de la zona consultada y métricas agregadas/sumas.
      2. Dos semanas previas a la fecha de consulta.
      3. Pronóstico del tiempo hasta la fecha solicitada.
    """
    consultation_date = date.today()
    try:
        target_d = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        target_d = consultation_date + timedelta(days=7)

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

    # 2. Pronóstico del tiempo hasta la fecha solicitada (inclusivo)
    delta_days = (target_d - consultation_date).days
    num_forecast_days = max(1, delta_days + 1)
    future_dates = [(consultation_date + timedelta(days=i)).isoformat() for i in range(0, num_forecast_days)]

    fut_snow = [round(15.0 if (i % 4 == 2) else (2.0 if i % 3 == 0 else 0.0), 1) for i in range(len(future_dates))]
    fut_precip = [round(22.0 if (i % 4 == 2) else (3.5 if i % 3 == 0 else 0.0), 1) for i in range(len(future_dates))]
    fut_tmax = [round(base_temp + 1.0 - ((i % 5) * 0.5), 1) for i in range(len(future_dates))]
    fut_tmin = [round(base_temp - 7.5 - ((i % 5) * 0.8), 1) for i in range(len(future_dates))]
    fut_wind = [round(28.0 + ((i * 7) % 55), 1) for i in range(len(future_dates))]

    forecast_until_target = {
        "description": f"Pronóstico del tiempo desde la fecha de consulta ({consultation_date}) hasta la fecha solicitada ({target_date_str})",
        "date_range": f"{future_dates[0]} al {future_dates[-1]}",
        "total_days": len(future_dates),
        "dates": future_dates,
        "temp_max_c": fut_tmax,
        "temp_min_c": fut_tmin,
        "precipitation_probability_pct": [min(95, 15 + ((i * 12) % 75)) for i in range(len(future_dates))],
        "precipitation_sum_mm": fut_precip,
        "snowfall_sum_cm": fut_snow,
        "wind_gusts_max_kmh": fut_wind,
        "trend": f"Evolución proyectada de temperaturas, manto nival y ráfagas hasta la fecha solicitada ({target_date_str})."
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
        "fecha_objetivo_expedicion": target_date_str,
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
        "nieve_proyectada_hasta_objetivo_cm": round(sum(fut_snow), 1),
        "precipitacion_proyectada_hasta_objetivo_mm": round(sum(fut_precip), 1),
        "nieve_total_periodo_analizado_cm": round(sum(past_snow + fut_snow), 1),
        "precipitacion_total_periodo_analizado_mm": round(sum(past_precip + fut_precip), 1),
        "temperatura_minima_extrema_c": min(past_tmin + fut_tmin),
        "temperatura_maxima_extrema_c": max(past_tmax + fut_tmax),
        "rafaga_viento_maxima_esperada_kmh": max(past_wind + fut_wind)
    }

    return {
        "source": "Sintético Calibrado por Altitud (Fallback Offline)",
        "consultation_date": consultation_date.isoformat(),
        "target_date": target_date_str,
        "elevation_m": altitude,
        "zona_consultada": zona_consultada,
        "sumas_y_metricas_zona": sumas_y_metricas_zona,
        "past_14_days": past_14,
        "forecast_until_target": forecast_until_target,
        "forecast_7_days": forecast_until_target,  # Compatibilidad
        "target_day_overview": {
            "target_date": target_date_str,
            "estimated_summit_temp_c": round(base_temp - 3.0, 1),
            "estimated_wind_speed_kmh": 45.0,
            "freeze_level_m": max(1500.0, round(altitude - 1200.0))
        }
    }

async def fetch_openmeteo_weather(
    latitude: float,
    longitude: float,
    altitude: float,
    target_date_str: str,
    mountain_name: str = "",
    route: str = ""
) -> Dict[str, Any]:
    """
    Consulta la API de Open-Meteo para obtener:
      1. Datos de la zona consultada y métricas agregadas/sumas.
      2. Clima de dos semanas previas a la fecha de consulta (past_days=14).
      3. Pronóstico del tiempo hasta la fecha objetivo solicitada.
    """
    consultation_date = date.today()
    try:
        target_d = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        target_d = consultation_date + timedelta(days=7)

    delta_days = (target_d - consultation_date).days
    # Días requeridos desde hoy hasta la fecha objetivo (inclusive)
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

                # Si la fecha solicitada excede el límite directo de 16 días de Open-Meteo,
                # se proyectan tendencialmente los días restantes hasta la fecha objetivo
                if requested_forecast_days > len(future_dates) and future_dates:
                    last_date_obj = datetime.strptime(future_dates[-1], "%Y-%m-%d").date()
                    extra_days = (target_d - last_date_obj).days
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
                    "description": f"Pronóstico del tiempo desde la fecha de consulta ({consultation_date}) hasta la fecha solicitada ({target_date_str})",
                    "date_range": f"{future_dates[0]} al {future_dates[-1]}" if future_dates else f"Hasta {target_date_str}",
                    "total_days": len(future_dates),
                    "dates": future_dates,
                    "temp_max_c": fut_tmax,
                    "temp_min_c": fut_tmin,
                    "precipitation_sum_mm": fut_precip,
                    "snowfall_sum_cm": fut_snow,
                    "wind_gusts_max_kmh": fut_wind,
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
                    "fecha_objetivo_expedicion": target_date_str,
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
                    "nieve_proyectada_hasta_objetivo_cm": round(sum(fut_snow), 1),
                    "precipitacion_proyectada_hasta_objetivo_mm": round(sum(fut_precip), 1),
                    "nieve_total_periodo_analizado_cm": round(sum(past_snow + fut_snow), 1),
                    "precipitacion_total_periodo_analizado_mm": round(sum(past_precip + fut_precip), 1),
                    "temperatura_minima_extrema_c": min(all_tmin) if all_tmin else None,
                    "temperatura_maxima_extrema_c": max(all_tmax) if all_tmax else None,
                    "rafaga_viento_maxima_esperada_kmh": max(all_wind) if all_wind else None
                }
                
                logger.info(
                    f"Datos meteorológicos obtenidos de Open-Meteo para {zona_consultada['nombre_referencia']}: "
                    f"Historial ({past_14['date_range']}) | Pronóstico ({forecast_until_target['date_range']})"
                )
                return {
                    "source": "Open-Meteo Live API",
                    "consultation_date": consultation_date.isoformat(),
                    "target_date": target_date_str,
                    "elevation_m": data.get("elevation", altitude),
                    "zona_consultada": zona_consultada,
                    "sumas_y_metricas_zona": sumas_y_metricas_zona,
                    "past_14_days": past_14,
                    "forecast_until_target": forecast_until_target,
                    "forecast_7_days": forecast_until_target,  # Compatibilidad
                    "target_day_overview": {
                        "target_date": target_date_str,
                        "elevation_used": data.get("elevation", altitude)
                    }
                }
            else:
                logger.warning(f"Open-Meteo devolvió código {response.status_code}. Usando fallback sintético.")
                return generate_fallback_weather(latitude, longitude, altitude, target_date_str, mountain_name, route)
    except Exception as exc:
        logger.warning(f"No fue posible conectar con Open-Meteo ({exc}). Usando fallback sintético.")
        return generate_fallback_weather(latitude, longitude, altitude, target_date_str, mountain_name, route)

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
    snow_sum = metrics.get("nieve_total_periodo_analizado_cm", 25.0)
    wind_max = metrics.get("rafaga_viento_maxima_esperada_kmh", 55.0)
    t_min = metrics.get("temperatura_minima_extrema_c", -15.0)

    # Determinar veredicto y nivel EAWS basado en métricas reales de la zona
    if wind_max > 70.0 or snow_sum > 60.0 or altitude > 6000:
        verdict = "[NO RECOMENDADA / ABORTAR (No Go)]"
        risk_level = "Nivel 4 (Fuerte)"
        op_risk = "Extremo"
        snow_state = (
            f"En {target_name} ({altitude} m.s.n.m.), el manto nivoso presenta alta inestabilidad debido a acumulaciones "
            f"recientes de {snow_sum} cm de nieve con severo transporte eólico. Se observan placas de viento reactivas en pendientes "
            f"superiores a 28° y riesgo inminente de desencadenamiento espontáneo en laderas de sotavento."
        )
    elif wind_max > 45.0 or snow_sum > 20.0 or altitude > 4000:
        verdict = "[RECOMENDADA CON CONDICIONANTES / RUTA ALTERNATIVA]"
        risk_level = "Nivel 3 (Marcado)"
        op_risk = "Alto"
        snow_state = (
            f"Para {target_name} ({altitude} m.s.n.m.), el manto presenta cohesión variable con costras de rehielo matinales "
            f"y presencia de placas de viento en aristas expuestas. Con {snow_sum} cm acumulados y ráfagas estimadas de {wind_max} km/h, "
            f"la progresión solo es viable evitando canales cerrados y transitando estrictamente por laderas protegidas o aristas de roca firme."
        )
    else:
        verdict = "[EXPEDICIÓN RECOMENDADA (Go)]"
        risk_level = "Nivel 2 (Limitado)"
        op_risk = "Moderado"
        snow_state = (
            f"Las condiciones en {target_name} ({altitude} m.s.n.m.) muestran un manto nivoso en proceso de consolidación favorable. "
            f"Con ráfagas contenidas ({wind_max} km/h) y temperaturas mínimas de {t_min}°C, el manto nivoso permite una progresión "
            f"firme durante la ventana matinal aprovechando el buen rehielo nocturno."
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
        f"sensación térmica extrema de {t_min - 8.0:.1f}°C y visibilidad reducida en cotas altas.\n"
        f"Riesgo residual operativo: **{op_risk}**.\n\n"
        f"**3. Recomendación Final y Criterio 'Go / No Go':**\n"
        f"**{verdict}**\n\n"
        f"- **Zona evaluada:** {target_name} ({altitude} m.s.n.m.)\n"
        f"- **Ventana horaria óptima:** Salida recomendada a las 04:00 AM para aprovechar la máxima estabilidad de rehielo del manto.\n"
        f"- **Hora límite de retorno (turn-around time):** 12:30 PM sin excepción.\n"
        f"- **Desencadenantes de aborto inmediato en terreno:** Ráfagas sostenidas sobre 60 km/h, desprendimientos o colapsos tipo 'whoomf', "
        f"pérdida de visibilidad por niebla/viento blanco o reblandecimiento acelerado de la nieve antes de mediodía.\n\n"
        f"*Nota: Si el usuario no especifica la ruta precisa o el nivel técnico de la cordada, se requiere validar de antemano "
        f"la experiencia técnica del grupo para una evaluación definitiva.*"
    )

def extract_verdict(analysis_text: str) -> str:
    """Extrae la clasificación del veredicto a partir del informe generado."""
    upper = analysis_text.upper()
    if "[EXPEDICIÓN RECOMENDADA (GO)]" in upper or "EXPEDICIÓN RECOMENDADA" in upper:
        return "GO"
    elif "[NO RECOMENDADA / ABORTAR" in upper or "ABORTAR (NO GO)" in upper or "NO GO" in upper:
        return "NO_GO"
    elif "RECOMENDADA CON CONDICIONANTES" in upper or "CONDICIONANTES" in upper:
        return "CONDITIONAL"
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
    recopila el contexto meteorológico (últimas 2 semanas y próxima semana),
    y genera el informe de viabilidad técnica mediante Gemini Pro.
    """
    try:
        # Si el usuario no especificó nombre o usó el mapa, usar coordenadas como referencia
        display_name = req.mountain_name.strip() if (req.mountain_name and req.mountain_name.strip()) else f"Zona Coordenadas ({req.latitude:.4f}, {req.longitude:.4f})"
        
        logger.info(f"Iniciando evaluación para: {display_name} (Alt: {req.altitude}m, Fecha: {req.target_date})")

        # 1. Recopilación de datos meteorológicos (Open-Meteo con fallback automático)
        weather_data = await fetch_openmeteo_weather(
            latitude=req.latitude,
            longitude=req.longitude,
            altitude=req.altitude,
            target_date_str=req.target_date,
            mountain_name=display_name,
            route=req.route or ""
        )

        # 2. Formulación del Prompt para Gemini
        past_info = weather_data.get('past_14_days', {})
        forecast_info = weather_data.get('forecast_until_target') or weather_data.get('forecast_7_days', {})
        consultation_date_str = weather_data.get('consultation_date', str(date.today()))

        user_prompt = f"""EVALUACIÓN DE EXPEDICIÓN EN ALTA MONTAÑA

PARÁMETROS DE LA EXPEDICIÓN Y ZONA CONSULTADA:
{json.dumps(weather_data.get('zona_consultada', {}), indent=2, ensure_ascii=False)}

MÉTRICAS Y SUMAS ACUMULADAS DE LA ZONA:
{json.dumps(weather_data.get('sumas_y_metricas_zona', {}), indent=2, ensure_ascii=False)}

CONTEXTO METEOROLÓGICO DETALLADO:
Fuente de datos: {weather_data.get('source')}

1. Diagnóstico del clima de las dos semanas previas a la fecha de consulta ({past_info.get('date_range', '14 días previos')}):
{json.dumps(past_info, indent=2, ensure_ascii=False)}

2. Proyección meteorológica desde la fecha de consulta hasta la fecha objetivo solicitada ({forecast_info.get('date_range', f'hasta {req.target_date}')}):
{json.dumps(forecast_info, indent=2, ensure_ascii=False)}

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
            target_date=req.target_date,
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

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)

