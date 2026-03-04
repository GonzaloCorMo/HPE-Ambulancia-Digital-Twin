import random

class VitalsEngine:
    def __init__(self):
        self.heart_rate = 80 # BPM
        self.blood_pressure_sys = 120
        self.blood_pressure_dia = 80
        self.oxygen_level = 98 # %
        self.blood_sugar = 100 # mg/dL
        self.patient_status = "stable" # stable, critical, deceased

    def step(self, dt=1.0):
        if self.patient_status == "deceased":
            self.heart_rate = 0
            self.blood_pressure_sys = 0
            self.blood_pressure_dia = 0
            self.oxygen_level = 0
            return self.get_state()

        fluctuation = 2 if self.patient_status == "stable" else 10
        
        self.heart_rate = max(30, min(200, self.heart_rate + random.uniform(-fluctuation, fluctuation)))
        self.blood_pressure_sys = max(60, min(200, self.blood_pressure_sys + random.uniform(-fluctuation/2, fluctuation/2)))
        self.blood_pressure_dia = max(40, min(130, self.blood_pressure_dia + random.uniform(-fluctuation/2, fluctuation/2)))
        self.oxygen_level = max(50, min(100, self.oxygen_level + random.uniform(-1, 1)))

        if self.patient_status == "critical":
            self.oxygen_level -= 0.5 * dt

        if self.oxygen_level < 85 or self.heart_rate > 150 or self.heart_rate < 40:
            self.patient_status = "critical"

        return self.get_state()

    def get_state(self):
        return {
            "heart_rate": int(self.heart_rate),
            "blood_pressure": f"{int(self.blood_pressure_sys)}/{int(self.blood_pressure_dia)}",
            "oxygen_level": round(self.oxygen_level, 1),
            "blood_sugar": int(self.blood_sugar),
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
