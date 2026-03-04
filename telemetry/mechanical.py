import random
import time

class MechanicalEngine:
    def __init__(self):
        self.fuel_level = 100.0
        self.tire_pressure = [32.0, 32.0, 32.0, 32.0]
        self.engine_temperature = 90.0
        self.battery_level = 100.0
        self.oil_pressure = 40.0
        self.coolant_level = 100.0
        self.brake_wear = 0.0
        self.broken = False
        self.is_refueling = False
        self.engine_on = True

    def step(self, dt=1.0, distance_km=0.0, speed_multiplier=1.0, engine_on=True):
        if self.broken:
            return self.get_state()
            
        adjusted_dt = dt * speed_multiplier
            
        if self.is_refueling:
            self.fuel_level = min(100.0, self.fuel_level + (25.0 * adjusted_dt))
            # State switch handled exclusively by ambulance orchestrator now
        else:
            if engine_on or distance_km > 0:
                # Realistic diesel consumption equivalent
                consumption = (0.15 * distance_km) + (0.005 * adjusted_dt)
                self.fuel_level = max(0.0, self.fuel_level - consumption)
                if self.fuel_level < 1.0 and not self.broken:
                    self.broken = True # completely out of fuel
                    self.fuel_level = 0.0
                
                # Active wear only when engine on
                self.oil_pressure = 40.0 + random.uniform(-2.0, 2.0)
                self.engine_temperature = min(110.0, 90.0 + random.uniform(0.0, 5.0) + (distance_km * 2.0))
                self.coolant_level = max(0.0, self.coolant_level - (0.001 * adjusted_dt))
                self.brake_wear = min(100.0, self.brake_wear + (0.005 * adjusted_dt))
            else:
                # Motor off, cooling down
                self.engine_temperature = max(20.0, self.engine_temperature - (1.0 * adjusted_dt))
                self.oil_pressure = max(0.0, self.oil_pressure - (5.0 * adjusted_dt))
                
        self.battery_level = max(0.0, self.battery_level - (0.005 * adjusted_dt)) # Passive electronics drain
        
        for i in range(4):
            self.tire_pressure[i] = max(0.0, self.tire_pressure[i] - random.uniform(0.0, 0.005 * adjusted_dt))
            
        return self.get_state()

    def get_state(self):
        status = "OK"
        if self.broken or self.fuel_level < 5.0:
            status = "CRITICAL"
        elif self.fuel_level < 20.0 or self.engine_temperature > 105.0 or self.oil_pressure < 30.0:
            status = "WARNING"
            
        return {
            "status": status,
            "fuel_level": round(self.fuel_level, 2),
            "tire_pressure": [round(p, 2) for p in self.tire_pressure],
            "engine_temperature": round(self.engine_temperature, 2),
            "battery_level": round(self.battery_level, 2),
            "oil_pressure": round(self.oil_pressure, 2),
            "coolant_level": round(self.coolant_level, 2),
            "brake_wear": round(self.brake_wear, 2),
            "broken": self.broken,
            "is_refueling": self.is_refueling,
            "engine_on": self.engine_on
        }

    def inject_fault(self, fault_type):
        if fault_type == "flat_tire":
            tire_idx = random.randint(0, 3)
            self.tire_pressure[tire_idx] = 10.0
        elif fault_type == "engine_failure":
            self.broken = True
            self.engine_temperature = 130.0
