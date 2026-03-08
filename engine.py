import random
import time
import math
import uuid
import threading
import logging
from typing import Dict, List, Optional, Any, Tuple, Callable
from main import launch_ambulance
from telemetry.logistics import (
    POIS, JAMS, MissionStatus, add_poi, add_jam, remove_jam
)
from telemetry.vitals import PatientStatus

# Distancia maxima operativa: asignaciones mas largas son rechazadas automaticamente
MAX_OPERATIONAL_DISTANCE_KM = 150.0

# Presets de escenarios predefinidos con infraestructura
SCENARIO_PRESETS = {
    "madrid": {
        "name": "Madrid",
        "hospitals": [
            (40.4812, -3.6868, "Hospital La Paz"),
            (40.4210, -3.6716, "Hospital Gregorio Marañón"),
            (40.3764, -3.6977, "Hospital 12 de Octubre"),
        ],
        "gas_stations": [
            (40.4500, -3.6900, "Repsol Castellana"),
            (40.4070, -3.6930, "Cepsa Atocha"),
        ],
        "ambulance_positions": [
            (40.4700, -3.7200),
            (40.4300, -3.6900),
            (40.4600, -3.6500),
            (40.4000, -3.7100),
        ],
    },
    "barcelona": {
        "name": "Barcelona",
        "hospitals": [
            (41.3900, 2.1530, "Hospital Clínic de Barcelona"),
            (41.4018, 2.1734, "Hospital de la Vall d'Hebron"),
            (41.3807, 2.1586, "Hospital de la Santa Creu i Sant Pau"),
        ],
        "gas_stations": [
            (41.3950, 2.1600, "Repsol Diagonal"),
            (41.3850, 2.1700, "BP Gran Via"),
        ],
        "ambulance_positions": [
            (41.3850, 2.1500),
            (41.3950, 2.1750),
            (41.4050, 2.1600),
            (41.3780, 2.1650),
        ],
    },
    "sevilla": {
        "name": "Sevilla",
        "hospitals": [
            (37.3927, -5.9876, "Hospital Virgen del Rocío"),
            (37.3762, -5.9905, "Hospital Virgen Macarena"),
        ],
        "gas_stations": [
            (37.3858, -5.9800, "Cepsa Sevilla Centro"),
            (37.3720, -5.9760, "Repsol Macarena"),
        ],
        "ambulance_positions": [
            (37.3890, -5.9850),
            (37.3780, -5.9780),
            (37.3960, -5.9920),
        ],
    },
    "valencia": {
        "name": "Valencia",
        "hospitals": [
            (39.4669, -0.3763, "Hospital La Fe"),
            (39.4762, -0.3765, "Hospital Clínico Universitario Valencia"),
        ],
        "gas_stations": [
            (39.4700, -0.3800, "Galp Valencia Norte"),
            (39.4650, -0.3720, "Repsol Av. del Cid"),
        ],
        "ambulance_positions": [
            (39.4720, -0.3810),
            (39.4650, -0.3750),
            (39.4730, -0.3700),
        ],
    },
    "cdmx": {
        "name": "Ciudad de México",
        "hospitals": [
            (19.4004, -99.1502, "Hospital General de México"),
            (19.4285, -99.1436, "Hospital ABC Observatorio"),
            (19.3736, -99.1572, "IMSS Centro Médico"),
        ],
        "gas_stations": [
            (19.4100, -99.1600, "PEMEX Insurgentes"),
            (19.3900, -99.1450, "PEMEX Eje 6 Sur"),
        ],
        "ambulance_positions": [
            (19.4050, -99.1550),
            (19.4250, -99.1500),
            (19.3850, -99.1600),
            (19.4150, -99.1350),
        ],
    },
    "guadalajara": {
        "name": "Guadalajara (MX)",
        "hospitals": [
            (20.6774, -103.3475, "Hospital Civil de Guadalajara"),
            (20.6890, -103.3680, "Hospital México Americano"),
        ],
        "gas_stations": [
            (20.6800, -103.3550, "PEMEX Av. Vallarta"),
            (20.6720, -103.3400, "PEMEX Federalismo"),
        ],
        "ambulance_positions": [
            (20.6820, -103.3480),
            (20.6750, -103.3600),
            (20.6880, -103.3380),
        ],
    },
    "monterrey": {
        "name": "Monterrey (MX)",
        "hospitals": [
            (25.6716, -100.3091, "Hospital Universitario UANL"),
            (25.6822, -100.3183, "Hospital Christus Muguerza"),
        ],
        "gas_stations": [
            (25.6760, -100.3100, "PEMEX Av. Lázaro Cárdenas"),
            (25.6680, -100.2980, "PEMEX Revolución"),
        ],
        "ambulance_positions": [
            (25.6740, -100.3050),
            (25.6810, -100.3200),
            (25.6650, -100.3150),
        ],
    },
    "bogota": {
        "name": "Bogotá",
        "hospitals": [
            (4.6286, -74.0978, "Hospital San Ignacio"),
            (4.6552, -74.0830, "Hospital El Tunal"),
            (4.6015, -74.0736, "Hospital Santa Clara"),
        ],
        "gas_stations": [
            (4.6350, -74.0900, "Terpel Cra 7"),
            (4.6150, -74.0850, "Primax Av. 68"),
        ],
        "ambulance_positions": [
            (4.6300, -74.0950),
            (4.6500, -74.0800),
            (4.6080, -74.0780),
            (4.6420, -74.0860),
        ],
    },
    "medellin": {
        "name": "Medellín",
        "hospitals": [
            (6.2442, -75.5936, "Hospital General de Medellín"),
            (6.2694, -75.5607, "Clínica Las Américas"),
        ],
        "gas_stations": [
            (6.2510, -75.5800, "Terpel El Centro"),
            (6.2630, -75.5650, "Primax Laureles"),
        ],
        "ambulance_positions": [
            (6.2480, -75.5870),
            (6.2600, -75.5700),
            (6.2380, -75.5760),
        ],
    },
    "cali": {
        "name": "Cali",
        "hospitals": [
            (3.4516, -76.5320, "Hospital Universitario del Valle"),
            (3.4660, -76.5210, "Clínica Imbanaco"),
        ],
        "gas_stations": [
            (3.4570, -76.5280, "Terpel Cra 1"),
            (3.4630, -76.5150, "Primax Av. Roosevelt"),
        ],
        "ambulance_positions": [
            (3.4540, -76.5300),
            (3.4680, -76.5240),
            (3.4480, -76.5180),
        ],
    },
}

logger = logging.getLogger(__name__)

