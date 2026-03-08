"""
Motor de detección de anomalías mecánicas usando Isolation Forest.

Se entrena en memoria al importarse, con un dataset sintético de operación
normal. Expone `predict_failure()` y un singleton `predictor` listo para usar.
"""
import random
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class AnomalyPredictor:
    """
    Predictor de fallos mecánicos basado en Isolation Forest (sklearn).

    Features de entrada (todas extraídas del dict de MechanicalEngine.get_state()):
      - engine_temperature  (°C)   normal: 85–105
      - oil_pressure        (PSI)  normal: 30–50
      - fuel_level          (%)    normal: 20–100
      - coolant_level       (%)    normal: 70–100
      - battery_level       (%)    normal: 60–100
      - brake_wear          (%)    normal: 0–75
    """

    FEATURES = [
        "engine_temperature",
        "oil_pressure",
        "fuel_level",
        "coolant_level",
        "battery_level",
        "brake_wear",
    ]

    # Rangos de operación NORMAL para generar el dataset sintético
    _NORMAL_RANGES = [
        (85.0, 105.0),   # engine_temperature
        (30.0, 50.0),    # oil_pressure
        (20.0, 100.0),   # fuel_level  (cualquier nivel operacional válido)
        (70.0, 100.0),   # coolant_level
        (60.0, 100.0),   # battery_level
        (0.0, 75.0),     # brake_wear
    ]

    def __init__(self, n_samples: int = 600, contamination: float = 0.05):
        """
        Genera el dataset sintético y entrena el modelo.

        Args:
            n_samples:     Número de muestras normales para entrenamiento.
            contamination: Fracción esperada de outliers (5 % por defecto).
        """
        self._model = None
        self._scaler = None

        try:
            import numpy as np
            from sklearn.ensemble import IsolationForest
            from sklearn.preprocessing import StandardScaler
        except ImportError:
            logger.error(
                "[AnomalyPredictor] scikit-learn no está instalado. "
                "Ejecuta: pip install scikit-learn>=1.3.0  — la predicción IA estará desactivada."
            )
            return

        rng = random.Random(42)

        # ----- Dataset sintético de operación normal -----
        data = []
        for _ in range(n_samples):
            sample = [
                rng.uniform(low, high)
                for low, high in self._NORMAL_RANGES
            ]
            data.append(sample)

        X = np.array(data, dtype=float)
        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X)

        self._model = IsolationForest(
            n_estimators=100,
            contamination=contamination,
            random_state=42,
            n_jobs=-1,
        )
        self._model.fit(X_scaled)

        logger.info(
            f"[AnomalyPredictor] IsolationForest entrenado: {n_samples} muestras, "
            f"contaminación={contamination}, features={self.FEATURES}"
        )

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def predict_failure(self, telemetry_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Predice si los datos de telemetría mecánica corresponden a una anomalía.

        Args:
            telemetry_data: Dict con los campos de MechanicalEngine.get_state().

        Returns:
            {
                "anomaly": bool,   — True si se detecta un patrón anómalo
                "score":   float,  — 0.0 (normal) … 1.0 (muy anómalo)
                "details": str,    — descripción human-readable del problema
            }
        """
        if self._model is None:
            return {"anomaly": False, "score": 0.0, "details": "Predictor no disponible (sklearn ausente)"}

        try:
            import numpy as np

            sample = [
                float(telemetry_data.get("engine_temperature", 90.0)),
                float(telemetry_data.get("oil_pressure",       40.0)),
                float(telemetry_data.get("fuel_level",         80.0)),
                float(telemetry_data.get("coolant_level",      90.0)),
                float(telemetry_data.get("battery_level",      90.0)),
                float(telemetry_data.get("brake_wear",         10.0)),
            ]

            X = np.array([sample], dtype=float)
            X_scaled = self._scaler.transform(X)

            # predict: +1 = normal, -1 = anomalía
            prediction = int(self._model.predict(X_scaled)[0])

            # score_samples: valores más negativos ↔ más anómalos
            raw_score = float(self._model.score_samples(X_scaled)[0])
            # Normalizar a [0, 1] — 0 = normal, 1 = muy anómalo
            normalized_score = max(0.0, min(1.0, (-raw_score - 0.1) / 0.4))

            anomaly = (prediction == -1)

            # Construir mensaje de detalles
            details = ""
            if anomaly:
                issues = []
                if sample[0] > 110.0:
                    issues.append(f"Temp.motor {sample[0]:.0f}°C")
                if sample[1] < 25.0:
                    issues.append(f"Presión aceite {sample[1]:.0f} PSI")
                if sample[2] < 5.0:
                    issues.append(f"Combustible crítico {sample[2]:.0f}%")
                if sample[3] < 60.0:
                    issues.append(f"Refrigerante {sample[3]:.0f}%")
                if sample[4] < 20.0:
                    issues.append(f"Batería {sample[4]:.0f}%")
                if sample[5] > 85.0:
                    issues.append(f"Desgaste frenos {sample[5]:.0f}%")
                details = "; ".join(issues) if issues else "Patrón estadístico anómalo detectado"

            return {
                "anomaly": anomaly,
                "score": round(normalized_score, 4),
                "details": details,
            }

        except Exception as exc:
            logger.warning(f"[AnomalyPredictor] Error durante predicción: {exc}")
            return {"anomaly": False, "score": 0.0, "details": f"Error interno: {exc}"}


# ---------------------------------------------------------------------------
# Singleton global — importar en otros módulos:  from telemetry.ai_predictor import predictor
# ---------------------------------------------------------------------------
predictor = AnomalyPredictor()


# ===========================================================================
# RUL Predictor — Vida Útil Restante del motor
# ===========================================================================

class RULPredictor:
    """
    Predictor de Vida Útil Restante (RUL) del motor usando RandomForestRegressor.

    Features de entrada (todas presentes en MechanicalEngine.get_state()):
      - engine_temperature  (°C)
      - oil_pressure        (PSI)
      - engine_hours        (h)   — horas acumuladas de funcionamiento

    Target: horas restantes de vida útil del motor (0 – 120 h).
    """

    # Umbrales de alerta según documento de diseño
    _THRESHOLD_CRITICAL  =  8.0   # h
    _THRESHOLD_ALERT     = 24.0   # h
    _THRESHOLD_CAUTION   = 72.0   # h

    # Rango máximo de RUL para la generación sintética
    _MAX_RUL = 120.0

    def __init__(self, n_samples: int = 500):
        self._model  = None
        self._scaler = None

        try:
            import numpy as np
            from sklearn.ensemble import RandomForestRegressor
            from sklearn.preprocessing import StandardScaler
        except ImportError:
            logger.error(
                "[RULPredictor] scikit-learn no está instalado. "
                "Ejecuta: pip install scikit-learn>=1.3.0 — la predicción RUL estará desactivada."
            )
            return

        rng = random.Random(0)

        # ── Dataset sintético de degradación ──────────────────────────────
        # El RUL decrece con las horas de uso, la temperatura elevada y la
        # presión de aceite baja, con ruido gaussiano para variabilidad.
        X_list: list = []
        y_list: list = []

        for _ in range(n_samples):
            hours   = rng.uniform(0.0,   500.0)
            temp    = rng.uniform(75.0,  135.0)
            pressure = rng.uniform(8.0,   58.0)

            rul = (
                self._MAX_RUL
                - hours    * 0.22
                - max(0.0, temp    - 100.0) * 1.5
                - max(0.0, 35.0    - pressure) * 2.0
                + rng.gauss(0.0, 3.0)       # ruido gaussiano
            )
            rul = max(0.0, min(self._MAX_RUL, rul))

            X_list.append([temp, pressure, hours])
            y_list.append(rul)

        X = np.array(X_list, dtype=float)
        y = np.array(y_list, dtype=float)

        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X)

        self._model = RandomForestRegressor(
            n_estimators=100,
            random_state=42,
            n_jobs=-1,
        )
        self._model.fit(X_scaled, y)

        logger.info(
            f"[RULPredictor] RandomForestRegressor entrenado: {n_samples} muestras, "
            f"features=[engine_temperature, oil_pressure, engine_hours]"
        )

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def predict_rul(self, telemetry_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Predice las horas de vida útil restante del motor.

        Args:
            telemetry_data: Dict con los campos de MechanicalEngine.get_state().

        Returns:
            {
                "hours_remaining": float,  — horas estimadas de vida útil restante
                "alert_level":     str,    — "NORMAL" | "PRECAUCIÓN" | "ALERTA" | "CRÍTICO"
            }
        """
        if self._model is None:
            return {"hours_remaining": self._MAX_RUL, "alert_level": "NORMAL"}

        try:
            import numpy as np

            sample = [
                float(telemetry_data.get("engine_temperature", 90.0)),
                float(telemetry_data.get("oil_pressure",       40.0)),
                float(telemetry_data.get("engine_hours",        0.0)),
            ]

            X = np.array([sample], dtype=float)
            X_scaled = self._scaler.transform(X)
            rul_hours = float(self._model.predict(X_scaled)[0])
            rul_hours = max(0.0, min(self._MAX_RUL, rul_hours))

            if rul_hours < self._THRESHOLD_CRITICAL:
                alert_level = "CRÍTICO"
            elif rul_hours < self._THRESHOLD_ALERT:
                alert_level = "ALERTA"
            elif rul_hours < self._THRESHOLD_CAUTION:
                alert_level = "PRECAUCIÓN"
            else:
                alert_level = "NORMAL"

            return {
                "hours_remaining": round(rul_hours, 1),
                "alert_level":     alert_level,
            }

        except Exception as exc:
            logger.warning(f"[RULPredictor] Error durante predicción: {exc}")
            return {"hours_remaining": self._MAX_RUL, "alert_level": "NORMAL"}


# ---------------------------------------------------------------------------
# Singleton global — importar con:  from telemetry.ai_predictor import rul_predictor
# ---------------------------------------------------------------------------
rul_predictor = RULPredictor()
