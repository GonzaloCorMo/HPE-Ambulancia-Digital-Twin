import random
import time
from typing import Dict, List, Literal, Optional
from enum import Enum

class PatientStatus(Enum):
    NONE = "NONE"
    STABLE = "stable"
    UNSTABLE = "unstable"
    CRITICAL = "critical"
    DECEASED = "deceased"

class ECG_Rhythm(Enum):
    NORMAL_SINUS = "Normal Sinus Rhythm"
    SINUS_TACHYCARDIA = "Sinus Tachycardia"
    SINUS_BRADYCARDIA = "Sinus Bradycardia"
    ATRIAL_FIBRILLATION = "Atrial Fibrillation"
    VENTRICULAR_TACHYCARDIA = "Ventricular Tachycardia"
    VENTRICULAR_FIBRILLATION = "Ventricular Fibrillation"
    ASYSTOLE = "Asystole"
    PEA = "Pulseless Electrical Activity"
    OFF = "OFF"

class VitalsEngine:
    def __init__(self):
        # Parámetros cardiovasculares
        self.heart_rate = 80  # BPM
        self.blood_pressure_sys = 120  # mmHg
        self.blood_pressure_dia = 80   # mmHg
        self.mean_arterial_pressure = 93.3  # mmHg
        self.cardiac_output = 5.0  # L/min
        
        # Parámetros respiratorios
        self.oxygen_level = 98  # SpO2 %
        self.respiratory_rate = 16  # breaths/min
        self.tidal_volume = 500  # mL
        self.minute_ventilation = 8.0  # L/min
        self.end_tidal_co2 = 35  # mmHg
        self.inspired_oxygen = 21  # FiO2 %
        
        # Parámetros metabólicos
        self.blood_sugar = 100  # mg/dL
        self.body_temperature = 37.0  # Celsius
        self.blood_ph = 7.40  # pH
        self.lactate_level = 1.0  # mmol/L
        self.hemoglobin = 14.0  # g/dL
        
        # Parámetros neurológicos
        self.glasgow_coma_scale = 15  # Puntuación GCS (3-15)
        self.pain_level = 0  # Escala 0-10
        
        # Estado del paciente
        self.patient_status = PatientStatus.STABLE
        self.has_patient = False  # Simulador no genera signos si está vacío
        self.patient_age = 45  # Años (para cálculo de parámetros)
        self.time_since_incident = 0.0  # Minutos desde incidente
        
        # Historial para tendencias
        self.hr_history: List[int] = []
        self.bp_history: List[tuple[int, int]] = []
        self.spo2_history: List[float] = []

    def step(self, dt: float = 1.0) -> Dict:
        """
        Avanza la simulación de constantes vitales un paso de tiempo.
        
        Args:
            dt: Paso de tiempo en segundos (lógico)
            
        Returns:
            Estado actual de las constantes vitales
        """
        if not self.has_patient:
            return self.get_state()
            
        if self.patient_status == PatientStatus.DECEASED:
            # Paciente fallecido - valores nulos
            self.heart_rate = 0
            self.blood_pressure_sys = 0
            self.blood_pressure_dia = 0
            self.mean_arterial_pressure = 0
            self.oxygen_level = 0
            self.respiratory_rate = 0
            self.body_temperature = max(20.0, self.body_temperature - 0.05 * dt)
            return self.get_state()

        self.time_since_incident += dt / 60.0  # Convertir a minutos
        
        # Determinar fluctuación basada en estado
        if self.patient_status == PatientStatus.STABLE:
            fluctuation = 2
            trend_stability = 0.8
        elif self.patient_status == PatientStatus.UNSTABLE:
            fluctuation = 5
            trend_stability = 0.5
        else:  # CRITICAL
            fluctuation = 10
            trend_stability = 0.2
        
        # Simulación de parámetros cardiovasculares con correlación
        hr_change = random.uniform(-fluctuation, fluctuation) * trend_stability
        self.heart_rate = max(30, min(200, self.heart_rate + hr_change))
        
        # La presión arterial correlaciona con la frecuencia cardíaca
        bp_sys_change = hr_change * 0.3 + random.uniform(-fluctuation/2, fluctuation/2)
        bp_dia_change = hr_change * 0.2 + random.uniform(-fluctuation/2, fluctuation/2)
        
        self.blood_pressure_sys = max(60, min(200, self.blood_pressure_sys + bp_sys_change))
        self.blood_pressure_dia = max(40, min(130, self.blood_pressure_dia + bp_dia_change))
        self.mean_arterial_pressure = self.blood_pressure_dia + (self.blood_pressure_sys - self.blood_pressure_dia) / 3
        self.cardiac_output = (self.heart_rate * 0.07) * (self.mean_arterial_pressure / 100)  # Simplificado
        
        # Parámetros respiratorios
        self.oxygen_level = max(50, min(100, self.oxygen_level + random.uniform(-1, 1)))
        self.respiratory_rate = max(8, min(40, self.respiratory_rate + random.uniform(-2, 2)))
        self.tidal_volume = max(300, min(800, self.tidal_volume + random.uniform(-20, 20)))
        self.minute_ventilation = (self.respiratory_rate * self.tidal_volume) / 1000.0
        self.end_tidal_co2 = max(20, min(60, self.end_tidal_co2 + random.uniform(-1, 1)))
        
        # Parámetros metabólicos
        self.blood_sugar = max(70, min(250, self.blood_sugar + random.uniform(-2, 2)))
        self.body_temperature = max(35.0, min(41.0, self.body_temperature + random.uniform(-0.1, 0.1)))
        self.blood_ph = max(7.20, min(7.60, self.blood_ph + random.uniform(-0.01, 0.01)))
        
        # Efectos del estado crítico
        if self.patient_status == PatientStatus.CRITICAL:
            self.oxygen_level -= 0.8 * dt
            self.lactate_level += 0.1 * dt
            self.blood_ph -= 0.005 * dt
            self.glasgow_coma_scale = max(3, self.glasgow_coma_scale - random.uniform(0, 0.1 * dt))
        elif self.patient_status == PatientStatus.UNSTABLE:
            self.oxygen_level -= 0.2 * dt
            self.lactate_level += 0.05 * dt
        
        # Lógica de transición de estado
        if self.patient_status != PatientStatus.DECEASED:
            if self.oxygen_level < 85 or self.heart_rate > 150 or self.heart_rate < 40:
                self.patient_status = PatientStatus.CRITICAL
            elif self.oxygen_level < 92 or self.heart_rate > 120 or self.heart_rate < 50:
                self.patient_status = PatientStatus.UNSTABLE
            elif self.oxygen_level >= 94 and 60 <= self.heart_rate <= 100:
                self.patient_status = PatientStatus.STABLE
            
            # Muerte por parada cardiorrespiratoria
            if (self.heart_rate == 0 and self.oxygen_level < 30) or self.oxygen_level < 30:
                self.patient_status = PatientStatus.DECEASED
        
        # Mantener historial para tendencias (últimos 60 segundos)
        self.hr_history.append(int(self.heart_rate))
        self.bp_history.append((int(self.blood_pressure_sys), int(self.blood_pressure_dia)))
        self.spo2_history.append(float(self.oxygen_level))
        
        if len(self.hr_history) > 60:
            self.hr_history.pop(0)
            self.bp_history.pop(0)
            self.spo2_history.pop(0)
        
        return self.get_state()

    def get_state(self) -> Dict:
        """
        Retorna el estado actual de las constantes vitales.
        
        Returns:
            Diccionario con todas las métricas médicas
        """
        if not self.has_patient:
            return {
                "heart_rate": 0,
                "blood_pressure": "0/0",
                "mean_arterial_pressure": 0,
                "cardiac_output": 0.0,
                "oxygen_level": 0.0,
                "respiratory_rate": 0,
                "tidal_volume": 0,
                "minute_ventilation": 0.0,
                "end_tidal_co2": 0,
                "inspired_oxygen": 0,
                "blood_sugar": 0,
                "body_temperature": 0.0,
                "blood_ph": 0.0,
                "lactate_level": 0.0,
                "hemoglobin": 0.0,
                "glasgow_coma_scale": 0,
                "pain_level": 0,
                "ecg_rhythm": ECG_Rhythm.OFF.value,
                "patient_status": PatientStatus.NONE.value,
                "patient_age": 0,
                "time_since_incident": 0.0,
                "hr_trend": [],
                "spo2_trend": []
            }

        # Determinar ritmo ECG basado en parámetros
        ecg_rhythm = ECG_Rhythm.NORMAL_SINUS
        if self.patient_status == PatientStatus.DECEASED:
            ecg_rhythm = ECG_Rhythm.ASYSTOLE
        elif self.heart_rate > 150:
            ecg_rhythm = ECG_Rhythm.VENTRICULAR_TACHYCARDIA
        elif self.heart_rate > 120:
            ecg_rhythm = ECG_Rhythm.SINUS_TACHYCARDIA
        elif self.heart_rate < 40:
            ecg_rhythm = ECG_Rhythm.SINUS_BRADYCARDIA
        elif self.heart_rate == 0 and self.oxygen_level > 30:
            ecg_rhythm = ECG_Rhythm.PEA
        elif random.random() < 0.05 and self.patient_status == PatientStatus.CRITICAL:
            ecg_rhythm = ECG_Rhythm.ATRIAL_FIBRILLATION

        return {
            "heart_rate": int(self.heart_rate),
            "blood_pressure": f"{int(self.blood_pressure_sys)}/{int(self.blood_pressure_dia)}",
            "mean_arterial_pressure": round(self.mean_arterial_pressure, 1),
            "cardiac_output": round(self.cardiac_output, 2),
            "oxygen_level": round(self.oxygen_level, 1),
            "respiratory_rate": int(self.respiratory_rate),
            "tidal_volume": int(self.tidal_volume),
            "minute_ventilation": round(self.minute_ventilation, 2),
            "end_tidal_co2": int(self.end_tidal_co2),
            "inspired_oxygen": int(self.inspired_oxygen),
            "blood_sugar": int(self.blood_sugar),
            "body_temperature": round(self.body_temperature, 1),
            "blood_ph": round(self.blood_ph, 2),
            "lactate_level": round(self.lactate_level, 1),
            "hemoglobin": round(self.hemoglobin, 1),
            "glasgow_coma_scale": int(self.glasgow_coma_scale),
            "pain_level": int(self.pain_level),
            "ecg_rhythm": ecg_rhythm.value,
            "patient_status": self.patient_status.value,
            "patient_age": int(self.patient_age),
            "time_since_incident": round(self.time_since_incident, 2),
            "hr_trend": self.hr_history[-10:] if len(self.hr_history) >= 10 else self.hr_history,
            "spo2_trend": self.spo2_history[-10:] if len(self.spo2_history) >= 10 else self.spo2_history
        }

    def inject_incident(self, incident_type: str) -> None:
        """
        Inyecta un incidente médico específico.
        
        Args:
            incident_type: Tipo de incidente a inyectar
        """
        if incident_type == "cardiac_arrest":
            self.heart_rate = 0
            self.blood_pressure_sys = 0
            self.blood_pressure_dia = 0
            self.oxygen_level = 30
            self.patient_status = PatientStatus.CRITICAL
        elif incident_type == "drop_oxygen":
            self.oxygen_level = 75
            self.patient_status = PatientStatus.CRITICAL
        elif incident_type == "hypotension":
            self.blood_pressure_sys = 80
            self.blood_pressure_dia = 50
            self.patient_status = PatientStatus.UNSTABLE
        elif incident_type == "hyperglycemia":
            self.blood_sugar = 300
            self.patient_status = PatientStatus.UNSTABLE
        elif incident_type == "hypothermia":
            self.body_temperature = 34.0
            self.patient_status = PatientStatus.UNSTABLE
        elif incident_type == "traumatic_injury":
            self.heart_rate = 130
            self.blood_pressure_sys = 90
            self.blood_pressure_dia = 60
            self.oxygen_level = 85
            self.lactate_level = 5.0
            self.glasgow_coma_scale = 10
            self.pain_level = 8
            self.patient_status = PatientStatus.CRITICAL
        elif incident_type == "stroke":
            self.blood_pressure_sys = 180
            self.blood_pressure_dia = 110
            self.glasgow_coma_scale = 8
            self.patient_status = PatientStatus.CRITICAL

    def set_patient_info(self, age: int = 45, has_patient: bool = True) -> None:
        """
        Configura información del paciente.
        
        Args:
            age: Edad del paciente en años
            has_patient: Si hay un paciente en la ambulancia
        """
        self.patient_age = age
        self.has_patient = has_patient
        if has_patient:
            # Ajustar parámetros basados en edad
            self.heart_rate = max(60, 80 - (age - 45) * 0.5)
            self.blood_pressure_sys = min(140, 120 + (age - 45) * 0.8)
        else:
            self.patient_status = PatientStatus.NONE

    def administer_treatment(self, treatment_type: str) -> bool:
        """
        Administra un tratamiento y actualiza las constantes.
        
        Args:
            treatment_type: Tipo de tratamiento a administrar
            
        Returns:
            True si el tratamiento fue efectivo
        """
        if not self.has_patient or self.patient_status == PatientStatus.DECEASED:
            return False
            
        if treatment_type == "oxygen":
            self.oxygen_level = min(100, self.oxygen_level + 10)
            self.inspired_oxygen = min(100, self.inspired_oxygen + 20)
            return True
        elif treatment_type == "epinephrine":
            self.heart_rate = min(150, self.heart_rate + 20)
            self.blood_pressure_sys = min(180, self.blood_pressure_sys + 30)
            return True
        elif treatment_type == "fluids":
            self.blood_pressure_sys = min(140, self.blood_pressure_sys + 15)
            self.blood_pressure_dia = min(90, self.blood_pressure_dia + 10)
            return True
        elif treatment_type == "analgesia":
            self.pain_level = max(0, self.pain_level - 4)
            return True
            
        return False