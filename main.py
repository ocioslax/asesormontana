"""
Servicio Web: Asesor de Seguridad en Alta Montaña
Grupo 1 - Advance Prompt Engineering for Generative IA
Integrantes:
  - Julio Soto Sánchez
  - Miguel Pedreros Olate
  - Francisco Parada
  - Francisco Bahamondes
Coordinadora: Berta Soto Jara | Director Académico: Ahmad Armoush
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
    title="Asesor de Seguridad en Alta Montaña - Grupo 1",
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
    mountain_name: str = Field(..., description="Nombre del cerro, montaña o referencia geográfica", example="Cerro El Plomo")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitud en grados decimales", example=-33.2319)
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitud en grados decimales", example=-70.2172)
    altitude: float = Field(..., ge=0.0, le=9000.0, description="Altitud en m.s.n.m.", example=5424.0)
    target_date: str = Field(..., description="Fecha objetivo del ascenso (YYYY-MM-DD)", example="2026-11-15")
    route: Optional[str] = Field(default="", description="Ruta prevista (opcional)", example="Ruta Normal por La Hoya")
    group_technical_level: Optional[str] = Field(default="", description="Nivel técnico del grupo (opcional)", example="Intermedio con experiencia en cramponaje")

class WeatherSummary(BaseModel):
    source: str
    past_14_days: Dict[str, Any]
    forecast_7_days: Dict[str, Any]
    target_day_overview: Dict[str, Any]

class ViabilityResponse(BaseModel):
    success: bool
    mountain_name: str
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
    """
    # Gradiente térmico aproximado: -6.5°C por cada 1000m
    base_temp = 18.0 - (altitude / 1000.0 * 6.5)
    
    past_dates = [(date.today() - timedelta(days=i)).isoformat() for i in range(14, 0, -1)]
    future_dates = [(date.today() + timedelta(days=i)).isoformat() for i in range(0, 8)]

    # Historial sintético de 14 días
    past_14 = {
        "dates": past_dates,
        "temp_max_c": [round(base_temp + (i % 3) - 2.0, 1) for i in range(14)],
        "temp_min_c": [round(base_temp - 8.0 - (i % 4), 1) for i in range(14)],
        "snowfall_sum_cm": [12.0 if i in (3, 4, 10) else (3.0 if i in (8, 9) else 0.0) for i in range(14)],
        "wind_gusts_max_kmh": [round(35.0 + (i * 3.5 % 45.0), 1) for i in range(14)],
        "dominant_conditions": "Ciclo de nevadas intermitentes con vientos moderados a fuertes en cotas altas."
    }

    # Pronóstico sintético de 7 días
    forecast_7 = {
        "dates": future_dates,
        "temp_max_c": [round(base_temp + 1.0 - (i * 0.5), 1) for i in range(8)],
        "temp_min_c": [round(base_temp - 7.5 - (i * 0.8), 1) for i in range(8)],
        "precipitation_probability_pct": [15, 20, 65, 80, 45, 10, 10, 5],
        "snowfall_sum_cm": [0.0, 1.5, 14.0, 18.0, 4.0, 0.0, 0.0, 0.0],
        "wind_gusts_max_kmh": [28.0, 42.0, 78.0, 85.0, 50.0, 25.0, 20.0, 18.0],
        "trend": "Frente de mal tiempo aproximándose a mitad del período de pronóstico con ráfagas superiores a 70 km/h."
    }

    return {
        "source": "Sintético Calibrado por Altitud (Fallback Offline)",
        "elevation_m": altitude,
        "past_14_days": past_14,
        "forecast_7_days": forecast_7,
        "target_day_overview": {
            "target_date": target_date_str,
            "estimated_summit_temp_c": round(base_temp - 3.0, 1),
            "estimated_wind_speed_kmh": 45.0,
            "freeze_level_m": max(1500.0, round(altitude - 1200.0))
        }
    }

