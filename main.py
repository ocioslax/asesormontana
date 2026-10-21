"""
Servicio Web: Asesor de Seguridad en Alta Montaña
Sistema de análisis nivometeorológico y viabilidad Go/No Go con Google Gemini Pro
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, date, timedelta

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

def generate_fallback_weather(latitude: float, longitude: float, altitude: float, target_date_str: str) -> Dict[str, Any]:
    """
    Genera un conjunto de datos meteorológicos sintéticos realistas basado en altitud
    en caso de que Open-Meteo no esté disponible o no haya conectividad externa.
    Cubre:
      1. Dos semanas previas a la fecha de consulta.
      2. Pronóstico del tiempo hasta la fecha solicitada.
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
    past_14 = {
        "description": "Diagnóstico del clima de 2 semanas previas a la fecha de consulta",
        "date_range": f"{past_dates[0]} al {past_dates[-1]}",
        "dates": past_dates,
        "temp_max_c": [round(base_temp + (i % 3) - 2.0, 1) for i in range(14)],
        "temp_min_c": [round(base_temp - 8.0 - (i % 4), 1) for i in range(14)],
        "snowfall_sum_cm": [12.0 if i in (3, 4, 10) else (3.0 if i in (8, 9) else 0.0) for i in range(14)],
        "wind_gusts_max_kmh": [round(35.0 + (i * 3.5 % 45.0), 1) for i in range(14)],
        "dominant_conditions": "Ciclo de nevadas intermitentes con vientos moderados a fuertes en cotas altas."
    }

    # 2. Pronóstico del tiempo hasta la fecha solicitada (inclusivo)
    delta_days = (target_d - consultation_date).days
    num_forecast_days = max(1, delta_days + 1)
    future_dates = [(consultation_date + timedelta(days=i)).isoformat() for i in range(0, num_forecast_days)]

    forecast_until_target = {
        "description": f"Pronóstico del tiempo desde la fecha de consulta ({consultation_date}) hasta la fecha solicitada ({target_date_str})",
        "date_range": f"{future_dates[0]} al {future_dates[-1]}",
        "total_days": len(future_dates),
        "dates": future_dates,
        "temp_max_c": [round(base_temp + 1.0 - ((i % 5) * 0.5), 1) for i in range(len(future_dates))],
        "temp_min_c": [round(base_temp - 7.5 - ((i % 5) * 0.8), 1) for i in range(len(future_dates))],
        "precipitation_probability_pct": [min(95, 15 + ((i * 12) % 75)) for i in range(len(future_dates))],
        "snowfall_sum_cm": [round(15.0 if (i % 4 == 2) else (2.0 if i % 3 == 0 else 0.0), 1) for i in range(len(future_dates))],
        "wind_gusts_max_kmh": [round(28.0 + ((i * 7) % 55), 1) for i in range(len(future_dates))],
        "trend": f"Evolución proyectada de temperaturas, manto nival y ráfagas hasta la fecha solicitada ({target_date_str})."
    }

    return {
        "source": "Sintético Calibrado por Altitud (Fallback Offline)",
        "consultation_date": consultation_date.isoformat(),
        "target_date": target_date_str,
        "elevation_m": altitude,
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

async def fetch_openmeteo_weather(latitude: float, longitude: float, altitude: float, target_date_str: str) -> Dict[str, Any]:
    """
    Consulta la API de Open-Meteo para obtener:
      1. Clima de dos semanas previas a la fecha de consulta (past_days=14).
      2. Pronóstico del tiempo hasta la fecha objetivo solicitada.
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
                
                temp_max = list(daily.get("temperature_2m_max", []))
                temp_min = list(daily.get("temperature_2m_min", []))
                precip = list(daily.get("precipitation_sum", []))
                snowfall = list(daily.get("snowfall_sum", []))
                wind_gusts = list(daily.get("wind_gusts_10m_max", []))

                past_14 = {
                    "description": "Diagnóstico del clima de 2 semanas previas a la fecha de consulta",
                    "date_range": f"{past_dates[0]} al {past_dates[-1]}" if past_dates else "14 días previos",
                    "dates": past_dates,
                    "temp_max_c": temp_max[:idx_today],
                    "temp_min_c": temp_min[:idx_today],
                    "precipitation_sum_mm": precip[:idx_today],
                    "snowfall_sum_cm": snowfall[:idx_today],
                    "wind_gusts_max_kmh": wind_gusts[:idx_today],
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

                forecast_until_target = {
                    "description": f"Pronóstico del tiempo desde la fecha de consulta ({consultation_date}) hasta la fecha solicitada ({target_date_str})",
                    "date_range": f"{future_dates[0]} al {future_dates[-1]}" if future_dates else f"Hasta {target_date_str}",
                    "total_days": len(future_dates),
                    "dates": future_dates,
                    "temp_max_c": temp_max[idx_today:idx_today + len(future_dates)],
                    "temp_min_c": temp_min[idx_today:idx_today + len(future_dates)],
                    "precipitation_sum_mm": precip[idx_today:idx_today + len(future_dates)],
                    "snowfall_sum_cm": snowfall[idx_today:idx_today + len(future_dates)],
                    "wind_gusts_max_kmh": wind_gusts[idx_today:idx_today + len(future_dates)],
                }
                
                logger.info(
                    f"Datos meteorológicos obtenidos de Open-Meteo: "
                    f"Historial 14 días ({past_14['date_range']}) | "
                    f"Pronóstico hasta fecha solicitada ({forecast_until_target['date_range']})"
                )
                return {
                    "source": "Open-Meteo Live API",
                    "consultation_date": consultation_date.isoformat(),
                    "target_date": target_date_str,
                    "elevation_m": data.get("elevation", altitude),
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
                return generate_fallback_weather(latitude, longitude, altitude, target_date_str)
    except Exception as exc:
        logger.warning(f"No fue posible conectar con Open-Meteo ({exc}). Usando fallback sintético.")
        return generate_fallback_weather(latitude, longitude, altitude, target_date_str)

def call_gemini_pro(prompt: str, system_instruction: str) -> Dict[str, Any]:
    """
    Envía el prompt al modelo Gemini Pro utilizando el SDK oficial google-generativeai.
    Gestiona ausencia de clave o errores de conexión.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    
    if not api_key:
        logger.warning("GEMINI_API_KEY no encontrada en el entorno. Generando informe experto en modo simulación.")
        return {
            "text": simulate_expert_response(prompt),
            "model": "simulated-gemini-pro (GEMINI_API_KEY no configurada)",
            "is_simulation": True
        }

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        # Probar modelos disponibles: gemini-pro o gemini-1.5-flash / gemini-1.5-pro según soporte del SDK
        model_candidates = ["gemini-pro", "gemini-1.5-flash", "gemini-1.5-pro"]
        last_error = None
        
        for candidate in model_candidates:
            try:
                # Si el SDK soporta system_instruction en GenerativeModel
                try:
                    model = genai.GenerativeModel(
                        model_name=candidate,
                        system_instruction=system_instruction
                    )
                    full_prompt = prompt
                except TypeError:
                    # En versiones previas del SDK, prepender la instrucción del sistema
                    model = genai.GenerativeModel(model_name=candidate)
                    full_prompt = f"INSTRUCCIÓN DEL SISTEMA:\n{system_instruction}\n\n---\nSOLICITUD:\n{prompt}"

                response = model.generate_content(full_prompt)
                if response and response.text:
                    logger.info(f"Respuesta generada exitosamente con el modelo {candidate}")
                    return {
                        "text": response.text,
                        "model": candidate,
                        "is_simulation": False
                    }
            except Exception as e:
                last_error = e
                logger.warning(f"Fallo al invocar modelo '{candidate}': {e}. Probando siguiente candidato si existe...")

        # Si fallaron todos los candidatos de modelo (por ejemplo, cuota excedida o clave inválida)
        raise RuntimeError(f"Fallo en llamadas a Gemini: {last_error}")

    except Exception as err:
        logger.error(f"Error al conectar con la API de Google Gemini: {err}")
        simulated_text = simulate_expert_response(prompt)
        error_note = (
            f"> [!WARNING]\n"
            f"> **Aviso de Integración Gemini:** Ocurrió una incidencia al contactar a Google Gemini ({str(err)}). "
            f"Se muestra a continuación el análisis generado por el motor de contingencia de seguridad en montaña.\n\n"
        )
        return {
            "text": error_note + simulated_text,
            "model": "fallback-simulation",
            "is_simulation": True
        }

def simulate_expert_response(prompt_context: str) -> str:
    """
    Genera un informe nivometeorológico estructurado exactamente en los 3 apartados
    exigidos por el Prompt Maestro cuando la API externa no está disponible.
    """
    return (
        "**1. Estado de la Nieve y Viabilidad del Ascenso:**\n"
        "Durante los últimos 14 días se registraron precipitaciones nivales acumuladas con transporte eólico "
        "significativo en orientaciones Este y Sureste, generando placas de viento reactivas sobre capas de facetas "
        "débiles en cotas superiores a los 3.800 m.s.n.m. En pendientes intermedias (>30°), el manto presenta cohesión "
        "inestable debido a variaciones térmicas diurnas y costras de rehielo quebradizas. La progresión solo es viable "
        "con extremas precauciones y evitando canales cerrados o laderas de sotavento.\n\n"
        "*Equipamiento técnico mínimo requerido:* Piolet de travesía/técnico, crampones de 12 puntas con antibott "
        "ajustados a botas rígidas, casco de montaña, sonda de avalancha de 240 cm, pala de nieve de aluminio, DVA/Arva "
        "(3 antenas) por participante y botiquín de primeros auxilios en hipotermia.\n\n"
        "**2. Nivel de Riesgo General:**\n"
        "Se asigna un **Nivel 3 (Marcado)** en la escala europea EAWS (European Avalanche Warning System). El problema "
        "nivológico principal radica en 'Placas de Viento Recientes' superpuestas sobre estratos facetados sin consolidar. "
        "Factores meteorológicos críticos: ráfagas pronosticadas entre 45 y 75 km/h que pueden provocar viento blanco "
        "(visibilidad inferior a 50 metros), sensación térmica proyectada de hasta -22°C y radiación UV extrema (Índice > 11).\n"
        "Riesgo residual operativo: **Alto**.\n\n"
        "**3. Recomendación Final y Criterio 'Go / No Go':**\n"
        "**[RECOMENDADA CON CONDICIONANTES / RUTA ALTERNATIVA]**\n\n"
        "Se autoriza intento de cumbre únicamente si se selecciona una ruta por arista limpia de acumulaciones de placa, "
        "descartando canales y palas con pendiente superior a 32°. \n"
        "- **Ventana horaria óptima:** Salida de campamento alto entre 03:30 AM y 04:30 AM, aprovechando el rehielo nocturno "
        "para estabilidad de huella.\n"
        "- **Hora límite de retorno categórica (turn-around time):** 12:30 PM (independientemente del punto alcanzado).\n"
        "- **Desencadenantes de aborto inmediato en terreno:** Sonidos de colapso nival ('whoomf'), agrietamiento de la nieve "
        "bajo los pies, ráfagas de viento sostenidas sobre 60 km/h con pérdida de visibilidad, o incremento de temperatura "
        "que ablande el manto a profundidad antes de las 10:00 AM.\n\n"
        "*Nota: Si el usuario no especifica la ruta precisa o el nivel técnico del grupo, se requiere validar de antemano "
        "la autonomía en rescate en avalanchas y progresión en pendientes pronunciadas para una evaluación definitiva.*"
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
            target_date_str=req.target_date
        )

        # 2. Formulación del Prompt para Gemini
        past_info = weather_data.get('past_14_days', {})
        forecast_info = weather_data.get('forecast_until_target') or weather_data.get('forecast_7_days', {})
        consultation_date_str = weather_data.get('consultation_date', str(date.today()))

        user_prompt = f"""EVALUACIÓN DE EXPEDICIÓN EN ALTA MONTAÑA

PARÁMETROS DE LA EXPEDICIÓN:
- Cerro / Montaña: {display_name}
- Coordenadas Geográficas: Latitud {req.latitude}, Longitud {req.longitude}
- Altitud Objetivo: {req.altitude} m.s.n.m.
- Fecha de Consulta: {consultation_date_str}
- Fecha Objetivo del Ascenso Solicitada: {req.target_date}
- Ruta declarada: {req.route if req.route else 'No especificada por el usuario'}
- Nivel técnico de la expedición: {req.group_technical_level if req.group_technical_level else 'No especificado por el usuario'}

CONTEXTO METEOROLÓGICO DISPONIBLE:
Fuente de datos: {weather_data.get('source')}

1. Diagnóstico del clima de las dos semanas previas a la fecha de consulta ({past_info.get('date_range', '14 días previos')}):
{json.dumps(past_info, indent=2, ensure_ascii=False)}

2. Proyección meteorológica desde la fecha de consulta hasta la fecha objetivo solicitada ({forecast_info.get('date_range', f'hasta {req.target_date}')}):
{json.dumps(forecast_info, indent=2, ensure_ascii=False)}

Por favor, elabora el informe técnico de seguridad siguiendo estrictamente los 3 apartados indicados en la instrucción del sistema."""

        # 3. Invocación a Gemini Pro
        gemini_result = call_gemini_pro(prompt=user_prompt, system_instruction=SYSTEM_PROMPT)
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

