import random
import time

class MechanicalEngine:
    def __init__(self):
        self.fuel_level = 100.0
        self.tire_pressure = [32.0, 32.0, 32.0, 32.0]
        self.engine_temperature = 90.0
        self.battery_level = 100.0
        self.broken = False

    def step(self, dt=1.0):
        if self.broken:
            return self.get_state()
            
        self.fuel_level = max(0.0, self.fuel_level - (0.05 * dt))
        self.battery_level = max(0.0, self.battery_level - (0.01 * dt))
        
        # slight fluctuations
        self.engine_temperature = 90.0 + random.uniform(-5.0, 5.0)
        
        for i in range(4):
            self.tire_pressure[i] = max(0.0, self.tire_pressure[i] - random.uniform(0.0, 0.01 * dt))
            
        return self.get_state()

    def get_state(self):
        return {
            "fuel_level": round(self.fuel_level, 2),
            "tire_pressure": [round(p, 2) for p in self.tire_pressure],
            "engine_temperature": round(self.engine_temperature, 2),
            "battery_level": round(self.battery_level, 2),
            "broken": self.broken
        }

    def inject_fault(self, fault_type):
        if fault_type == "flat_tire":
            tire_idx = random.randint(0, 3)
            self.tire_pressure[tire_idx] = 10.0
        elif fault_type == "engine_failure":
            self.broken = True
            self.engine_temperature = 130.0
