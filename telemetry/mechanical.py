import random
import time
from typing import Dict, List, Optional

class MechanicalEngine:
    def __init__(self):
        self.fuel_level = 100.0  # Porcentaje de combustible
        self.tire_pressure = [32.0, 32.0, 32.0, 32.0]  # PSI para cada rueda
        self.engine_temperature = 90.0  # Celsius
        self.battery_level = 100.0  # Porcentaje
        self.oil_pressure = 40.0  # PSI
        self.coolant_level = 100.0  # Porcentaje
        self.brake_wear = 0.0  # Porcentaje de desgaste
        self.broken = False  # Avería total
        self.is_refueling = False  # En repostaje
        self.engine_on = True  # Motor encendido
        
        # Nuevas métricas mejoradas
        self.oil_level = 100.0  # Porcentaje de aceite
        self.transmission_temperature = 85.0  # Celsius
        self.brake_fluid_level = 100.0  # Porcentaje
        self.alternator_voltage = 13.8  # Voltios
        self.tire_tread_depth = [8.0, 8.0, 8.0, 8.0]  # mm de profundidad
        self.engine_hours = 0.0  # Horas de funcionamiento
        self.last_maintenance_hours = 0.0  # Horas desde último mantenimiento

    def step(self, dt: float = 1.0, distance_km: float = 0.0, 
             speed_multiplier: float = 1.0, engine_on: bool = True) -> Dict:
        """
        Avanza la simulación mecánica un paso de tiempo.
        
        Args:
            dt: Paso de tiempo en segundos (lógico)
            distance_km: Distancia recorrida en km desde el último paso
            speed_multiplier: Multiplicador de velocidad de simulación
            engine_on: Si el motor está encendido
            
        Returns:
            Estado actual del motor mecánico
        """
        if self.broken:
            return self.get_state()
            
        adjusted_dt = dt * speed_multiplier
        self.engine_hours += adjusted_dt / 3600.0  # Acumular horas de motor
            
        if self.is_refueling:
            # Repostaje rápido
            self.fuel_level = min(100.0, self.fuel_level + (35.0 * adjusted_dt))
            # Durante repostaje, otros sistemas se mantienen
        else:
            if engine_on or distance_km > 0:
                # Consumo realista de diésel (L/100km ~15)
                base_consumption = 0.15 * distance_km  # Consumo por distancia
                idle_consumption = 0.005 * adjusted_dt  # Consumo en ralentí
                self.fuel_level = max(0.0, self.fuel_level - (base_consumption + idle_consumption))
                
                # Si se queda sin combustible
                if self.fuel_level < 1.0 and not self.broken:
                    self.broken = True
                    self.fuel_level = 0.0
                    self.engine_on = False
                
                # Desgaste y temperaturas durante operación
                self.oil_pressure = max(10.0, 40.0 + random.uniform(-3.0, 3.0) - (self.engine_hours * 0.001))
                self.engine_temperature = min(115.0, 90.0 + random.uniform(0.0, 8.0) + (distance_km * 1.5))
                self.transmission_temperature = min(100.0, 85.0 + random.uniform(0.0, 5.0) + (distance_km * 0.8))
                
                # Desgaste progresivo
                self.coolant_level = max(50.0, self.coolant_level - (0.0005 * adjusted_dt))
                self.oil_level = max(30.0, self.oil_level - (0.0003 * adjusted_dt))
                self.brake_wear = min(100.0, self.brake_wear + (0.008 * adjusted_dt))
                self.brake_fluid_level = max(60.0, self.brake_fluid_level - (0.0001 * adjusted_dt))
                
                # Desgaste de neumáticos proporcional a distancia
                for i in range(4):
                    self.tire_tread_depth[i] = max(1.6, self.tire_tread_depth[i] - (distance_km * 0.00002))
                    self.tire_pressure[i] = max(20.0, self.tire_pressure[i] - random.uniform(0.0, 0.003 * adjusted_dt))
                    
            else:
                # Motor apagado, enfriamiento
                self.engine_temperature = max(20.0, self.engine_temperature - (2.0 * adjusted_dt))
                self.transmission_temperature = max(20.0, self.transmission_temperature - (1.5 * adjusted_dt))
                self.oil_pressure = max(0.0, self.oil_pressure - (3.0 * adjusted_dt))
        
        # Drenaje pasivo de batería (mayor si motor apagado)
        if not engine_on:
            self.battery_level = max(0.0, self.battery_level - (0.01 * adjusted_dt))
        else:
            # Motor encendido, alternador carga la batería
            self.battery_level = min(100.0, self.battery_level + (0.1 * adjusted_dt))
            self.alternator_voltage = 13.8 + random.uniform(-0.2, 0.2)
            
        # Pequeñas fluctuaciones aleatorias
        self.oil_pressure += random.uniform(-0.5, 0.5)
        self.engine_temperature += random.uniform(-0.3, 0.3)
        
        return self.get_state()

    def get_state(self) -> Dict:
        """
        Retorna el estado actual del motor mecánico.
        
        Returns:
            Diccionario con todas las métricas
        """
        status = "OK"
        if self.broken:
            status = "CRITICAL"
        elif self.fuel_level < 5.0:
            status = "CRITICAL"
        elif (self.fuel_level < 20.0 or 
              self.engine_temperature > 110.0 or 
              self.oil_pressure < 25.0 or
              self.oil_level < 40.0 or
              self.coolant_level < 60.0 or
              any(t < 2.0 for t in self.tire_tread_depth) or
              any(p < 25.0 for p in self.tire_pressure)):
            status = "WARNING"
        elif (self.engine_temperature > 105.0 or 
              self.oil_pressure < 30.0 or
              self.brake_wear > 80.0):
            status = "CAUTION"
            
        return {
            "status": status,
            "fuel_level": round(self.fuel_level, 2),
            "tire_pressure": [round(p, 2) for p in self.tire_pressure],
            "tire_tread_depth": [round(t, 2) for t in self.tire_tread_depth],
            "engine_temperature": round(self.engine_temperature, 2),
            "transmission_temperature": round(self.transmission_temperature, 2),
            "battery_level": round(self.battery_level, 2),
            "alternator_voltage": round(self.alternator_voltage, 2),
            "oil_pressure": round(self.oil_pressure, 2),
            "oil_level": round(self.oil_level, 2),
            "coolant_level": round(self.coolant_level, 2),
            "brake_wear": round(self.brake_wear, 2),
            "brake_fluid_level": round(self.brake_fluid_level, 2),
            "engine_hours": round(self.engine_hours, 2),
            "broken": self.broken,
            "is_refueling": self.is_refueling,
            "engine_on": self.engine_on,
            "last_maintenance_hours": round(self.last_maintenance_hours, 2)
        }

    def inject_fault(self, fault_type: str) -> None:
        """
        Inyecta una falla específica en el sistema mecánico.
        
        Args:
            fault_type: Tipo de falla a inyectar
        """
        if fault_type == "flat_tire":
            tire_idx = random.randint(0, 3)
            self.tire_pressure[tire_idx] = 10.0
            self.tire_tread_depth[tire_idx] = max(1.0, self.tire_tread_depth[tire_idx] - 3.0)
        elif fault_type == "engine_failure":
            self.broken = True
            self.engine_temperature = 130.0
            self.oil_pressure = 5.0
        elif fault_type == "low_oil":
            self.oil_level = 15.0
            self.oil_pressure = 18.0
        elif fault_type == "brake_failure":
            self.brake_wear = 95.0
            self.brake_fluid_level = 30.0
        elif fault_type == "battery_drain":
            self.battery_level = 15.0
            self.alternator_voltage = 11.5
        elif fault_type == "overheating":
            self.engine_temperature = 120.0
            self.coolant_level = 40.0

    def perform_maintenance(self) -> None:
        """Realiza mantenimiento completo, restableciendo valores óptimos."""
        self.fuel_level = 100.0
        self.tire_pressure = [32.0, 32.0, 32.0, 32.0]
        self.tire_tread_depth = [8.0, 8.0, 8.0, 8.0]
        self.engine_temperature = 90.0
        self.battery_level = 100.0
        self.oil_pressure = 40.0
        self.oil_level = 100.0
        self.coolant_level = 100.0
        self.brake_wear = 0.0
        self.brake_fluid_level = 100.0
        self.alternator_voltage = 13.8
        self.transmission_temperature = 85.0
        self.broken = False
        self.is_refueling = False
        self.engine_on = True
        self.last_maintenance_hours = self.engine_hours