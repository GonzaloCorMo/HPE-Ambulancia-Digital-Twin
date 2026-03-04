import random

class VitalsEngine:
    def __init__(self):
        self.heart_rate = 80 # BPM
        self.blood_pressure_sys = 120
        self.blood_pressure_dia = 80
        self.oxygen_level = 98 # %
        self.blood_sugar = 100 # mg/dL
        self.respiratory_rate = 16 # breaths/min
        self.body_temperature = 37.0 # Celsius
        self.patient_status = "stable" # stable, critical, deceased

    def step(self, dt=1.0):
        if self.patient_status == "deceased":
            self.heart_rate = 0
            self.blood_pressure_sys = 0
            self.blood_pressure_dia = 0
            self.oxygen_level = 0
            self.respiratory_rate = 0
            self.body_temperature = max(20.0, self.body_temperature - 0.1 * dt)
            return self.get_state()

        fluctuation = 2 if self.patient_status == "stable" else 10
        
        self.heart_rate = max(30, min(200, self.heart_rate + random.uniform(-fluctuation, fluctuation)))
        self.blood_pressure_sys = max(60, min(200, self.blood_pressure_sys + random.uniform(-fluctuation/2, fluctuation/2)))
        self.blood_pressure_dia = max(40, min(130, self.blood_pressure_dia + random.uniform(-fluctuation/2, fluctuation/2)))
        self.oxygen_level = max(50, min(100, self.oxygen_level + random.uniform(-1, 1)))
        self.respiratory_rate = max(8, min(40, self.respiratory_rate + random.uniform(-2, 2)))
        self.body_temperature = max(35.0, min(41.0, self.body_temperature + random.uniform(-0.1, 0.1)))

        if self.patient_status == "critical":
            self.oxygen_level -= 0.5 * dt

        if self.oxygen_level < 85 or self.heart_rate > 150 or self.heart_rate < 40:
            self.patient_status = "critical"

        return self.get_state()

    def get_state(self):
        ecg_rhythm = "Normal Sinus Rhythm"
        if self.patient_status == "deceased":
            ecg_rhythm = "Asystole"
        elif self.patient_status == "critical":
            ecg_rhythm = "Ventricular Tachycardia" if self.heart_rate > 150 else "Bradycardia"

        return {
            "heart_rate": int(self.heart_rate),
            "blood_pressure": f"{int(self.blood_pressure_sys)}/{int(self.blood_pressure_dia)}",
            "oxygen_level": round(self.oxygen_level, 1),
            "blood_sugar": int(self.blood_sugar),
            "respiratory_rate": int(self.respiratory_rate),
            "body_temperature": round(self.body_temperature, 1),
            "ecg_rhythm": ecg_rhythm,
            "patient_status": self.patient_status
        }

    def inject_incident(self, incident_type):
        if incident_type == "cardiac_arrest":
            self.heart_rate = 0
            self.blood_pressure_sys = 0
            self.blood_pressure_dia = 0
            self.patient_status = "critical"
        elif incident_type == "drop_oxygen":
            self.oxygen_level = 80
            self.patient_status = "critical"
