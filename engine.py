import random
import time
import math
import uuid
import threading
import logging
from typing import Dict, List, Optional, Any, Tuple, Callable
from main import launch_ambulance
from telemetry.logistics import POIS, JAMS, MissionStatus, add_poi

# Distancia maxima operativa: asignaciones mas largas son rechazadas automaticamente
MAX_OPERATIONAL_DISTANCE_KM = 150.0

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
        self.mqtt_on = True
        self.p2p_on = True
        self.http_on = True
        
        self.log_callback = log_callback or self._default_logger
        
        # Estadísticas
        self.emergencies_handled = 0
        self.total_response_time = 0.0
        self.average_response_time = 0.0
        
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
            
            # Estado inicial: ir a gasolinera si hay poca gasolina
            if hasattr(self.ambulances[am_id].logistics, 'route_to_nearest'):
                self.ambulances[am_id].logistics.route_to_nearest("GAS_STATION")
            
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
                ambulance.vitals.patient_status = "CRITICAL"
            
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
        """Gestiona ambulancias sin asignación."""
        if not self.is_simulating:
            return
        
        hospitals = [p for p in POIS if p.get("type") == "HOSPITAL"]
        if not hospitals:
            return
        
        for ambulance in self.ambulances.values():
            # Solo ambulancias activas sin destino y con combustible >= 30%.
            # Las de bajo combustible son gestionadas por _manage_proactive_refueling,
            # que ya corre antes en el loop. Sin este guard, idle ruteaba a BASE
            # ambulancias en la zona muerta 20-30% que el dispatcher rechaza,
            # dejandolas paralizadas indefinidamente.
            if (hasattr(ambulance.logistics, 'mission_status') and 
                ambulance.logistics.mission_status == MissionStatus.ACTIVE.value and
                hasattr(ambulance.logistics, 'destination') and
                ambulance.logistics.destination is None and
                getattr(ambulance.mechanical, 'fuel_level', 100.0) >= 30.0):
                
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
                    # Enrutar al hospital más cercano
                    nearest_hospital = min(
                        hospitals,
                        key=lambda h: self._calculate_distance_km(
                            ambulance.logistics.lat, ambulance.logistics.lon,
                            h["lat"], h["lon"]
                        )
                    )
                    
                    if hasattr(ambulance.logistics, 'set_destination'):
                        ambulance.logistics.set_destination(
                            nearest_hospital["lat"], nearest_hospital["lon"], "BASE"
                        )
                        ambulance.logistics.action_message = "Regresando a Base"

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

            # Actuar sobre ambulancias activas, sin paciente, combustible < 30%,
            # sin ruta activa y sin repostaje ya en progreso.
            # Umbral en 30% = mismo umbral del dispatcher (_is_ambulance_available),
            # cerrando la zona muerta 20-30% donde las ambulancias quedaban paralizadas.
            if not (
                fuel < 30.0
                and not has_patient
                and not is_refueling
                and not getattr(ambulance, 'refuel_pending', False)
                and mission == MissionStatus.ACTIVE.value
                and hasattr(ambulance.logistics, 'destination')
                and ambulance.logistics.destination is None
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
    # MODO DE SIMULACION AUTONOMA
    # ------------------------------------------------------------------

    def start_auto_simulation(self) -> None:
        """
        Inicia el modo de simulacion autonoma con infraestructura real de Madrid:
          - 3 hospitales reales + 2 gasolineras predefinidas
          - 4 ambulancias distribuidas por la capital
          - Hilo daemon que genera emergencias aleatorias cada 20-30 segundos
          - Inyeccion periodica de anomalias mecanicas para demostrar el predictor IA
        """
        # Evitar doble inicializacion: si el hilo ya corre, notificar y salir
        if getattr(self, '_auto_sim_active', False):
            self.log_network("[AUTO-SIM] Hilo de simulacion automatica ya activo.")
            return

        self.log_network("[AUTO-SIM] Iniciando simulacion autonoma de Madrid...")

        # --- 1. Hospitales reales de Madrid ---
        madrid_hospitals = [
            (40.4812, -3.6868, "Hospital La Paz"),
            (40.4210, -3.6716, "Hospital Gregorio Maranon"),
            (40.3764, -3.6977, "Hospital 12 de Octubre"),
        ]
        for lat, lon, name in madrid_hospitals:
            add_poi("HOSPITAL", lat, lon, name)
            self.log_network(f"[AUTO-SIM] {name} registrado en ({lat:.4f}, {lon:.4f})")

        # --- 2. Gasolineras predefinidas ---
        madrid_gas = [
            (40.4500, -3.6900, "Repsol Castellana"),
            (40.4070, -3.6930, "Cepsa Atocha"),
        ]
        for lat, lon, name in madrid_gas:
            add_poi("GAS_STATION", lat, lon, name)
            self.log_network(f"[AUTO-SIM] Gasolinera {name} registrada en ({lat:.4f}, {lon:.4f})")

        # --- 3. Desplegar 4 ambulancias repartidas por Madrid ---
        initial_positions = [
            (40.4700, -3.7200),  # Noroeste (Moncloa)
            (40.4300, -3.6900),  # Centro-sur (Lavapies)
            (40.4600, -3.6500),  # Este (Salamanca)
            (40.4000, -3.7100),  # Sur (Carabanchel)
        ]
        for lat, lon in initial_positions:
            try:
                am_id = self.spawn_ambulance(lat, lon)
                self.log_network(
                    f"[AUTO-SIM] Unidad {am_id} desplegada en ({lat:.4f}, {lon:.4f})"
                )
            except Exception as exc:
                logger.warning(f"[AUTO-SIM] No se pudo desplegar ambulancia: {exc}")

        # --- 4. Activar simulacion ---
        if not self.is_simulating:
            self.toggle_playback()

        # --- 5. Iniciar hilo generador de emergencias ---
        self._auto_sim_active = True
        self._auto_sim_thread = threading.Thread(
            target=self._auto_emergency_loop,
            daemon=True,
            name="AutoSimThread"
        )
        self._auto_sim_thread.start()
        self.log_network(
            "[AUTO-SIM] Simulacion autonoma activa. "
            "Emergencias cada 20-30s, anomalias IA cada 2 min."
        )

    def _auto_emergency_loop(self) -> None:
        """
        Bucle daemon: genera emergencias aleatorias e inyecta anomalias mecanicas
        periodicas para que el predictor IA pueda activarse y verse en el frontend.
        """
        last_anomaly_injection = time.time()
        ANOMALY_INTERVAL = 120.0  # segundos entre inyecciones de anomalia
        FAULT_TYPES = ["overheating", "low_oil", "brake_failure", "battery_drain"]
        SEVERITIES   = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

        try:
            while self.running and getattr(self, '_auto_sim_active', False):
                if not self.is_simulating:
                    time.sleep(1.0)
                    continue

                try:
                    # Esperar 20-30 s (acelerado por speed_multiplier)
                    sleep_s = random.uniform(20.0, 30.0) / max(1, self.speed_multiplier)
                    time.sleep(sleep_s)

                    if not self.is_simulating or not self.running:
                        break

                    # Emergencia aleatoria dentro de ~10 km del centro de Madrid
                    em_lat, em_lon = self._generate_random_madrid_coords(radius_km=10.0)
                    severity = random.choice(SEVERITIES)
                    em_id = self.spawn_emergency(em_lat, em_lon, severity)
                    self.log_network(
                        f"[AUTO-SIM] Emergencia auto-generada {em_id} "
                        f"({severity}) en ({em_lat:.4f}, {em_lon:.4f})"
                    )

                    # Inyeccion periodica de anomalia para demostrar el predictor IA
                    now = time.time()
                    if (now - last_anomaly_injection) >= ANOMALY_INTERVAL and self.ambulances:
                        target_id = random.choice(list(self.ambulances.keys()))
                        target_amb = self.ambulances[target_id]
                        fault = random.choice(FAULT_TYPES)
                        if hasattr(target_amb.mechanical, 'inject_fault'):
                            target_amb.mechanical.inject_fault(fault)
                            self.log_network(
                                f"[AUTO-SIM] Anomalia '{fault}' inyectada en {target_id} "
                                f"- Predictor IA deberia detectarla en breve."
                            )
                        last_anomaly_injection = now

                except Exception as exc:
                    logger.error(f"[AUTO-SIM] Error en bucle automatico: {exc}")
                    self.log_network(f"[AUTO-SIM] \u26a0\ufe0f Error en iteracion del bucle: {exc}")
                    time.sleep(5.0)
        finally:
            self._auto_sim_active = False
            self.log_network("[AUTO-SIM] Hilo de simulacion autonoma finalizado.")

    def _generate_random_madrid_coords(self, radius_km: float = 10.0) -> tuple:
        """
        Genera coordenadas aleatorias dentro de un radio dado desde el centro de Madrid.

        Args:
            radius_km: Radio maximo en kilometros.

        Returns:
            (lat, lon) como floats redondeados a 6 decimales.
        """
        CENTER_LAT = 40.4168
        CENTER_LON = -3.7038
        R = 6371.0  # Radio terrestre en km

        distance_km = random.uniform(0.5, radius_km)
        bearing_rad = random.uniform(0.0, 2.0 * math.pi)

        lat1 = math.radians(CENTER_LAT)
        lon1 = math.radians(CENTER_LON)

        lat2 = math.asin(
            math.sin(lat1) * math.cos(distance_km / R)
            + math.cos(lat1) * math.sin(distance_km / R) * math.cos(bearing_rad)
        )
        lon2 = lon1 + math.atan2(
            math.sin(bearing_rad) * math.sin(distance_km / R) * math.cos(lat1),
            math.cos(distance_km / R) - math.sin(lat1) * math.sin(lat2)
        )

        return round(math.degrees(lat2), 6), round(math.degrees(lon2), 6)