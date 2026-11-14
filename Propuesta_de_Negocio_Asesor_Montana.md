# Propuesta de Negocio y Modelo SaaS: Asesor de Seguridad en Alta Montaña

**Stack Tecnológico:** FastAPI · Google Gemini · Open-Meteo · OpenStreetMap · Docker / Google Cloud Run  
**Fecha:** Noviembre 2026  

---

## 1. Resumen Ejecutivo y Problema a Resolver

La planificación de ascensos en alta montaña enfrenta hoy una alta fragmentación de información: los montañistas, guías y organismos de emergencia deben cruzar manualmente pronósticos meteorológicos, historial de nevadas, radiación solar, viento en altura y ventanas horarias de ataque a cumbre. Una mala interpretación del ciclo térmico o de las placas de viento eleva drásticamente el riesgo de avalanchas, extravíos y rescates de alto costo.

**Asesor de Seguridad en Alta Montaña** automatiza este proceso en segundos: combina datos satelitales y topográficos reales (**OpenStreetMap + Open-Meteo**) con un motor experto basado en **Google Gemini** para entregar un informe estandarizado en 3 apartados:
1. **Estado de la Nieve y Viabilidad del Ascenso**
2. **Nivel de Riesgo General (Escala EAWS 1–5)**
3. **Recomendación Final y Criterio *Go / No Go*** (incluyendo *turn-around time* y desencadenantes de aborto)

### Capacidades Tecnológicas Base
* **Backend FastAPI (`src/main.py`):** Endpoints `/api/geocode`, `/api/analyze` y `/api/health`.
* **Frontend Dual:** Dashboard rápido (`/`, `src/index.html`) y Planificador cronológico (`/planificador`, `src/planificador.html`) con mapas Leaflet y gráficos Chart.js.
* **IA Estructurada y Validada:** Prompts externalizados en `src/prompts/*.md` y suite de pruebas Golden Set en `src/test/`.
* **Resiliencia y Control de Costos (`GeminiQuotaGuard`):** Control RPM/RPD, tope de tokens, caché TTL de 15 min y motor de contingencia determinista 24/7 ante fallas o límites de API.
* **Cloud-Native:** Contenedor Docker optimizado para escalar en Google Cloud Run (`PORT=8080`).

---

## 2. Segmentos de Clientes

1. **Personas Naturales (B2C):** Montañistas, andinistas, escaladores, esquiadores de travesía y senderistas de alta ruta.
   * **Necesidad:** Validación rápida y confiable antes de salir al cerro.
   * **Valor:** Reducción de incertidumbre y definición clara de hora límite de retorno.
2. **Empresas (B2B):** Agencias de turismo aventura, guías certificados, aseguradoras y faenas mineras/energéticas en cordillera.
   * **Necesidad:** Respaldo documental técnico, gestión de múltiples salidas e integración vía API.
   * **Valor:** Menor siniestralidad, estandarización operativa y trazabilidad.
3. **Gobiernos e Instituciones Públicas (B2G):** Servicios de protección civil (ej. SENAPRED), cuerpos de Socorro Andino, parques nacionales y unidades fronterizas.
   * **Necesidad:** Monitoreo territorial preventivo, alertas tempranas y soberanía de datos.
   * **Valor:** Reducción de rescates evitables y optimización de recursos públicos.

---

## 3. Modelo de Suscripción y Estructura de Precios

El modelo combina una estrategia **Freemium** para impulsar la adopción masiva en la comunidad de montaña, con escalamiento por volumen de solicitudes (`POST /api/analyze`) y funcionalidades empresariales/institucionales **a partir de la solicitud número 11**.

| Plan / Tier | Segmento | Solicitudes Incluidas | Precio | Funcionalidades y SLA |
| :--- | :--- | :--- | :--- | :--- |
| **FREE / Explorer** | Personas Naturales | **0 a 10 / mes** *(máx. 2/día)* | **USD \$0** (Gratuito) | Dashboard + Planificador, clima Open-Meteo (14 días + ventana), informe IA 3 apartados (modelos Flash + caché TTL). |
| **PRO / Andinista** | Personas Naturales y Guías | **11 a 150 / mes** *(excedente: USD \$0.10/req)* | **USD \$12 / mes** *(o USD \$115/año)* | Sin límite diario estricto, exportación PDF del informe, historial de expediciones (90 días) y alertas de cambio climático pre-cumbre. |
| **BUSINESS / Operador** | Empresas y Faenas | **151 a 1.500 / mes** *(excedente: USD \$0.06/req)* | **USD \$79 / mes** *(hasta 10 usuarios)* | Acceso completo a API REST, modelos Gemini Pro para rutas complejas, bitácora auditada para seguros/prevención de riesgos, SLA 99.5%. |
| **GOBIERNO / Institucional** | Gobiernos y Parques | **5.000+ / mes** *(volumen a medida)* | **Desde USD \$650 / mes** *(contrato anual)* | Despliegue dedicado (Cloud Run / VPC privada), tablero multi-región, integración con alertas tempranas, trazabilidad legal y SLA 99.9%. |

### Enfoque específico para Gobiernos e Instituciones Públicas (B2G)
A diferencia de los planes comerciales estándar, los contratos gubernamentales operan bajo **licenciamiento anual o convenio marco** con:
* **Infraestructura aislada y soberanía de datos:** Despliegue *single-tenant* sin retención de consultas operativas.
* **Monitoreo preventivo masivo:** Supervisión simultánea de múltiples pasos fronterizos, parques nacionales y cumbres.
* **Integración directa:** Conexión vía webhooks/API con centros de alerta temprana y cuerpos de rescate.
* **Soporte técnico dedicado y capacitación:** Acompañamiento operativo para guardaparques y equipos de emergencia.

---

## 4. Economía Unitaria y Viabilidad Financiera

* **Costo marginal ultrabajo:** Al priorizar `gemini-2.5-flash`, limitar la salida a `2.048 tokens` y reutilizar resultados idénticos mediante caché TTL de 15 minutos, el costo de cómputo e IA por solicitud se mantiene en fracciones de centavo, permitiendo financiar el **Tier Gratuito (10 solicitudes/mes)** como canal de adquisición.
* **Datos meteorológicos sin costo variable inicial:** El uso de Open-Meteo y OpenStreetMap Nominatim elimina costos fijos elevados en etapas tempranas, con opción de sumar estaciones nivológicas privadas en los tiers B2B/B2G.
* **Margen proyectado:** Margen bruto superior al **75%** en planes Pro y Business gracias a la optimización de prompts y control de cuotas.

---

## 5. Hoja de Ruta de Implementación

| Fase | Horizonte | Hitos Clave |
| :--- | :--- | :--- |
| **Fase 1: Lanzamiento** | Mes 1 – 2 | Autenticación de usuarios (OAuth/JWT), contador de solicitudes por cuenta (10 gratis/mes), pasarela de pagos (Stripe/MercadoPago) y despliegue continuo en Google Cloud Run. |
| **Fase 2: Tracción B2B** | Mes 3 – 5 | Generación de API Keys para agencias/empresas, exportación PDF de reportes firmados, alertas automáticas por correo/WhatsApp ante cambios en la ventana de cumbre. |
| **Fase 3: Escala B2G** | Mes 6 – 12 | Pilotos con parques nacionales y organismos de protección civil, tableros multi-cumbre regionales e ingesta de datos de estaciones meteorológicas locales. |
