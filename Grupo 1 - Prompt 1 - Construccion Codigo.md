Actúa como un Tech Lead y Senior Full-Stack Developer. Tu objetivo es reconstruir desde cero, configurar y verificar localmente una aplicación web completa llamada **"Asesor de Seguridad en Alta Montaña"**, siguiendo estrictamente las especificaciones técnicas descritas a continuación.

## 1. Contexto y Objetivo del Proyecto
Desarrollar una aplicación web orientada a la seguridad y gestión del riesgo en alta montaña. El sistema debe capturar parámetros geográficos, topográficos y cronológicos de una expedición, recopilar datos meteorológicos históricos y futuros reales, y procesarlos con Google Gemini para emitir un informe experto de viabilidad ("Go / No Go").

## 2. Arquitectura y Stack Tecnológico
* **Backend:** Python 3.11+ con **FastAPI**, servido con **Uvicorn**, validación con **Pydantic**, cliente HTTP asíncrono **httpx** y **python-dotenv**.
* **Frontend:** Dos vistas HTML/CSS/JS independientes con estética visual **Adminator** (dashboard administrativo), usando **Bootstrap 5**, **Font Awesome**, **Leaflet** (mapas OpenStreetMap) y **Chart.js** para gráficos meteorológicos:
  * `index.html` (ruta `/`): Dashboard principal de consulta rápida y análisis de viabilidad.
  * `planificador.html` (ruta `/planificador`): Planificador detallado de ascenso, itinerario y gestión del riesgo.
* **IA / LLM:** Integración nativa con el SDK `google-generativeai`, con lista de modelos candidatos (`gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-pro-latest`, `gemini-flash-latest`, `gemini-pro`) + auto-descubrimiento vía `list_models()`, y un motor de contingencia/simulación (`simulate_expert_response`) si `GEMINI_API_KEY` no está configurada o falla la API.
* **Datos Geográficos y Meteorológicos:**
  * Geocodificación (`/api/geocode?q=...`): OpenStreetMap **Nominatim** + elevación desde **Open-Meteo Elevation API**, con fallback a **Open-Meteo Geocoding**.
  * Meteorología: **Open-Meteo** para obtener el diagnóstico histórico de las **últimas 2 semanas** y la proyección para la **ventana completa de la expedición** (con fallback sintético si falla la conexión).
* **Contenedores:** `Dockerfile` optimizado para Google Cloud Run (`python:3.11-slim`, usuario no privilegiado `appuser`, puerto dinámico `${PORT:-8080}`), `docker-compose.yml` (puerto `8000` y healthcheck a `/api/health`) y `Procfile`.

## 3. Requisitos Funcionales y Endpoints
Implementa en `main.py` los siguientes endpoints y lógica:
1. `GET /` -> Sirve `index.html`.
2. `GET /planificador` -> Sirve `planificador.html`.
3. `GET /api/health` -> Retorna estado del servicio y si `GEMINI_API_KEY` está configurada.
4. `GET /api/geocode` -> Busca cumbres/zonas por nombre y retorna coordenadas y altitud.
5. `POST /api/analyze` -> Recibe `ExpeditionRequest` (`mountain_name`, `latitude`, `longitude`, `altitude`, `start_date`, `start_time`, `summit_date`, `summit_time`, `end_date`, `end_time`, `route`, `group_technical_level`), normaliza el cronograma, consulta Open-Meteo, construye el contexto y llama a Gemini retornando `ViabilityResponse` con el informe y el veredicto (`GO`, `CONDITIONAL`, `NO_GO`).

## 4. Prompt Engineering (System Prompt Obligatorio)
Configura el cliente de Gemini para inyectar obligatoriamente el siguiente `SYSTEM_PROMPT`:

> "Actúa como un especialista en seguridad en montaña y gestión del riesgo en alta montaña. Tu objetivo es analizar el estado de una zona o ruta de montaña específica que el usuario te consulte y entregar un informe estructurado de viabilidad y riesgo. El análisis lo debes hacer en consideración del diagnóstico del tiempo de las últimas dos semanas, y la proyección de la ventana completa de la expedición solicitada (fechas y horarios de inicio, día y hora de ataque a cumbre, y fecha y hora de término provistos en el prompt).
>
> Estructura tu respuesta EXACTAMENTE en los siguientes 3 apartados:
> **1. Estado de la Nieve y Viabilidad del Ascenso:** Analiza la estabilidad, cohesión y estructura del manto nivoso (presencia de nieve fresca, placas de viento, capas débiles o terreno glaciar/hielo) a lo largo de las fechas de la expedición y de manera específica durante el día y hora estimada de cumbre. Considera el ciclo diurno térmico (rehielo nocturno/matinal vs radiación solar y fusión de tarde). Determina si el estado actual y su evolución permiten una progresión segura. Especifica el equipamiento técnico mínimo requerido (piolet, crampones, raquetas, equipo de autorrescate en grietas/avalanchas).
> **2. Nivel de Riesgo General:** Asigna un nivel de peligro de avalanchas según la escala EAWS (Nivel 1-Bajo a Nivel 5-Muy Fuerte) e identifica el problema nivológico principal. Evalúa factores meteorológicos críticos en la cota de cumbre para la fecha y hora seleccionadas (sensación térmica por viento/wind chill, ráfagas, visibilidad, tormenta, UV). Define el riesgo residual operativo (Bajo, Moderado, Alto o Extremo).
> **3. Recomendación Final y Criterio 'Go / No Go':** Emite una recomendación categórica: [EXPEDICIÓN RECOMENDADA (Go)] / [RECOMENDADA CON CONDICIONANTES / RUTA ALTERNATIVA] / [NO RECOMENDADA / ABORTAR (No Go)]. Valida y califica explícitamente el cronograma operativo propuesto: hora de salida, fecha y hora de cumbre, y hora de retorno. Confirma si el horario en cumbre es seguro o si debe ajustarse (hora límite estricta de cumbre y turn-around time para evitar la pérdida de rehielo, caída de piedras o la noche en el descenso). Enumera los desencadenantes de aborto inmediato en terreno.
>
> *Nota: Si el usuario no especifica la ruta precisa o el nivel técnico del grupo, indica en el informe la necesidad de estos datos para una evaluación definitiva.*"

## 5. Entregables y Restricciones
* **No omitas código:** Genera todos los archivos completos, sin placeholders ni comentarios tipo `// resto del código aquí`.
* **Archivos requeridos:**
  1. `main.py`
  2. `index.html`
  3. `planificador.html`
  4. `requirements.txt`
  5. `Dockerfile`
  6. `docker-compose.yml`
  7. `Procfile`
  8. `.env.example` (con `GEMINI_API_KEY=` y `PORT=8080`, nunca subas secretos reales)
  9. `.gitignore` y `.dockerignore` (excluyendo `.env`, `__pycache__/`, `.venv/`)
  10. `README.md` con instrucciones de ejecución local y despliegue.
* **Verificación obligatoria antes de terminar:** Instala dependencias en un entorno virtual o prueba levantar el servidor con Uvicorn y verifica con `curl` que `/api/health`, `/` y `/planificador` respondan HTTP 200.