class SimulatorEngine:
    """
    Motor central de simulación que gestiona flota de ambulancias, emergencias
    y lógica de despacho inteligente.
    """
    
    def __init__(self, log_callback: Optional[Callable[[str], None]] = None):
        """
        Inicializa el motor de simulación.
        
        Args:
            log_callback: Función callback para logging
        """
        self.ambulances: Dict[str, Any] = {}
        self.active_emergencies: Dict[str, Dict[str, Any]] = {}
        
        self.running = True
        self.is_simulating = False
        
        self.speed_multiplier = 1
        self.event_severity = 1.0  # Multiplier for auto-sim event frequency (0.2–5.0)
        self.fault_frequency = 1.0  # Multiplier for mechanical fault injection rate (0.1–10.0)
        self.mqtt_on = True
        self.p2p_on = True
        self.http_on = True
        
        self.log_callback = log_callback or self._default_logger
        
        # Estadísticas
        self.emergencies_handled = 0
        self.total_response_time = 0.0
        self.average_response_time = 0.0

        # Flags de simulación autónoma
        self._auto_sim_active: bool = False
        self._auto_jam_active: bool = False
        self._rul_monitor_active: bool = False
        self._rul_warned: set = set()  # Ambulance IDs that have received ALERTA log (avoid spam)
        self._repair_timers: Dict[str, float] = {}  # amb_id → timestamp when repair started
        
        # Iniciar hilo de despacho
        self._dispatch_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._dispatch_thread.start()
        
        logger.info("SimulatorEngine inicializado")
        
    def _default_logger(self, message: str) -> None:
        """Logger por defecto."""
        logger.info(message)

    def log_network(self, message: str) -> None:
        """Envía mensaje al logger."""
        if self.log_callback:
            self.log_callback(message)

    def _is_within_operational_area(self, lat: float, lon: float) -> bool:
        """Devuelve True si las coordenadas están cerca de algún hospital del mapa."""
        hospitals = [p for p in POIS if p.get("type") == "HOSPITAL"]
        if not hospitals:
            return True  # Sin hospitales, toda ubicación es válida
        return any(
            self._calculate_distance_km(lat, lon, h["lat"], h["lon"])
            <= MAX_OPERATIONAL_DISTANCE_KM
            for h in hospitals
        )

    def spawn_ambulance(self, lat: float, lon: float) -> str:
        """
        Despliega una nueva ambulancia en el mapa.
        
        Args:
            lat: Latitud inicial
            lon: Longitud inicial
            
        Returns:
            ID de la ambulancia creada
        """
        am_id = f"AMB-{len(self.ambulances)+1:03d}"
        
        try:
            self.ambulances[am_id] = launch_ambulance(
                am_id, lat, lon, "localhost", log_callback=self.log_network
            )
            self.ambulances[am_id].speed_multiplier = self.speed_multiplier
            self.ambulances[am_id].is_paused = not self.is_simulating

            # Solo auto-enrutar si la ambulancia está cerca de algún hospital.
            if self._is_within_operational_area(lat, lon):
                if hasattr(self.ambulances[am_id].logistics, 'route_to_nearest'):
                    self.ambulances[am_id].logistics.route_to_nearest("GAS_STATION")
            else:
                self.ambulances[am_id].logistics.action_message = "Fuera de área operativa - En espera"

            self.log_network(f"[SISTEMA] 🚑 Nueva unidad {am_id} desplegada en ({lat:.4f}, {lon:.4f}).")
            return am_id
            
        except Exception as e:
            logger.error(f"Error desplegando ambulancia: {e}")
            self.log_network(f"[ERROR] Fallo al desplegar ambulancia: {e}")
            raise

    def spawn_emergency(self, lat: float, lon: float, severity: str = "MEDIUM") -> str:
        """
        Crea una nueva emergencia en el mapa.
        
        Args:
            lat: Latitud de la emergencia
            lon: Longitud de la emergencia
            severity: Gravedad (LOW, MEDIUM, HIGH, CRITICAL)
            
        Returns:
            ID de la emergencia creada
        """
        em_id = str(uuid.uuid4())[:8]
        emergency = {
            "id": em_id,
            "lat": lat,
            "lon": lon,
            "status": "INITIATED",
            "severity": severity,
            "created_at": time.time(),
            "assigned_ambulance": None,
            "response_time": None,
            "hospital_assigned": None
        }
        
        self.active_emergencies[em_id] = emergency
        self.log_network(f"[URGENCIA {em_id}] 🚨 Estado: INITIATED. "
                        f"Gravedad: {severity}. Ubicación: ({lat:.4f}, {lon:.4f})")
        
        # Evaluar asignación de recursos
        self.evaluate_fleet_assignments()
        return em_id

    def evaluate_fleet_assignments(self) -> None:
        """
        Evalúa y asigna ambulancias disponibles a emergencias pendientes.
        Usa algoritmo de asignación óptima considerando distancia, combustible
        y gravedad de la emergencia.
        """
        if not self.running or not self.is_simulating:
            return
        
        # Filtrar emergencias que necesitan asignación
        pending_emergencies = [
            em for em in self.active_emergencies.values() 
            if em["status"] == "INITIATED"
        ]
        
        if not pending_emergencies:
            return
        
        # Filtrar hospitales disponibles
        hospitals = [p for p in POIS if p.get("type") == "HOSPITAL"]
        
        for emergency in pending_emergencies:
            best_amb = None
            best_score = float('-inf')
            
            for amb_id, ambulance in self.ambulances.items():
                # Verificar disponibilidad
                if not self._is_ambulance_available(ambulance):
                    continue
                
                # Calcular puntuación para esta ambulancia
                score = self._calculate_dispatch_score(ambulance, emergency, hospitals)
                
                if score > best_score:
                    best_score = score
                    best_amb = ambulance
            
            # Asignar mejor ambulancia si se encontró
            if best_amb and best_score > 0:
                self._assign_ambulance_to_emergency(best_amb, emergency, hospitals)

    def _is_ambulance_available(self, ambulance: Any) -> bool:
        """
        Verifica si una ambulancia está disponible para asignación.
        
        Args:
            ambulance: Instancia de ambulancia
            
        Returns:
            True si está disponible
        """
        # Verificar avería — nunca asignar una ambulancia averiada
        if getattr(ambulance.mechanical, 'broken', False):
            return False

        # Verificar estado de misión
        mission_status = getattr(ambulance.logistics, 'mission_status', None)
        if mission_status not in [MissionStatus.ACTIVE.value, MissionStatus.INACTIVE.value]:
            return False
        
        # Verificar si está repostando
        if getattr(ambulance.mechanical, 'is_refueling', False):
            return False

        # Verificar si ya está en ruta a gasolinera (flag seteado por _manage_proactive_refueling)
        if getattr(ambulance, 'refuel_pending', False):
            return False
        
        # Verificar combustible suficiente (mínimo 30%)
        if getattr(ambulance.mechanical, 'fuel_level', 0) < 30.0:
            return False
        
        # Verificar que no tenga paciente (a menos que permitamos traslados múltiples)
        if getattr(ambulance.vitals, 'has_patient', False):
            return False
        
        return True

    def _calculate_dispatch_score(self, ambulance: Any, emergency: Dict, 
                                 hospitals: List[Dict]) -> float:
        """
        Calcula puntuación de despacho para una ambulancia.
        
        Args:
            ambulance: Instancia de ambulancia
            emergency: Diccionario de emergencia
            hospitals: Lista de hospitales disponibles
            
        Returns:
            Puntuación de despacho (mayor es mejor)
        """
        # Distancia a la emergencia (km)
        amb_lat = getattr(ambulance.logistics, 'lat', 0)
        amb_lon = getattr(ambulance.logistics, 'lon', 0)
        dist_to_emergency = self._calculate_distance_km(
            amb_lat, amb_lon, emergency["lat"], emergency["lon"]
        )

        # Rechazar si supera el limite operativo (evita asignaciones intercontinentales)
        if dist_to_emergency > MAX_OPERATIONAL_DISTANCE_KM:
            return 0.0

        # Rechazar si la ambulancia está lejos de todos los hospitales
        if not self._is_within_operational_area(amb_lat, amb_lon):
            return 0.0

        # Distancia de emergencia al hospital mas cercano
        if hospitals:
            hospital_distances = [
                self._calculate_distance_km(
                    emergency["lat"], emergency["lon"], h["lat"], h["lon"]
                ) for h in hospitals
            ]
            dist_to_hospital = min(hospital_distances)
        else:
            dist_to_hospital = 5.0  # Default si no hay hospitales
        
        # Distancia total estimada
        total_distance = dist_to_emergency + dist_to_hospital
        
        # Puntuación base (inversamente proporcional a distancia)
        distance_score = 100.0 / (total_distance + 0.1)
        
        # Factor de combustible (penalizar bajo combustible)
        fuel_level = getattr(ambulance.mechanical, 'fuel_level', 100.0)
        fuel_consumption = total_distance * 0.15  # Estimación de consumo
        fuel_factor = 1.0 if fuel_level > fuel_consumption * 2 else 0.3
        
        # Factor de gravedad (priorizar emergencias críticas)
        severity_factors = {
            "CRITICAL": 2.0,
            "HIGH": 1.5,
            "MEDIUM": 1.0,
            "LOW": 0.7
        }
        severity_factor = severity_factors.get(emergency.get("severity", "MEDIUM"), 1.0)
        
        # Factor de estado mecánico
        mech_status = getattr(ambulance.mechanical, 'get_state', lambda: {})().get('status', 'OK')
        status_factors = {
            "OK": 1.0,
            "CAUTION": 0.8,
            "WARNING": 0.5,
            "CRITICAL": 0.1
        }
        status_factor = status_factors.get(mech_status, 0.5)
        
        # Puntuación final
        score = distance_score * fuel_factor * severity_factor * status_factor
        
        # Penalizar ambulancias ya asignadas a otras emergencias
        if getattr(ambulance.logistics, 'mission_status', '') == MissionStatus.IN_USE.value:
            score *= 0.5
        
        return score

    def _assign_ambulance_to_emergency(self, ambulance: Any, emergency: Dict, 
                                      hospitals: List[Dict]) -> None:
        """
        Asigna una ambulancia a una emergencia.
        
        Args:
            ambulance: Ambulancia a asignar
            emergency: Emergencia a atender
            hospitals: Lista de hospitales disponibles
        """
        emergency_id = emergency["id"]
        ambulance_id = ambulance.id

        # Pre-verificar limite de distancia operativa antes de asignar
        amb_lat_pre = getattr(ambulance.logistics, 'lat', 0)
        amb_lon_pre = getattr(ambulance.logistics, 'lon', 0)
        dist_pre = self._calculate_distance_km(
            amb_lat_pre, amb_lon_pre, emergency["lat"], emergency["lon"]
        )
        if dist_pre > MAX_OPERATIONAL_DISTANCE_KM:
            self.log_network(
                f"[DISPATCH] Asignacion bloqueada: {ambulance_id} esta a {dist_pre:.0f} km "
                f"(limite operativo: {MAX_OPERATIONAL_DISTANCE_KM} km)."
            )
            return

        # Actualizar estado de emergencia
        emergency["status"] = "PROCESSING"
        emergency["assigned_ambulance"] = ambulance_id
        emergency["assigned_at"] = time.time()
        
        # Actualizar estado de ambulancia
        if hasattr(ambulance.logistics, 'mission_status'):
            ambulance.logistics.mission_status = MissionStatus.IN_USE.value
        
        # Establecer destino a emergencia
        if hasattr(ambulance.logistics, 'set_destination'):
            ambulance.logistics.set_destination(
                emergency["lat"], emergency["lon"], "EMERGENCY"
            )
        
        # Asignar hospital más cercano para después
        if hospitals:
            # Encontrar hospital más cercano a la emergencia
            nearest_hospital = min(
                hospitals, 
                key=lambda h: self._calculate_distance_km(
                    emergency["lat"], emergency["lon"], h["lat"], h["lon"]
                )
            )
            emergency["hospital_assigned"] = {
                "lat": nearest_hospital["lat"],
                "lon": nearest_hospital["lon"]
            }
        
        # Log
        response_time = emergency["assigned_at"] - emergency["created_at"]
        self.log_network(
            f"[DISPATCH] 🚑 Unidad {ambulance_id} asignada a Urgencia {emergency_id}. "
            f"Tiempo respuesta: {response_time:.1f}s. "
            f"Gravedad: {emergency.get('severity', 'MEDIUM')}"
        )

    def _dispatch_loop(self) -> None:
        """
        Bucle principal de despacho que monitorea estado de emergencias
        y coordina transporte de pacientes.
        """
        while self.running:
            if not self.is_simulating:
                time.sleep(0.5)
                continue
            
            try:
                self._monitor_emergency_progress()
                self._manage_proactive_refueling()
                self._manage_idle_ambulances()
                self._update_statistics()
                
            except Exception as e:
                logger.error(f"Error en bucle de despacho: {e}")
                self.log_network(f"[DISPATCH ERROR] {e}")
            
            time.sleep(0.2)  # 5 Hz

    def _monitor_emergency_progress(self) -> None:
        """Monitorea progreso de emergencias activas."""
        current_time = time.time()
        
        for emergency in list(self.active_emergencies.values()):
            em_id = emergency["id"]
            amb_id = emergency.get("assigned_ambulance")
            
            if not amb_id or amb_id not in self.ambulances:
                continue
                
            ambulance = self.ambulances[amb_id]
            
            # Emergencia en procesamiento (yendo al lugar)
            if emergency["status"] == "PROCESSING":
                self._handle_processing_emergency(emergency, ambulance, current_time)
            
            # Emergencia en transporte (yendo al hospital)
            elif emergency["status"] == "TRANSPORTING":
                self._handle_transporting_emergency(emergency, ambulance, current_time)

            # Ambulancia varada sin combustible: liberar urgencia y reasignar
            mission_now = getattr(ambulance.logistics, 'mission_status', '')
            if mission_now == "STRANDED" and emergency["status"] in ("PROCESSING", "TRANSPORTING"):
                self.log_network(
                    f"[DISPATCH] Unidad {amb_id} varada sin combustible. "
                    f"Reasignando urgencia {em_id}..."
                )
                self._release_ambulance(ambulance)
                emergency["status"] = "INITIATED"
                emergency["assigned_ambulance"] = None
                emergency.pop("assigned_at", None)
                self.evaluate_fleet_assignments()

            # Verificar timeout (15 minutos maximo)
            if current_time - emergency.get("created_at", current_time) > 900:  # 15 minutos
                self.log_network(f"[TIMEOUT] ⏱️ Urgencia {em_id} excedió tiempo máximo de respuesta.")
                emergency["status"] = "TIMEOUT"
                if amb_id in self.ambulances:
                    self._release_ambulance(ambulance)

    def _handle_processing_emergency(self, emergency: Dict, ambulance: Any, 
                                    current_time: float) -> None:
        """Maneja emergencia en estado PROCESSING."""
        em_id = emergency["id"]
        amb_id = ambulance.id
        
        # Verificar si llegó a la emergencia
        if (hasattr(ambulance.logistics, 'destination') and 
            ambulance.logistics.destination is None):
            
            # Ambulancia llegó a emergencia
            emergency["status"] = "ON_SCENE"
            emergency["on_scene_at"] = current_time
            
            # Configurar paciente en ambulancia
            if hasattr(ambulance.vitals, 'set_patient_info'):
                ambulance.vitals.set_patient_info(age=45, has_patient=True)
                ambulance.vitals.patient_status = PatientStatus.CRITICAL
            
            # Asignar hospital destino
            hospital = emergency.get("hospital_assigned")
            if hospital and hasattr(ambulance.logistics, 'set_destination'):
                ambulance.logistics.set_destination(
                    hospital["lat"], hospital["lon"], "HOSPITAL"
                )
                ambulance.logistics.action_message = "Transportando al Hospital"
                
                emergency["status"] = "TRANSPORTING"
                
                distance = self._calculate_distance_km(
                    ambulance.logistics.lat, ambulance.logistics.lon,
                    hospital["lat"], hospital["lon"]
                )
                
                self.log_network(
                    f"[TRANSPORT] 🏥 Unidad {amb_id} transportando paciente al hospital. "
                    f"Distancia: {distance:.1f} km"
                )
            else:
                self.log_network(
                    f"[ERROR] 🏥 No hay hospital asignado para Urgencia {em_id}"
                )

    def _handle_transporting_emergency(self, emergency: Dict, ambulance: Any, 
                                      current_time: float) -> None:
        """Maneja emergencia en estado TRANSPORTING."""
        em_id = emergency["id"]
        amb_id = ambulance.id
        
        # Verificar si llegó al hospital
        if (hasattr(ambulance.logistics, 'destination') and 
            ambulance.logistics.destination is None):
            
            # Paciente entregado en hospital
            emergency["status"] = "RESOLVED"
            emergency["resolved_at"] = current_time
            
            # Liberar ambulancia
            self._release_ambulance(ambulance)
            
            # Actualizar estadísticas
            self.emergencies_handled += 1
            response_time = emergency["resolved_at"] - emergency["created_at"]
            self.total_response_time += response_time
            self.average_response_time = self.total_response_time / self.emergencies_handled
            
            self.log_network(
                f"[RESUELTO] ✅ Urgencia {em_id} resuelta por Unidad {amb_id}. "
                f"Tiempo total: {response_time/60:.1f} min. "
                f"Promedio: {self.average_response_time/60:.1f} min"
            )
            
            # Eliminar emergencia
            if em_id in self.active_emergencies:
                del self.active_emergencies[em_id]
            
            # Re-evaluar asignaciones
            self.evaluate_fleet_assignments()

    def _release_ambulance(self, ambulance: Any) -> None:
        """Libera ambulancia para nuevas asignaciones."""
        if hasattr(ambulance.logistics, 'mission_status'):
            ambulance.logistics.mission_status = MissionStatus.ACTIVE.value
        
        if hasattr(ambulance.vitals, 'set_patient_info'):
            ambulance.vitals.set_patient_info(has_patient=False)
        
        if hasattr(ambulance.logistics, 'action_message'):
            ambulance.logistics.action_message = "Disponible para nuevas asignaciones"

    def _manage_idle_ambulances(self) -> None:
        """Gestiona ambulancias sin asignación.

        Para evitar que todas las ambulancias inactivas de una misma ciudad
        confluyan en el mismo hospital (apareciendo como un único icono en el mapa),
        distribuye las ambulancias entre los hospitales de su área operativa: cada
        ambulancia es enviada al hospital local con menor número de ambulancias
        asignadas actualmente.
        """
        if not self.is_simulating:
            return
        
        hospitals = [p for p in POIS if p.get("type") == "HOSPITAL"]
        if not hospitals:
            return

        # Contar ambulancias cuyo destino actual es cada hospital (para balancear)
        hospital_load: Dict[Tuple[float, float], int] = {
            (h["lat"], h["lon"]): 0 for h in hospitals
        }
        for amb in self.ambulances.values():
            dest = getattr(amb.logistics, 'destination', None)
            dest_type = getattr(amb.logistics, 'destination_type', None)
            if dest and dest_type in ("BASE", "HOSPITAL"):
                key = (round(dest[0], 4), round(dest[1], 4))
                closest_key = min(
                    hospital_load.keys(),
                    key=lambda k: abs(k[0] - dest[0]) + abs(k[1] - dest[1])
                )
                hospital_load[closest_key] = hospital_load.get(closest_key, 0) + 1

        for ambulance in self.ambulances.values():
            # Solo ambulancias activas sin destino y con combustible >= 30%.
            # Las de bajo combustible son gestionadas por _manage_proactive_refueling.
            # Tampoco procesar ambulancias fuera del área operativa (lejos de hospitales).
            if (hasattr(ambulance.logistics, 'mission_status') and 
                ambulance.logistics.mission_status == MissionStatus.ACTIVE.value and
                hasattr(ambulance.logistics, 'destination') and
                ambulance.logistics.destination is None and
                getattr(ambulance.mechanical, 'fuel_level', 100.0) >= 30.0 and
                self._is_within_operational_area(
                    getattr(ambulance.logistics, 'lat', 0.0),
                    getattr(ambulance.logistics, 'lon', 0.0)
                )):
                
                # Verificar si ya está en un hospital
                at_hospital = False
                for h in hospitals:
                    if (hasattr(ambulance.logistics, 'lat') and 
                        hasattr(ambulance.logistics, 'lon')):
                        dist = self._calculate_distance_km(
                            ambulance.logistics.lat, ambulance.logistics.lon,
                            h["lat"], h["lon"]
                        )
                        if dist < 0.5:  # Dentro de 500m
                            at_hospital = True
                            break
                
                if not at_hospital:
                    amb_lat = getattr(ambulance.logistics, 'lat', 0.0)
                    amb_lon = getattr(ambulance.logistics, 'lon', 0.0)

                    # Candidatos: solo hospitales dentro del área operativa de la ambulancia
                    local_hospitals = [
                        h for h in hospitals
                        if self._calculate_distance_km(amb_lat, amb_lon, h["lat"], h["lon"])
                           <= MAX_OPERATIONAL_DISTANCE_KM
                    ]
                    if not local_hospitals:
                        local_hospitals = hospitals  # fallback

                    # Elegir el hospital local con menor carga de ambulancias en route
                    target_hospital = min(
                        local_hospitals,
                        key=lambda h: (
                            hospital_load.get((h["lat"], h["lon"]), 0),
                            self._calculate_distance_km(amb_lat, amb_lon, h["lat"], h["lon"])
                        )
                    )

                    if hasattr(ambulance.logistics, 'set_destination'):
                        ambulance.logistics.set_destination(
                            target_hospital["lat"], target_hospital["lon"], "BASE"
                        )
                        ambulance.logistics.action_message = "Regresando a Base"
                        hospital_load[(target_hospital["lat"], target_hospital["lon"])] = \
                            hospital_load.get((target_hospital["lat"], target_hospital["lon"]), 0) + 1

    def _manage_proactive_refueling(self) -> None:
        """
        Repostaje proactivo: si una ambulancia libre tiene combustible < 20%
        y no esta transportando a un paciente critico, la redirige automaticamente
        a la gasolinera mas cercana antes de aceptar nuevas emergencias.
        """
        if not self.is_simulating:
            return

        gas_stations = [p for p in POIS if p.get("type") == "GAS_STATION"]
        if not gas_stations:
            return

        for ambulance in self.ambulances.values():
            fuel         = getattr(ambulance.mechanical, 'fuel_level',    100.0)
            has_patient  = getattr(ambulance.vitals,     'has_patient',   False)
            mission      = getattr(ambulance.logistics,  'mission_status', '')
            is_refueling = getattr(ambulance.mechanical, 'is_refueling',   False)
            amb_lat      = getattr(ambulance.logistics,  'lat', 0.0)
            amb_lon      = getattr(ambulance.logistics,  'lon', 0.0)

            # Actuar sobre ambulancias activas, sin paciente, combustible < 30%,
            # sin ruta activa y sin repostaje ya en progreso.
            # Umbral en 30% = mismo umbral del dispatcher (_is_ambulance_available),
            # cerrando la zona muerta 20-30% donde las ambulancias quedaban paralizadas.
            # Tampoco repostar ambulancias fuera del área operativa (lejos de hospitales).
            if not (
                fuel < 30.0
                and not has_patient
                and not is_refueling
                and not getattr(ambulance, 'refuel_pending', False)
                and mission == MissionStatus.ACTIVE.value
                and hasattr(ambulance.logistics, 'destination')
                and ambulance.logistics.destination is None
                and self._is_within_operational_area(amb_lat, amb_lon)
            ):
                continue

            if hasattr(ambulance.logistics, 'route_to_nearest'):
                success = ambulance.logistics.route_to_nearest("GAS_STATION")
                if success:
                    ambulance.logistics.mission_status = MissionStatus.INACTIVE.value
                    ambulance.refuel_pending = True          # marca para twin._manage_fuel_and_maintenance
                    ambulance.logistics.action_message = (
                        f"Repostaje preventivo ({fuel:.0f}% restante)"
                    )
                    self.log_network(
                        f"[COMBUSTIBLE] {ambulance.id} — Repostaje proactivo iniciado "
                        f"(combustible al {fuel:.0f}%)."
                    )

    def _update_statistics(self) -> None:
        """Actualiza estadísticas del sistema."""
        # Pueden añadirse más métricas aquí
        pass

    def _calculate_distance_km(self, lat1: float, lon1: float, 
                              lat2: float, lon2: float) -> float:
        """
        Calcula distancia en kilómetros entre dos puntos.
        
        Args:
            lat1, lon1: Coordenadas punto 1
            lat2, lon2: Coordenadas punto 2
            
        Returns:
            Distancia en kilómetros
        """
        # Fórmula de Haversine
        R = 6371.0  # Radio terrestre en km
        
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)
        
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c

    def update_speed_multiplier(self, val: int) -> None:
        """
        Actualiza multiplicador de velocidad de simulación.
        
        Args:
            val: Nuevo multiplicador (1-50)
        """
        self.speed_multiplier = max(1, min(50, val))
        for ambulance in self.ambulances.values():
            if hasattr(ambulance, 'speed_multiplier'):
                ambulance.speed_multiplier = self.speed_multiplier
        
        self.log_network(f"[SISTEMA] ⚡ Reloj temporal ajustado a {self.speed_multiplier}x.")

    def toggle_playback(self) -> None:
        """Alterna estado de reproducción de la simulación."""
        self.is_simulating = not self.is_simulating
        
        for ambulance in self.ambulances.values():
            if hasattr(ambulance, 'is_paused'):
                ambulance.is_paused = not self.is_simulating
        
        if self.is_simulating:
            self.log_network("=== ▶️ SIMULACIÓN INICIADA ===")
            self.evaluate_fleet_assignments()
        else:
            self.log_network("=== ⏸️ SIMULACIÓN PAUSADA ===")

    def clear_all_scenario(self) -> None:
        """Limpia completamente el escenario de simulación."""
        self.log_network("=== 🗑️ LIMPIANDO ESCENARIO... ===")
        
        was_simulating = self.is_simulating
        if was_simulating:
            self.toggle_playback()
        
        # Detener todas las ambulancias
        for ambulance in list(self.ambulances.values()):
            if hasattr(ambulance, 'stop'):
                ambulance.stop()
            if hasattr(ambulance, 'p2p_mesh') and ambulance.p2p_mesh:
                ambulance.p2p_mesh.stop()
        
        # Limpiar estructuras de datos
        self.ambulances.clear()
        
        # Limpiar POIS y JAMS (importados de logistics)
        global POIS, JAMS
        POIS.clear()
        JAMS.clear()
        
        self.active_emergencies.clear()

        # Detener hilos de simulación autónoma
        self._auto_sim_active = False
        self._auto_jam_active = False
        
        # Resetear estadísticas
        self.emergencies_handled = 0
        self.total_response_time = 0.0
        self.average_response_time = 0.0
        
        self.log_network("[SISTEMA] ✅ Escenario limpiado. Listo para nueva simulación.")
        
        if was_simulating:
            self.toggle_playback()

    def toggle_networks(self, mqtt: bool, p2p: bool, http: bool) -> None:
        """
        Habilita/deshabilita canales de comunicación.
        
        Args:
            mqtt: Estado MQTT
            p2p: Estado P2P
            http: Estado HTTP
        """
        self.mqtt_on = mqtt
        self.p2p_on = p2p
        self.http_on = http
        
        for ambulance in self.ambulances.values():
            if hasattr(ambulance, 'mqtt_client') and ambulance.mqtt_client:
                if self.mqtt_on and not ambulance.mqtt_client.is_connected():
                    ambulance.mqtt_client.connect()
                elif not self.mqtt_on and ambulance.mqtt_client.is_connected():
                    ambulance.mqtt_client.disconnect()
            
            if hasattr(ambulance, 'p2p_enabled'):
                ambulance.p2p_enabled = self.p2p_on
            
            if hasattr(ambulance, 'http_enabled'):
                ambulance.http_enabled = self.http_on
        
        status_msg = (
            f"--- CONFIGURACIÓN RED ---\n"
            f"MQTT: {'🟢 ACTIVADO' if self.mqtt_on else '🔴 DESACTIVADO'}\n"
            f"P2P:  {'🟢 ACTIVADO' if self.p2p_on else '🔴 DESACTIVADO'}\n"
            f"HTTP: {'🟢 ACTIVADO' if self.http_on else '🔴 DESACTIVADO'}"
        )
        self.log_network(status_msg)

    def stop(self) -> None:
        """Detiene completamente el motor de simulación."""
        self.running = False
        self.is_simulating = False
        
        for ambulance in list(self.ambulances.values()):
            if hasattr(ambulance, 'stop'):
                ambulance.stop()
            if hasattr(ambulance, 'p2p_mesh') and ambulance.p2p_mesh:
                ambulance.p2p_mesh.stop()
        
        logger.info("SimulatorEngine detenido")

    def get_statistics(self) -> Dict[str, Any]:
        """
        Retorna estadísticas actuales del sistema.
        
        Returns:
            Diccionario con estadísticas
        """
        return {
            "total_ambulances": len(self.ambulances),
            "active_emergencies": len(self.active_emergencies),
            "emergencies_handled": self.emergencies_handled,
            "average_response_time_min": round(self.average_response_time / 60, 1) if self.emergencies_handled > 0 else 0,
            "is_simulating": self.is_simulating,
            "speed_multiplier": self.speed_multiplier,
            "network_status": {
                "mqtt": self.mqtt_on,
                "p2p": self.p2p_on,
                "http": self.http_on
            }
        }

    def get_ambulance_details(self, ambulance_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene detalles de una ambulancia específica.
        
        Args:
            ambulance_id: ID de la ambulancia
            
        Returns:
            Diccionario con detalles o None si no existe
        """
        if ambulance_id not in self.ambulances:
            return None
        
        ambulance = self.ambulances[ambulance_id]
        
        details = {
            "id": ambulance_id,
            "running": getattr(ambulance, 'running', False),
            "paused": getattr(ambulance, 'is_paused', False),
            "speed_multiplier": getattr(ambulance, 'speed_multiplier', 1.0),
            "communication_errors": getattr(ambulance, 'communication_errors', 0) if hasattr(ambulance, 'communication_errors') else 0,
            "operational_hours": getattr(ambulance, 'operational_hours', 0.0) if hasattr(ambulance, 'operational_hours') else 0.0
        }
        
        # Añadir estados de motores si están disponibles
        if hasattr(ambulance, 'get_detailed_status'):
            details.update(ambulance.get_detailed_status())
        
        return details

    # ------------------------------------------------------------------
    # PRESETS Y SIMULACIÓN AUTÓNOMA
    # ------------------------------------------------------------------

    def set_event_severity(self, multiplier: float) -> None:
        """Ajusta el multiplicador de frecuencia de eventos autónomos (0.2–5.0)."""
        self.event_severity = max(0.1, min(10.0, float(multiplier)))
        self.log_network(f"[AUTO-SIM] Frecuencia de eventos ajustada a {self.event_severity:.1f}x")

    def set_fault_frequency(self, multiplier: float) -> None:
        """Ajusta el multiplicador de frecuencia de inyección de fallos mecánicos (0.1–10.0)."""
        self.fault_frequency = max(0.1, min(10.0, float(multiplier)))
        self.log_network(f"[AUTO-SIM] Frecuencia de averías ajustada a {self.fault_frequency:.1f}x")

    def load_preset(self, preset_name: str) -> bool:
        """
        Carga un preset de escenario (hospitales, gasolineras, ambulancias).
        Limpia el escenario actual antes de cargar.
        """
        if preset_name not in SCENARIO_PRESETS:
            self.log_network(f"[SISTEMA] Preset '{preset_name}' no encontrado.")
            return False

        preset = SCENARIO_PRESETS[preset_name]
        self.log_network(f"[SISTEMA] Cargando preset: {preset['name']}...")

        # Limpiar escenario actual
        self.clear_all_scenario()

        # Cargar hospitales
        for lat, lon, name in preset["hospitals"]:
            add_poi("HOSPITAL", lat, lon, name)
            self.log_network(f"[PRESET] 🏥 {name} en ({lat:.4f}, {lon:.4f})")

        # Cargar gasolineras
        for lat, lon, name in preset["gas_stations"]:
            add_poi("GAS_STATION", lat, lon, name)
            self.log_network(f"[PRESET] ⛽ {name} en ({lat:.4f}, {lon:.4f})")

        # Desplegar ambulancias
        for lat, lon in preset["ambulance_positions"]:
            try:
                am_id = self.spawn_ambulance(lat, lon)
                self.log_network(f"[PRESET] 🚑 {am_id} en ({lat:.4f}, {lon:.4f})")
            except Exception as e:
                logger.warning(f"[PRESET] Error desplegando ambulancia: {e}")

        self.log_network(
            f"[SISTEMA] ✅ Preset '{preset['name']}' cargado: "
            f"{len(preset['hospitals'])} hospitales, "
            f"{len(preset['gas_stations'])} gasolineras, "
            f"{len(preset['ambulance_positions'])} ambulancias."
        )
        return True

    def load_preset_additive(self, preset_name: str) -> bool:
        """
        Carga un preset de escenario de forma aditiva (sin limpiar el escenario actual).
        Permite cargar múltiples presets simultáneamente.
        """
        if preset_name not in SCENARIO_PRESETS:
            self.log_network(f"[SISTEMA] Preset '{preset_name}' no encontrado.")
            return False

        preset = SCENARIO_PRESETS[preset_name]
        self.log_network(f"[SISTEMA] Añadiendo preset: {preset['name']}...")

        for lat, lon, name in preset["hospitals"]:
            add_poi("HOSPITAL", lat, lon, name)
            self.log_network(f"[PRESET] 🏥 {name} en ({lat:.4f}, {lon:.4f})")

        for lat, lon, name in preset["gas_stations"]:
            add_poi("GAS_STATION", lat, lon, name)
            self.log_network(f"[PRESET] ⛽ {name} en ({lat:.4f}, {lon:.4f})")

        for lat, lon in preset["ambulance_positions"]:
            try:
                am_id = self.spawn_ambulance(lat, lon)
                self.log_network(f"[PRESET] 🚑 {am_id} en ({lat:.4f}, {lon:.4f})")
            except Exception as e:
                logger.warning(f"[PRESET] Error desplegando ambulancia: {e}")

        self.log_network(
            f"[SISTEMA] ✅ Preset '{preset['name']}' añadido: "
            f"{len(preset['hospitals'])} hospitales, "
            f"{len(preset['gas_stations'])} gasolineras, "
            f"{len(preset['ambulance_positions'])} ambulancias."
        )
        return True

    def start_auto_simulation(self) -> tuple:
        """
        Inicia la generación automática de eventos (emergencias, atascos, anomalías).
        Requiere que existan hospitales y ambulancias en el mapa.

        Returns:
            (success: bool, message: str)
        """
        if getattr(self, '_auto_sim_active', False):
            self.log_network("[AUTO-SIM] Simulación autónoma ya activa.")
            return False, "La simulación autónoma ya está activa."

        hospitals = [p for p in POIS if p.get("type") == "HOSPITAL"]
        if not hospitals:
            msg = "No hay hospitales en el mapa. Carga un preset o añade hospitales manualmente."
            self.log_network(f"[AUTO-SIM] ⚠️ {msg}")
            return False, msg

        if not self.ambulances:
            msg = "No hay ambulancias desplegadas. Carga un preset primero."
            self.log_network(f"[AUTO-SIM] ⚠️ {msg}")
            return False, msg

        self.log_network("[AUTO-SIM] Iniciando generación automática de eventos...")

        if not self.is_simulating:
            self.toggle_playback()

        # Hilo generador de emergencias + anomalías
        self._auto_sim_active = True
        self._auto_sim_thread = threading.Thread(
            target=self._auto_emergency_loop, daemon=True, name="AutoSimThread"
        )
        self._auto_sim_thread.start()

        # Hilo generador de atascos
        self._auto_jam_active = True
        self._auto_jam_thread = threading.Thread(
            target=self._auto_jam_loop, daemon=True, name="AutoJamThread"
        )
        self._auto_jam_thread.start()

        # Hilo monitor de RUL y averías
        self._rul_monitor_active = True
        self._rul_warned = set()
        self._rul_monitor_thread = threading.Thread(
            target=self._rul_monitor_loop, daemon=True, name="RULMonitorThread"
        )
        self._rul_monitor_thread.start()

        msg = "Simulación autónoma activa. Emergencias y atascos se generarán automáticamente."
        self.log_network(f"[AUTO-SIM] ✅ {msg}")
        return True, msg

    def stop_auto_simulation(self) -> None:
        """Detiene la generación automática de eventos."""
        self._auto_sim_active = False
        self._auto_jam_active = False
        self._rul_monitor_active = False
        self.log_network("[AUTO-SIM] Generación automática de eventos detenida.")

    def _auto_emergency_loop(self) -> None:
        """Genera emergencias aleatorias cerca de hospitales e inyecta anomalías IA."""
        last_anomaly_injection = time.time()
        ANOMALY_INTERVAL = 120.0
        FAULT_TYPES = ["overheating", "low_oil", "brake_failure", "battery_drain", "flat_tire"]
        SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

        try:
            while self.running and getattr(self, '_auto_sim_active', False):
                if not self.is_simulating:
                    time.sleep(1.0)
                    continue

                try:
                    sleep_s = random.uniform(45.0, 75.0) / max(1, self.speed_multiplier) / max(0.1, self.event_severity)
                    time.sleep(sleep_s)

                    if not self.is_simulating or not self.running:
                        break

                    coords = self._generate_random_coords_near_pois(radius_km=10.0)
                    if coords is None:
                        time.sleep(5.0)
                        continue

                    em_lat, em_lon = coords
                    severity = random.choice(SEVERITIES)
                    em_id = self.spawn_emergency(em_lat, em_lon, severity)
                    self.log_network(
                        f"[AUTO-SIM] Emergencia auto-generada {em_id} "
                        f"({severity}) en ({em_lat:.4f}, {em_lon:.4f})"
                    )

                    now = time.time()
                    if (now - last_anomaly_injection) >= ANOMALY_INTERVAL / max(0.1, self.fault_frequency) and self.ambulances:
                        target_id = random.choice(list(self.ambulances.keys()))
                        target_amb = self.ambulances[target_id]
                        fault = random.choice(FAULT_TYPES)
                        if hasattr(target_amb.mechanical, 'inject_fault'):
                            target_amb.mechanical.inject_fault(fault)
                            self.log_network(
                                f"[AUTO-SIM] Anomalía '{fault}' inyectada en {target_id}"
                            )
                        last_anomaly_injection = now

                except Exception as exc:
                    logger.error(f"[AUTO-SIM] Error en bucle automático: {exc}")
                    time.sleep(5.0)
        finally:
            self._auto_sim_active = False
            self.log_network("[AUTO-SIM] Hilo de emergencias automáticas finalizado.")

    def _rul_monitor_loop(self) -> None:
        """Monitoriza el RUL de cada ambulancia y reacciona ante averías graves y RUL crítico."""
        try:
            while self.running and getattr(self, '_rul_monitor_active', False):
                time.sleep(5.0)  # Comprobar cada 5s de tiempo real

                if not self.is_simulating:
                    continue

                for amb_id, ambulance in list(self.ambulances.items()):
                    try:
                        mission_status = getattr(ambulance.logistics, 'mission_status', None)

                        # — Auto-reparación: ambulancia en mantenimiento con temporizador —
                        if mission_status == MissionStatus.MAINTENANCE.value:
                            if amb_id not in self._repair_timers:
                                # Sin temporizador: registrar ahora para auto-reparar tras la duración
                                self._repair_timers[amb_id] = time.time()
                            repair_started = self._repair_timers[amb_id]
                            is_breakdown = getattr(ambulance.mechanical, 'broken', False)
                            base_duration = 180.0 if is_breakdown else 120.0
                            repair_duration = max(10.0, base_duration / max(1, self.speed_multiplier))
                            if (time.time() - repair_started) >= repair_duration:
                                ambulance.mechanical.perform_maintenance()
                                ambulance.logistics.mission_status = MissionStatus.ACTIVE.value
                                ambulance.logistics.action_message = "✅ Mantenimiento completado. Disponible para servicio."
                                self._repair_timers.pop(amb_id, None)
                                self._rul_warned.discard(amb_id)
                                self._rul_warned.discard(f"{amb_id}:anomaly")
                                self.log_network(
                                    f"[MANTENIMIENTO] ✅ {amb_id}: Reparación automática completada. Unidad operativa."
                                )
                            continue  # No procesar otros checks mientras está en mantenimiento

                        # — Avería total: ambulancia dañada y no está ya en MAINTENANCE —
                        if (getattr(ambulance.mechanical, 'broken', False)
                                and mission_status != MissionStatus.MAINTENANCE.value):
                            self._handle_breakdown(amb_id, ambulance)
                            continue

                        # — RUL CRÍTICO: vida útil restante < 8h —
                        rul_data = ambulance.current_state.get("ai_prediction", {}).get("rul", {})
                        alert_level = rul_data.get("alert_level", "NORMAL")
                        hours_remaining = rul_data.get("hours_remaining", 120.0)

                        if (alert_level == "CRÍTICO"
                                and mission_status not in (
                                    MissionStatus.MAINTENANCE.value,
                                    MissionStatus.STRANDED.value,
                                )):
                            self._handle_predictive_maintenance(amb_id, ambulance)
                            self._rul_warned.discard(amb_id)

                        elif alert_level == "ALERTA" and amb_id not in self._rul_warned:
                            self.log_network(
                                f"[RUL] ⚠️ {amb_id}: RUL en ALERTA — "
                                f"{hours_remaining:.1f}h restantes de motor. "
                                f"Asegúrese de planificar mantenimiento pronto."
                            )
                            self._rul_warned.add(amb_id)

                        elif alert_level in ("NORMAL", "PRECAUCIÓN"):
                            self._rul_warned.discard(amb_id)

                        # — Predictor IA: anomalía mecánica detectada con alta confianza —
                        anomaly_data = ambulance.current_state.get("ai_prediction", {})
                        anomaly_key = f"{amb_id}:anomaly"
                        anomaly_score = float(anomaly_data.get("score", 0.0))
                        if (
                            anomaly_data.get("anomaly", False)
                            and anomaly_score >= 0.65
                            and mission_status not in (
                                MissionStatus.MAINTENANCE.value,
                                MissionStatus.STRANDED.value,
                            )
                            and anomaly_key not in self._rul_warned
                        ):
                            details = anomaly_data.get("details") or "anomalía estadística detectada"
                            self.log_network(
                                f"[IA] 🔍 {amb_id}: Predictor detecta anomalía mecánica "
                                f"(confianza={anomaly_score:.2f}) — {details}"
                            )
                            self._rul_warned.add(anomaly_key)
                            # Acción preventiva cuando la confianza es muy alta y la unidad está libre
                            engine_hours = float(
                            ambulance.current_state.get("mechanical", {}).get("engine_hours", 0.0)
                        )
                        anomaly_details = str(anomaly_data.get("details", ""))
                        has_specific_breach = (
                            bool(anomaly_details)
                            and anomaly_details != "Patrón estadístico anómalo detectado"
                        )
                        if (
                                anomaly_score >= 0.85
                                and mission_status == MissionStatus.ACTIVE.value
                                and not getattr(ambulance, 'refuel_pending', False)
                                and engine_hours >= 1.0  # ignorar ambulancias recién desplegadas
                                and has_specific_breach   # requiere fallo medible, no solo patrón estadístico
                            ):
                                self.log_network(
                                    f"[IA] 🟡 {amb_id}: Alta confianza ({anomaly_score:.2f}) — "
                                    f"enviando preventivamente a revisión mecánica."
                                )
                                try:
                                    ambulance.logistics.route_to_nearest("HOSPITAL")
                                except Exception:
                                    pass
                                ambulance.logistics.mission_status = MissionStatus.MAINTENANCE.value
                                ambulance.logistics.action_message = "🟡 REVISIÓN PREVENTIVA — Anomalía IA detectada. Revisión automática en curso (~2 min)."
                                self._repair_timers[amb_id] = time.time()
                        elif not anomaly_data.get("anomaly", False):
                            self._rul_warned.discard(anomaly_key)

                    except Exception as exc:
                        logger.warning(f"[RUL-MONITOR] Error comprobando {amb_id}: {exc}")

        except Exception as exc:
            logger.error(f"[RUL-MONITOR] Error en bucle RUL: {exc}")
        finally:
            self._rul_monitor_active = False
            self.log_network("[RUL-MONITOR] Monitor RUL finalizado.")

    def _handle_breakdown(self, amb_id: str, ambulance: Any) -> None:
        """Gestiona una avería grave: pone la ambulancia en MAINTENANCE, reasigna emergencias."""
        self.log_network(
            f"[AVERÍA] 🔴 {amb_id} ha sufrido una avería grave. "
            f"Motor inmovilizado — enviando al hospital más cercano para reparación."
        )

        # Aseguramos estado de fallo
        ambulance.mechanical.broken = True
        ambulance.mechanical.engine_on = False
        ambulance.logistics.speed = 0.0
        ambulance.logistics.acceleration = 0.0

        # Reasignar cualquier emergencia que tuviera asignada
        for em in self.active_emergencies.values():
            if em.get("assigned_ambulance") == amb_id and em["status"] not in ("COMPLETED", "CANCELLED"):
                em["assigned_ambulance"] = None
                em["status"] = "INITIATED"
                self.log_network(
                    f"[URGENCIA {em['id']}] ⚡ Reasignando — ambulancia {amb_id} averiada."
                )

        # Enrutar al hospital más cercano
        try:
            ambulance.logistics.route_to_nearest("HOSPITAL")
        except Exception:
            pass  # Si el enrutamiento falla, igualmente ponemos MAINTENANCE

        ambulance.logistics.mission_status = MissionStatus.MAINTENANCE.value
        ambulance.logistics.action_message = "🔴 AVERIADA — Reparación automática en curso (~3 min)."
        self._repair_timers[amb_id] = time.time()

        # Intentar reasignar las emergencias huérfanas a otra unidad
        self.evaluate_fleet_assignments()

    def _handle_predictive_maintenance(self, amb_id: str, ambulance: Any) -> None:
        """Envía preventivamente la ambulancia a mantenimiento cuando el RUL es crítico."""
        mission_status = getattr(ambulance.logistics, 'mission_status', None)
        if mission_status != MissionStatus.ACTIVE.value:
            # Solo actuar si está en ACTIVE (no en medio de una misión o repostaje)
            return

        rul_data = ambulance.current_state.get("ai_prediction", {}).get("rul", {})
        hours_remaining = rul_data.get("hours_remaining", 0.0)

        self.log_network(
            f"[RUL] 🟠 {amb_id}: RUL CRÍTICO ({hours_remaining:.1f}h restantes). "
            f"Enviando preventivamente a hospital para mantenimiento urgente."
        )

        try:
            ambulance.logistics.route_to_nearest("HOSPITAL")
        except Exception:
            pass

        ambulance.logistics.mission_status = MissionStatus.MAINTENANCE.value
        ambulance.logistics.action_message = "🟠 MANTENIMIENTO PREVENTIVO — RUL crítico. Reparación automática en curso (~2 min)."
        self._repair_timers[amb_id] = time.time()

    def _auto_jam_loop(self) -> None:
        """Genera y elimina atascos aleatorios cerca de hospitales."""
        MAX_JAMS = max(2, round(2 * self.event_severity))
        JAM_CAUSES = [
            "accidente de tráfico",
            "obras en calzada",
            "avería de vehículo",
            "control policial",
            "manifestación",
        ]
        managed_jams: List[Tuple[float, float, float]] = []

        try:
            while self.running and getattr(self, '_auto_jam_active', False):
                if not self.is_simulating:
                    time.sleep(2.0)
                    continue

                now = time.time()

                # Eliminar atascos caducados
                still_active = []
                for jlat, jlon, expiry in managed_jams:
                    if now >= expiry:
                        removed = remove_jam(jlat, jlon, threshold=0.002)
                        if removed:
                            self.log_network(
                                f"[TRÁFICO] Atasco disuelto en ({jlat:.4f}, {jlon:.4f})"
                            )
                    else:
                        still_active.append((jlat, jlon, expiry))
                managed_jams = still_active

                # Crear nuevo atasco si hay hueco
                if len(managed_jams) < MAX_JAMS:
                    coords = self._generate_random_coords_near_pois(radius_km=8.0)
                    if coords:
                        jlat, jlon = coords
                        severity = round(random.uniform(0.5, 1.0), 2)
                        cause = random.choice(JAM_CAUSES)
                        radius = round(random.uniform(0.003, 0.007), 4)
                        duration_s = random.uniform(60.0, 240.0)

                        add_jam(jlat, jlon, radius=radius, severity=severity, cause=cause)
                        managed_jams.append((jlat, jlon, now + duration_s))
                        self.log_network(
                            f"[TRÁFICO] 🚧 Nuevo atasco: {cause} en ({jlat:.4f}, {jlon:.4f}) "
                            f"— severidad {severity:.0%}, duración ~{duration_s/60:.1f} min"
                        )

                wait_s = random.uniform(100.0, 180.0) / max(1, math.sqrt(self.speed_multiplier)) / max(0.1, self.event_severity)
                time.sleep(wait_s)

        except Exception as exc:
            logger.error(f"[AUTO-JAM] Error en bucle de atascos: {exc}")
        finally:
            for jlat, jlon, _ in managed_jams:
                remove_jam(jlat, jlon, threshold=0.002)
            self._auto_jam_active = False
            self.log_network("[AUTO-JAM] Hilo de atascos automáticos finalizado.")

    def _generate_random_coords_near_pois(self, radius_km: float = 10.0) -> Optional[Tuple[float, float]]:
        """Genera coordenadas aleatorias cerca de los hospitales existentes en el mapa.

        Agrupa los hospitales en clústeres geográficos (radio ~200 km) para que,
        cuando haya múltiples presets de ciudades lejanas cargados simultáneamente
        (p.ej. Madrid + Barcelona + Ciudad de México), los eventos se distribuyan de
        forma equitativa entre todas las ciudades y nunca aparezcan en el océano
        (como ocurriría al usar el centroide global de todos los hospitales).

        Algoritmo:
          1. Clusterizar hospitales: cada nuevo hospital se añade al primer clúster
             cuyo centroide se encuentre a ≤ CLUSTER_RADIUS_KM; si no hay ninguno,
             abre un nuevo clúster.
          2. Elegir un clúster al azar (distribución uniforme entre ciudades).
          3. Elegir un hospital al azar dentro del clúster.
          4. Generar un punto aleatorio a ≤ radius_km del hospital elegido.
        """
        hospitals = [p for p in POIS if p.get("type") == "HOSPITAL"]
        if not hospitals:
            return None

        # Agrupar hospitales en clústeres geográficos (una entrada por ciudad/área)
        CLUSTER_RADIUS_KM = 200.0
        clusters: List[List[Dict]] = []
        for h in hospitals:
            placed = False
            for cluster in clusters:
                # Centroide aproximado del clúster
                clat = sum(m["lat"] for m in cluster) / len(cluster)
                clon = sum(m["lon"] for m in cluster) / len(cluster)
                if self._calculate_distance_km(h["lat"], h["lon"], clat, clon) <= CLUSTER_RADIUS_KM:
                    cluster.append(h)
                    placed = True
                    break
            if not placed:
                clusters.append([h])

        # Elegir un clúster al azar (1 voto por ciudad, sin importar cuántos hospitales tenga)
        chosen_cluster = random.choice(clusters)
        center = random.choice(chosen_cluster)
        center_lat, center_lon = center["lat"], center["lon"]

        R = 6371.0

        distance_km = random.uniform(0.5, radius_km)
        bearing_rad = random.uniform(0.0, 2.0 * math.pi)

        lat1 = math.radians(center_lat)
        lon1 = math.radians(center_lon)

        lat2 = math.asin(
            math.sin(lat1) * math.cos(distance_km / R)
            + math.cos(lat1) * math.sin(distance_km / R) * math.cos(bearing_rad)
        )
        lon2 = lon1 + math.atan2(
            math.sin(bearing_rad) * math.sin(distance_km / R) * math.cos(lat1),
            math.cos(distance_km / R) - math.sin(lat1) * math.sin(lat2)
        )

        return round(math.degrees(lat2), 6), round(math.degrees(lon2), 6)