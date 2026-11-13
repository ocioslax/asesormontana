"""
Pruebas unitarias del Golden Set (5 casos) para el Asesor de Seguridad en Alta Montaña.
Ejecución: python -m unittest discover -s src/test -v
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src import main


def _build_mock_weather(
    mountain_name: str,
    altitude: float,
    snow_48h_cm: float = 2.0,
    wind_kmh: float = 20.0,
    temp_min_c: float = -6.0,
    temp_max_c: float = 2.0,
) -> dict:
    """Genera un contexto meteorológico determinista compatible con WeatherSummary."""
    return {
        "source": "Open-Meteo (Golden Set Mock)",
        "consultation_date": "2026-11-12",
        "start_date": "2026-11-15",
        "start_time": "05:00",
        "summit_date": "2026-11-16",
        "summit_time": "10:00",
        "end_date": "2026-11-16",
        "end_time": "16:00",
        "target_date": "2026-11-16",
        "expedition_duration_days": 2,
        "expedition_duration_hours": 35.0,
        "zona_consultada": {
            "nombre": mountain_name,
            "altitud_msnm": altitude,
        },
        "sumas_y_metricas_zona": {
            "nieve_acumulada_48h_cm": snow_48h_cm,
            "viento_max_kmh": wind_kmh,
            "temp_min_c": temp_min_c,
            "temp_max_c": temp_max_c,
        },
        "ventana_expedicion": {
            "cronograma_resumen": "2026-11-15 a 2026-11-16",
            "dias": [],
        },
        "past_14_days": {"date_range": "2026-10-29 a 2026-11-11", "resumen": "Estable"},
        "forecast_until_target": {"date_range": "2026-11-12 a 2026-11-16", "resumen": "Ventana evaluada"},
        "target_day_overview": {"temp_min": temp_min_c, "temp_max": temp_max_c, "wind_max": wind_kmh},
    }


def _assert_three_sections(test_case: unittest.TestCase, report_text: str) -> None:
    """Verifica la presencia obligatoria de los 3 apartados del System Prompt."""
    test_case.assertIn("1. Estado de la Nieve", report_text)
    test_case.assertIn("2. Nivel de Riesgo General", report_text)
    test_case.assertIn("3. Recomendación Final", report_text)
    test_case.assertIn("EAWS", report_text)


class TestGoldenSet(unittest.TestCase):
    """Suite de 5 casos Golden Set para validar veredictos, estructura y guardrails Free Tier."""

    def setUp(self) -> None:
        self.client = TestClient(main.app)
        # Reiniciar estado de cuota antes de cada prueba
        main.gemini_quota_guard = main.GeminiQuotaGuard()

    def _mock_genai_module(self, response_text: str) -> MagicMock:
        mock_model = MagicMock()
        mock_model.generate_content.return_value = SimpleNamespace(text=response_text)
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        return mock_genai

    def test_case_1_go_optimal_window(self) -> None:
        """Caso 1: Ventana estable y cronograma matinal óptimo -> GO."""
        mock_report = (
            "**1. Estado de la Nieve y Viabilidad del Ascenso:** Manto nivoso estable con buen rehielo nocturno. "
            "Equipamiento mínimo: piolet, crampones, casco y kit DVA/pala/sonda.\n"
            "**2. Nivel de Riesgo General:** Peligro de avalanchas EAWS Nivel 1 - Bajo. Viento leve (< 20 km/h). "
            "Riesgo residual operativo: Bajo.\n"
            "**3. Recomendación Final y Criterio 'Go / No Go':** [EXPEDICIÓN RECOMENDADA (Go)]. "
            "El cronograma (salida 04:30, cumbre 10:00, retorno 16:00) es óptimo. Turn-around time estricto: 12:30."
        )
        mock_weather = _build_mock_weather("Cerro El Plomo", 5424.0, snow_48h_cm=0.0, wind_kmh=18.0)
        mock_genai = self._mock_genai_module(mock_report)

        payload = {
            "mountain_name": "Cerro El Plomo",
            "latitude": -33.2319,
            "longitude": -70.2172,
            "altitude": 5424.0,
            "start_date": "2026-11-15",
            "start_time": "04:30",
            "summit_date": "2026-11-16",
            "summit_time": "10:00",
            "end_date": "2026-11-16",
            "end_time": "16:00",
            "route": "Ruta Normal por La Hoya",
            "group_technical_level": "Intermedio con experiencia en cramponaje",
        }

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-fake-key"}), \
             patch.dict(sys.modules, {"google.generativeai": mock_genai}), \
             patch("src.main.fetch_openmeteo_weather", new=AsyncMock(return_value=mock_weather)):
            resp = self.client.post("/api/analyze", json=payload)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["verdict"], "GO")
        self.assertFalse(data["is_simulation"])
        self.assertEqual(data["model_used"], "gemini-2.5-flash")
        _assert_three_sections(self, data["analysis_report"])

    def test_case_2_no_go_extreme_storm(self) -> None:
        """Caso 2: Tormenta severa y alta acumulación de nieve -> NO_GO."""
        mock_report = (
            "**1. Estado de la Nieve y Viabilidad del Ascenso:** Presencia crítica de placas de viento y >35 cm de nieve fresca. "
            "Progresión insegura incluso con piolet, crampones y equipo de avalanchas.\n"
            "**2. Nivel de Riesgo General:** Peligro de avalanchas EAWS Nivel 4 - Fuerte. Ráfagas >75 km/h y viento blanco. "
            "Riesgo residual operativo: Extremo.\n"
            "**3. Recomendación Final y Criterio 'Go / No Go':** [NO RECOMENDADA / ABORTAR (No Go)]. "
            "Se recomienda abortar la salida; turn-around time inmediato ante ráfagas >50 km/h o visibilidad <20 m."
        )
        mock_weather = _build_mock_weather("Volcán Villarrica", 2847.0, snow_48h_cm=38.0, wind_kmh=78.0)
        mock_genai = self._mock_genai_module(mock_report)

        payload = {
            "mountain_name": "Volcán Villarrica",
            "latitude": -39.4209,
            "longitude": -71.9392,
            "altitude": 2847.0,
            "start_date": "2026-11-15",
            "start_time": "05:00",
            "summit_date": "2026-11-15",
            "summit_time": "11:00",
            "end_date": "2026-11-15",
            "end_time": "17:00",
            "route": "Ruta Normal",
            "group_technical_level": "Intermedio",
        }

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-fake-key"}), \
             patch.dict(sys.modules, {"google.generativeai": mock_genai}), \
             patch("src.main.fetch_openmeteo_weather", new=AsyncMock(return_value=mock_weather)):
            resp = self.client.post("/api/analyze", json=payload)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["verdict"], "NO_GO")
        self.assertFalse(data["is_simulation"])
        _assert_three_sections(self, data["analysis_report"])

    def test_case_3_conditional_late_summit_schedule(self) -> None:
        """Caso 3: Clima moderado pero horario de cumbre tardío (15:30) -> CONDITIONAL."""
        mock_report = (
            "**1. Estado de la Nieve y Viabilidad del Ascenso:** Nieve firme en la mañana pero con fusión acelerada por tarde. "
            "Requiere piolet, crampones y encordamiento glaciar.\n"
            "**2. Nivel de Riesgo General:** Peligro de avalanchas EAWS Nivel 2 - Limitado (aumenta a Nivel 3 por tarde). "
            "Riesgo residual operativo: Moderado.\n"
            "**3. Recomendación Final y Criterio 'Go / No Go':** [RECOMENDADA CON CONDICIONANTES / RUTA ALTERNATIVA]. "
            "El ataque a cumbre a las 15:30 y retorno a las 21:00 es inseguro por pérdida de rehielo y noche en descenso. "
            "Se exige adelantar la salida y fijar turn-around time máximo a las 12:00."
        )
        mock_weather = _build_mock_weather("Mont Blanc", 4808.0, snow_48h_cm=4.0, wind_kmh=25.0)
        mock_genai = self._mock_genai_module(mock_report)

        payload = {
            "mountain_name": "Mont Blanc",
            "latitude": 45.8326,
            "longitude": 6.8652,
            "altitude": 4808.0,
            "start_date": "2026-11-15",
            "start_time": "08:00",
            "summit_date": "2026-11-15",
            "summit_time": "15:30",
            "end_date": "2026-11-15",
            "end_time": "21:00",
            "route": "Arista de Goûter",
            "group_technical_level": "Avanzado en glaciar",
        }

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-fake-key"}), \
             patch.dict(sys.modules, {"google.generativeai": mock_genai}), \
             patch("src.main.fetch_openmeteo_weather", new=AsyncMock(return_value=mock_weather)):
            resp = self.client.post("/api/analyze", json=payload)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["verdict"], "CONDITIONAL")
        self.assertIn("15:30", data["analysis_report"])
        _assert_three_sections(self, data["analysis_report"])

    def test_case_4_incomplete_route_and_technical_level(self) -> None:
        """Caso 4: Ruta y nivel técnico vacíos -> CONDITIONAL y nota de datos faltantes."""
        mock_report = (
            "**1. Estado de la Nieve y Viabilidad del Ascenso:** Condiciones nivales variables en cota 4.180 m. "
            "Equipamiento mínimo: piolet, crampones y abrigo técnico.\n"
            "**2. Nivel de Riesgo General:** Escala EAWS Nivel 2 - Limitado. Viento moderado (35 km/h). "
            "Riesgo residual operativo: Moderado.\n"
            "**3. Recomendación Final y Criterio 'Go / No Go':** [RECOMENDADA CON CONDICIONANTES / RUTA ALTERNATIVA]. "
            "Turn-around time sugerido: 13:00. "
            "Nota: Se requiere especificar la ruta precisa y el nivel técnico del grupo para una evaluación definitiva."
        )
        mock_weather = _build_mock_weather("Cerro Pintor", 4180.0, snow_48h_cm=5.0, wind_kmh=35.0)
        mock_genai = self._mock_genai_module(mock_report)

        payload = {
            "mountain_name": "Cerro Pintor",
            "latitude": -33.3069,
            "longitude": -70.2053,
            "altitude": 4180.0,
            "start_date": "2026-11-15",
            "start_time": "06:00",
            "summit_date": "2026-11-15",
            "summit_time": "11:00",
            "end_date": "2026-11-15",
            "end_time": "16:00",
            "route": "",
            "group_technical_level": "",
        }

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-fake-key"}), \
             patch.dict(sys.modules, {"google.generativeai": mock_genai}), \
             patch("src.main.fetch_openmeteo_weather", new=AsyncMock(return_value=mock_weather)):
            resp = self.client.post("/api/analyze", json=payload)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["verdict"], "CONDITIONAL")
        self.assertIn("ruta precisa", data["analysis_report"].lower())
        self.assertIn("nivel técnico", data["analysis_report"].lower())
        _assert_three_sections(self, data["analysis_report"])

    def test_case_5_free_tier_guardrail_fallback(self) -> None:
        """Caso 5: Al superar GEMINI_MAX_RPM, activa contingencia Free Tier sin error HTTP."""
        mock_weather = _build_mock_weather("Cerro El Plomo", 5424.0, snow_48h_cm=2.0, wind_kmh=22.0)

        # Configurar límite estricto de 1 RPM para disparar el guardrail en la segunda llamada
        main.gemini_quota_guard.max_rpm = 1
        main.gemini_quota_guard.cache_ttl_seconds = 0

        mock_report = (
            "**1. Estado de la Nieve y Viabilidad del Ascenso:** Estable.\n"
            "**2. Nivel de Riesgo General:** EAWS Nivel 1 - Bajo.\n"
            "**3. Recomendación Final y Criterio 'Go / No Go':** [EXPEDICIÓN RECOMENDADA (Go)]."
        )
        mock_genai = self._mock_genai_module(mock_report)

        payload = {
            "mountain_name": "Cerro El Plomo",
            "latitude": -33.2319,
            "longitude": -70.2172,
            "altitude": 5424.0,
            "start_date": "2026-11-15",
            "start_time": "05:00",
            "summit_date": "2026-11-16",
            "summit_time": "10:00",
            "end_date": "2026-11-16",
            "end_time": "16:00",
            "route": "Ruta Normal",
            "group_technical_level": "Intermedio",
        }

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-fake-key"}), \
             patch.dict(sys.modules, {"google.generativeai": mock_genai}), \
             patch("src.main.fetch_openmeteo_weather", new=AsyncMock(return_value=mock_weather)):
            resp_1 = self.client.post("/api/analyze", json=payload)
            resp_2 = self.client.post("/api/analyze", json=payload)

        self.assertEqual(resp_1.status_code, 200)
        self.assertFalse(resp_1.json()["is_simulation"])

        self.assertEqual(resp_2.status_code, 200)
        data_2 = resp_2.json()
        self.assertTrue(data_2["is_simulation"])
        self.assertEqual(data_2["model_used"], "fallback-free-tier-guard")
        self.assertIn("Protección Free Tier Activa", data_2["analysis_report"])
        _assert_three_sections(self, data_2["analysis_report"])


if __name__ == "__main__":
    unittest.main()