async def fetch_openmeteo_weather(latitude: float, longitude: float, altitude: float, target_date_str: str) -> Dict[str, Any]:
    """
    Consulta la API libre de Open-Meteo para obtener historial de los últimos 14 días
    y el pronóstico de los próximos 7 días con un solo endpoint.
    """
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
        "forecast_days": 8,
        "timezone": "auto"
    }

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                daily = data.get("daily", {})
                dates = daily.get("time", [])
                
                # Dividir en pasado (14 días) y futuro (8 días)
                # El índice 14 corresponde usualmente al día de hoy
                idx_today = min(14, len(dates) // 2) if len(dates) > 14 else 14
                
                past_dates = dates[:idx_today]
                future_dates = dates[idx_today:]
                
                past_14 = {
                    "dates": past_dates,
                    "temp_max_c": daily.get("temperature_2m_max", [])[:idx_today],
                    "temp_min_c": daily.get("temperature_2m_min", [])[:idx_today],
                    "precipitation_sum_mm": daily.get("precipitation_sum", [])[:idx_today],
                    "snowfall_sum_cm": daily.get("snowfall_sum", [])[:idx_today],
                    "wind_gusts_max_kmh": daily.get("wind_gusts_10m_max", [])[:idx_today],
                }
                
                forecast_7 = {
                    "dates": future_dates,
                    "temp_max_c": daily.get("temperature_2m_max", [])[idx_today:],
                    "temp_min_c": daily.get("temperature_2m_min", [])[idx_today:],
                    "precipitation_sum_mm": daily.get("precipitation_sum", [])[idx_today:],
                    "snowfall_sum_cm": daily.get("snowfall_sum", [])[idx_today:],
                    "wind_gusts_max_kmh": daily.get("wind_gusts_10m_max", [])[idx_today:],
                }
                
                logger.info(f"Datos meteorológicos obtenidos exitosamente de Open-Meteo ({latitude}, {longitude})")
                return {
                    "source": "Open-Meteo Live API",
                    "elevation_m": data.get("elevation", altitude),
                    "past_14_days": past_14,
                    "forecast_7_days": forecast_7,
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
        "group": "Grupo 1",
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
        logger.info(f"Iniciando evaluación para: {req.mountain_name} (Alt: {req.altitude}m, Fecha: {req.target_date})")

        # 1. Recopilación de datos meteorológicos (Open-Meteo con fallback automático)
        weather_data = await fetch_openmeteo_weather(
            latitude=req.latitude,
            longitude=req.longitude,
            altitude=req.altitude,
            target_date_str=req.target_date
        )

        # 2. Formulación del Prompt para Gemini
        user_prompt = f"""EVALUACIÓN DE EXPEDICIÓN EN ALTA MONTAÑA

PARÁMETROS DE LA EXPEDICIÓN:
- Cerro / Montaña: {req.mountain_name}
- Coordenadas Geográficas: Latitud {req.latitude}, Longitud {req.longitude}
- Altitud Objetivo: {req.altitude} m.s.n.m.
- Fecha Objetivo del Ascenso: {req.target_date}
- Ruta declarada: {req.route if req.route else 'No especificada por el usuario'}
- Nivel técnico del grupo: {req.group_technical_level if req.group_technical_level else 'No especificado por el usuario'}

CONTEXTO METEOROLÓGICO DISPONIBLE:
Fuente de datos: {weather_data.get('source')}

1. Diagnóstico del clima de las últimas 2 semanas:
{json.dumps(weather_data.get('past_14_days'), indent=2, ensure_ascii=False)}

2. Proyección meteorológica de la semana siguiente:
{json.dumps(weather_data.get('forecast_7_days'), indent=2, ensure_ascii=False)}

Por favor, elabora el informe técnico de seguridad siguiendo estrictamente los 3 apartados indicados en la instrucción del sistema."""

        # 3. Invocación a Gemini Pro
        gemini_result = call_gemini_pro(prompt=user_prompt, system_instruction=SYSTEM_PROMPT)
        analysis_text = gemini_result.get("text", "")
        verdict = extract_verdict(analysis_text)

        return ViabilityResponse(
            success=True,
            mountain_name=req.mountain_name,
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
