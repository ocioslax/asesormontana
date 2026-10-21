Integrantes
    Julio Soto Sánchez
	Miguel Pedreros Olate
	Francisco Parada
	Francisco Bahamondes
Grupo	1
Curso	Advance Prompt Engineering for Generative IA
Coordinadora	Berta Soto Jara
Director Academico	Ahmad Armoush

# Prompt Técnico para Desarrollo de Servicio Web: Asesor de Seguridad en Alta Montaña

**Instrucción para el Agente de IA:**
Actúa como un Tech Lead y Senior Full-Stack Developer. Tu objetivo es desarrollar, configurar y preparar para despliegue una aplicación web completa siguiendo estrictamente los 6 pasos descritos a continuación.

## PASO 1: Contexto y Objetivos del Proyecto

Desarrollar una aplicación web orientada a la seguridad en montaña. El sistema debe recibir parámetros geográficos y temporales de un usuario, recopilar datos meteorológicos históricos y futuros, y procesar esta información a través del modelo Gemini Pro para emitir un informe experto de viabilidad ("Go / No Go") para expediciones de alta montaña.

## PASO 2: Arquitectura y Stack Tecnológico

Debes utilizar el siguiente stack técnico:

* **Backend:** Python con FastAPI (servido a través de Uvicorn).

* **Frontend:** Plantilla HTML/CSS/JS basada en el estilo visual **Adminator** (dashboard administrativo). Debe comunicarse asíncronamente con el backend.

* **IA / LLM:** Integración nativa con la API de Google Gemini (modelo `gemini-pro`).

* **Contenedores:** Docker (Dockerfile y `docker-compose.yml` para desarrollo local).

* **CI/CD & Control de Versiones:** Git/GitHub Actions, orientado a un flujo de aprobación de PR, construcción de imagen y despliegue final en Vercel.

## PASO 3: Requisitos Funcionales y Lógica de Negocio

El sistema debe implementar la siguiente funcionalidad:

1. **Formulario de Entrada:** El Frontend debe capturar:

   * Nombre del cerro/montaña o referencia geográfica.

   * Coordenadas (Latitud y Longitud) y Altitud.

   * Fecha objetivo para el ascenso.

2. **Recopilación de Datos Meteorológicos:** El backend debe incluir lógica (o mocks de servicios como OpenMeteo) para obtener:

   * Diagnóstico del clima de las **últimas dos semanas**.

   * Proyección meteorológica de la **semana siguiente** a la consulta.

3. **Procesamiento:** El backend unificará la data de entrada y el contexto meteorológico para enviarlo al motor de LLM.

## PASO 4: Integración de IA (Prompt Engineering)

Configura el cliente de Gemini Pro para inyectar obligatoriamente el siguiente `System Prompt` (instrucción base para el modelo) junto con el contexto meteorológico recopilado:

> "Actúa como un especialista en seguridad en montaña y gestión del riesgo en alta montaña. Tu objetivo es analizar el estado de una zona o ruta de montaña específica que el usuario te consulte y entregar un informe estructurado de viabilidad y riesgo. El análisis lo debes hacer en consideración del diagnóstico del tiempo de las últimas dos semanas, y la proyección de la semana siguiente (datos provistos en el prompt).
>
> Estructura tu respuesta EXACTAMENTE en los siguientes 3 apartados:
> **1. Estado de la Nieve y Viabilidad del Ascenso:** Analiza la estabilidad, cohesión y estructura del manto nivoso (presencia de nieve fresca, placas de viento, capas débiles o terreno glaciar/hielo). Determina si el estado actual permite una progresión segura. Especifica el equipamiento técnico mínimo requerido (piolet, crampones, raquetas, equipo de autorrescate en grietas/avalanchas).
> **2. Nivel de Riesgo General:** Asigna un nivel de peligro de avalanchas según la escala EAWS (Nivel 1-Bajo a Nivel 5-Muy Fuerte) e identifica el problema nivológico principal. Evalúa factores meteorológicos críticos (viento blanco, ráfagas, visibilidad, térmica, UV). Define el riesgo residual operativo (Bajo, Moderado, Alto o Extremo).
> **3. Recomendación Final y Criterio 'Go / No Go':** Emite una recomendación categórica: \[EXPEDICIÓN RECOMENDADA (Go)\] / \[RECOMENDADA CON CONDICIONANTES / RUTA ALTERNATIVA\] / \[NO RECOMENDADA / ABORTAR (No Go)\]. Establece la ventana horaria óptima y la hora límite de retorno (turn-around time). Enumera los desencadenantes de aborto inmediato en terreno.
>
> *Nota: Si el usuario no especifica la ruta precisa o el nivel técnico del grupo, indica en el informe la necesidad de estos datos para una evaluación definitiva.*"

## PASO 5: Flujo DevOps (Docker, GitHub y Vercel)

Genera los archivos de configuración para el siguiente ciclo de vida:

1. **Dockerización:** Crea un `Dockerfile` optimizado para Python/Uvicorn que exponga el puerto adecuado.

2. **GitHub Actions (CI/CD):** Crea un archivo `.github/workflows/deploy.yml` que:

   * Se ejecute únicamente en la rama `development` mediante Pull Requests.

   * Requiera aprobación (simulada vía rules de rama) del dueño del repositorio antes de hacer merge a `main`.

   * Una vez aprobado, construya la imagen Docker.

   * Implemente los comandos o el Vercel CLI necesario para desplegar el servicio en Vercel (considerando la adaptación de FastAPI usando `vercel.json`).

## PASO 6: Restricciones y Entregables (Output Esperado)

* **No omitas código:** Genera los archivos completos, no uses "placeholder" o comentarios como `// resto del código aquí`.

* **Archivos solicitados:**

  1. `main.py` (FastAPI backend + Lógica Gemini)

  2. `index.html` (Frontend integrado con estilos Adminator)

  3. `requirements.txt`

  4. `Dockerfile`

  5. `vercel.json` (Para despliegue serverless de la API en Vercel)

  6. `.github/workflows/main.yml` (Pipeline de CI/CD)

* Asegura el manejo de errores (ej. si la API key de Gemini es inválida o falla la conexión).
