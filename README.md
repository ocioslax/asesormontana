# Asesor de Seguridad en Alta Montaña

> **Aplicación Web para Diagnóstico Nivometeorológico y Viabilidad Experta "Go / No Go" con IA**

Proyecto desarrollado para el curso **Advance Prompt Engineering for Generative IA**.

---

## 👥 Información del Proyecto y Equipo

| Rol | Nombre |
| :--- | :--- |
| **Grupo** | **Grupo 1** |
| **Integrantes** | Julio Soto Sánchez<br>Miguel Pedreros Olate<br>Francisco Parada<br>Francisco Bahamondes |
| **Curso** | Advance Prompt Engineering for Generative IA |
| **Coordinadora** | Berta Soto Jara |
| **Director Académico** | Ahmad Armoush |

---

## 🎯 Descripción del Sistema

El **Asesor de Seguridad en Alta Montaña** es una plataforma web completa diseñada para montañistas, expedicionarios y guías de montaña. Recibe parámetros geográficos y temporales de una expedición, recopila automáticamente los registros meteorológicos de las **últimas dos semanas** y el pronóstico de la **semana siguiente**, y procesa esta información a través del modelo **Google Gemini Pro** utilizando técnicas avanzadas de Prompt Engineering y la escala de riesgo de avalanchas **EAWS** (*European Avalanche Warning System*).

---

## 🏗️ Arquitectura y Stack Tecnológico

* **Backend:** Python 3.11+, **FastAPI**, servido asíncronamente con **Uvicorn**.
* **Frontend:** Panel interactivo SPA basado en el estilo visual **Adminator** (Bootstrap 5, Inter font, FontAwesome 6, JavaScript asíncrono con `fetch`).
* **IA / LLM:** Google Gemini (**Gemini Pro**) mediante el SDK `google-generativeai`. Incluye motor de contingencia y simulación experta en caso de ausencia de API key o intermitencia de red.
* **Datos Meteorológicos:** Integración automática con **Open-Meteo API** (historial satelital de 14 días + proyección de 7 días sin costo de API key) con fallback dinámico calibrado por altitud.
* **Contenedores:** Docker (`Dockerfile` optimizado y seguro con usuario no-root) y `docker-compose.yml`.
* **CI/CD:** GitHub Actions (`.github/workflows/main.yml` y `deploy.yml`) para validación de PRs en rama `development` y despliegue a **Vercel** (`vercel.json`).

---

## 📋 Estructura de Entregables

```text
.
├── Grupo 1 - Prompt Maestro.md    # Especificación y requerimientos originales
├── main.py                         # Backend FastAPI + Lógica Gemini Pro + Open-Meteo
├── index.html                      # Frontend interactivo estilo Adminator
├── requirements.txt                # Dependencias Python
├── Dockerfile                      # Imagen Docker optimizada (Python 3.11-slim)
├── docker-compose.yml              # Orquestación local para desarrollo
├── vercel.json                     # Adaptador Serverless para despliegue en Vercel
├── .github/
│   └── workflows/
│       ├── main.yml                # Pipeline CI/CD principal
│       └── deploy.yml              # Pipeline de PR y despliegue continuo
├── .env.example                    # Plantilla de variables de entorno
├── .gitignore                      # Exclusiones de control de versiones
└── README.md                       # Documentación técnica completa
```

---

## 🧠 Prompt Engineering (System Prompt Implementado)

Siguiendo estrictamente las especificaciones del **Paso 4**, el cliente de Gemini Pro inyecta la siguiente instrucción obligatoria:

```text
Actúa como un especialista en seguridad en montaña y gestión del riesgo en alta montaña. Tu objetivo es analizar el estado de una zona o ruta de montaña específica que el usuario te consulte y entregar un informe estructurado de viabilidad y riesgo. El análisis lo debes hacer en consideración del diagnóstico del tiempo de las últimas dos semanas, y la proyección de la semana siguiente (datos provistos en el prompt).

Estructura tu respuesta EXACTAMENTE en los siguientes 3 apartados:
**1. Estado de la Nieve y Viabilidad del Ascenso:** Analiza la estabilidad, cohesión y estructura del manto nivoso (presencia de nieve fresca, placas de viento, capas débiles o terreno glaciar/hielo). Determina si el estado actual permite una progresión segura. Especifica el equipamiento técnico mínimo requerido (piolet, crampones, raquetas, equipo de autorrescate en grietas/avalanchas).
**2. Nivel de Riesgo General:** Asigna un nivel de peligro de avalanchas según la escala EAWS (Nivel 1-Bajo a Nivel 5-Muy Fuerte) e identifica el problema nivológico principal. Evalúa factores meteorológicos críticos (viento blanco, ráfagas, visibilidad, térmica, UV). Define el riesgo residual operativo (Bajo, Moderado, Alto o Extremo).
**3. Recomendación Final y Criterio 'Go / No Go':** Emite una recomendación categórica: [EXPEDICIÓN RECOMENDADA (Go)] / [RECOMENDADA CON CONDICIONANTES / RUTA ALTERNATIVA] / [NO RECOMENDADA / ABORTAR (No Go)]. Establece la ventana horaria óptima y la hora límite de retorno (turn-around time). Enumera los desencadenantes de aborto inmediato en terreno.

*Nota: Si el usuario no especifica la ruta precisa o el nivel técnico del grupo, indica en el informe la necesidad de estos datos para una evaluación definitiva.*
```

---

## 🚀 Guía de Puesta en Marcha

### Opción 1: Con Docker (Recomendada)

1. **Configurar variables de entorno:**
   ```bash
   cp .env.example .env
   # Editar .env y colocar tu GEMINI_API_KEY
   ```

2. **Levantar con Docker Compose:**
   ```bash
   docker-compose up --build -d
   ```

3. **Acceder a la aplicación:**
   Abrir en el navegador [http://localhost:8000](http://localhost:8000).

---

### Opción 2: Ejecución Local en Python

1. **Crear y activar un entorno virtual:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configurar la API Key de Gemini:**
   ```bash
   export GEMINI_API_KEY="tu_clave_gemini_aqui"
   ```

4. **Ejecutar el servidor Uvicorn:**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

5. Abrir [http://localhost:8000](http://localhost:8000) en el navegador.

---

## 🧪 Pruebas Rápidas y Cumbres Pre-configuradas

La interfaz web incluye botones de carga rápida ("Presets") para evaluar cumbres emblemáticas con un solo clic:
* **🇨🇱 Cerro El Plomo (5.424 m):** Los Andes Centrales de Chile.
* **🇦🇷 Aconcagua (6.961 m):** La cumbre más alta de América.
* **🇨🇱 Volcán Villarrica (2.847 m):** Estratovolcán activo en la Araucanía.
* **🇫🇷 Mont Blanc (4.808 m):** Macizo de los Alpes.

---

## 🚢 Despliegue en Vercel y Flujo CI/CD

El repositorio está configurado para:
1. **Pull Requests hacia `development`:** Ejecuta pruebas de validación de sintaxis, modelos Pydantic y construcción de contenedor Docker.
2. **Merge hacia `main`:** Dispara el despliegue automático hacia **Vercel** mediante Vercel CLI utilizando el adaptador de serverless functions definido en `vercel.json`.
