import time
import uuid
import threading
import logging
from typing import Dict, Any, Optional, Callable
from telemetry.mechanical import MechanicalEngine
from telemetry.vitals import VitalsEngine, PatientStatus
from telemetry.logistics import LogisticsEngine
from telemetry.ai_predictor import predictor as ai_predictor

class AmbulanceTwin:
    """
    Gemelo digital de una ambulancia que simula estado mecánico, constantes vitales
    y logística en tiempo real, con comunicación redundante.
    """
    
    def __init__(self, am_id: Optional[str] = None, 
                 log_callback: Optional[Callable[[str], None]] = None):
        """
        Inicializa una nueva instancia de ambulancia digital.
        
        Args:
            am_id: Identificador único de la ambulancia
            log_callback: Función de callback para logging
        """
        self.id = am_id or f"AMB-{uuid.uuid4()[:8]}"
        self.log_callback = log_callback or self._default_logger
        
        # Motores de simulación
        self.mechanical = MechanicalEngine()
        self.vitals = VitalsEngine()
        self.logistics = LogisticsEngine()
        
        # Handlers de comunicación (inyectados después)
        self.mqtt_client = None
        self.https_client = None
        self.p2p_mesh = None
        
        # Estado de ejecución
        self.running = False
        self.is_paused = False
        self._thread: Optional[threading.Thread] = None
        
        # Configuración de comunicaciones
        self.p2p_enabled = True
        self.http_enabled = True
        self.speed_multiplier = 1.0
        
        # Estado actual y métricas
        self.current_state: Dict[str, Any] = {}
        self.last_https_sync = time.time()
        self.communication_errors = 0
        self.operational_hours = 0.0

        # IA: detector de anomalías mecánicas
        self.ai_anomaly_detected: bool = False

        # Flag de repostaje pendiente — seteado por engine.py, consumido por _manage_fuel_and_maintenance
        # Desacopla la detección de llegada a gasolinera del campo destination_type (que logistics.py
        # borra atómicamente en _arrive_at_destination antes de que el twin pueda leerlo).
        self.refuel_pending: bool = False
        
        # Configurar logger
        self.logger = logging.getLogger(f"AmbulanceTwin.{self.id}")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(f'[%(name)s] %(levelname)s: %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def _default_logger(self, message: str) -> None:
        """Logger por defecto si no se proporciona callback."""
        self.logger.info(message)

    def start(self) -> None:
        """
        Inicia el bucle principal de simulación en un hilo separado.
        """
        if self.running:
            self.logger.warning(f"Ambulance {self.id} ya está en ejecución.")
            return
            
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name=f"Twin-{self.id}")
        self._thread.start()
        self.logger.info(f"Ambulance Twin {self.id} iniciado.")

    def stop(self) -> None:
        """
        Detiene el bucle principal de simulación.
        """
        self.running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                self.logger.warning(f"Hilo de {self.id} no pudo detenerse correctamente.")
        self.logger.info(f"Ambulance Twin {self.id} detenido.")

    def _run_loop(self) -> None:
        """
        Bucle principal de simulación que actualiza todos los motores y maneja comunicaciones.
        """
        while self.running:
            if self.is_paused:
                time.sleep(0.5)
                continue
                
            try:
                # Calcular sleep dinámico basado en multiplicador de velocidad
                actual_sleep = max(0.01, 1.0 / self.speed_multiplier)
                
                # 1. Actualizar logística y obtener distancia recorrida
                log_state = self.logistics.step(dt=1.0, speed_multiplier=self.speed_multiplier)
                dist_km = self.logistics.last_distance_km
                self.operational_hours += (1.0 / 3600.0) / self.speed_multiplier
                
                # 2. Gestión inteligente de combustible y mantenimiento
                self._manage_fuel_and_maintenance(dist_km)
                
                # 3. Determinar si el motor está encendido
                engine_on = self.logistics.speed > 0.1 or self.logistics.mission_status == "IN_USE"
                
                # 4. Actualizar motores mecánicos y vitales
                mech_state = self.mechanical.step(
                    dt=1.0, 
                    distance_km=dist_km, 
                    speed_multiplier=self.speed_multiplier, 
                    engine_on=engine_on
                )
                vit_state = self.vitals.step(dt=1.0)
                
                # 4.5. Predicción IA de anomalías mecánicas
                ai_result = ai_predictor.predict_failure(mech_state)
                self.ai_anomaly_detected = ai_result.get("anomaly", False)

                # 5. Agregar estado completo
                self.current_state = {
                    "ambulance_id": self.id,
                    "timestamp": time.time(),
                    "operational_hours": round(self.operational_hours, 2),
                    "mechanical": mech_state,
                    "vitals": vit_state,
                    "logistics": log_state,
                    "ai_prediction": ai_result,
                    "communication_status": self._get_communication_status()
                }
                
                # 6. Manejar comunicaciones redundantes
                self._handle_communications(mech_state, vit_state, log_state)
                
                # 7. Sincronización HTTPS de backup
                self._handle_https_backup()
                
                time.sleep(actual_sleep)
                
            except Exception as e:
                self.logger.error(f"Error en bucle de simulación: {e}")
                self.communication_errors += 1
                time.sleep(1.0)  # Pausa breve ante errores

    def _manage_fuel_and_maintenance(self, distance_km: float) -> None:
        """
        Gestiona automáticamente combustible, repostaje y mantenimiento.

        La decisión de iniciar repostaje está centralizada en engine.py
        (_manage_proactive_refueling), que setea self.refuel_pending = True y
        enruta la ambulancia a la gasolinera más cercana. Este método sólo
        gestiona la transición de llegada → is_refueling y la finalización.
        
        Args:
            distance_km: Distancia recorrida en el último paso
        """
        # Llegada a gasolinera — usa refuel_pending en lugar de destination_type
        # para evitar la condición de carrera con logistics._arrive_at_destination(),
        # que borra destination_type antes de que este método pueda leerlo.
        if (self.logistics.destination is None and
            self.refuel_pending and
            self.logistics.mission_status == "INACTIVE"):

            self.mechanical.is_refueling = True
            self.refuel_pending = False          # consumir el flag
            self.logistics.action_message = "Repostando (Bomba conectada)"
        
        # Finalización de repostaje - exactamente 100%
        if self.mechanical.is_refueling and self.mechanical.fuel_level >= 100.0:
            self.mechanical.is_refueling = False
            self.mechanical.fuel_level = 100.0  # Asegurar exactamente 100%
            self.logistics.mission_status = "ACTIVE"
            self.logistics.destination_type = None
            self.logistics.action_message = "Tanque lleno al 100%, listo para servicio"
            self.log_callback(f"[{self.id}] ✅ Tanque lleno al 100% exacto. Volviendo a estado OPERATIVO.")
        
        # Mantenimiento preventivo basado en horas de operación
        if (self.mechanical.engine_hours - self.mechanical.last_maintenance_hours > 100.0 and
            self.logistics.mission_status == "ACTIVE"):
            
            self.log_callback(f"[{self.id}] 🔧 Requiere mantenimiento programado ({self.mechanical.engine_hours:.1f}h).")
        
        # Parada por agotamiento total de combustible → estado STRANDED
        if self.mechanical.fuel_level <= 0.0:
            self.logistics.speed = 0.0
            self.logistics.acceleration = 0.0
            self.logistics.mission_status = "STRANDED"
            self.logistics.action_message = "VARADA — Sin combustible"
            self.mechanical.engine_on = False

    def _get_communication_status(self) -> Dict[str, Any]:
        """
        Retorna el estado actual de las comunicaciones.
        
        Returns:
            Diccionario con estado de cada canal
        """
        return {
            "mqtt_connected": self.mqtt_client.is_connected() if self.mqtt_client else False,
            "p2p_enabled": self.p2p_enabled,
            "http_enabled": self.http_enabled,
            "errors": self.communication_errors,
            "last_sync": self.last_https_sync
        }

    def _handle_communications(self, mech_state: Dict, vit_state: Dict, log_state: Dict) -> None:
        """
        Maneja comunicaciones redundantes MQTT/P2P.
        
        Args:
            mech_state: Estado mecánico actual
            vit_state: Estado de constantes vitales
            log_state: Estado logístico
        """
        # Crear log compacto para display
        m_stat = mech_state.get('status', 'OK')
        v_stat = vit_state.get('patient_status', PatientStatus.NONE.value)
        l_stat = log_state.get('traffic_status', 'clear')
        compact_log = f"Mech:{m_stat} | Vit:{v_stat} | Trf:{l_stat}"
        
        # Prioridad 1: MQTT a centralita
        if self.mqtt_client and self.mqtt_client.is_connected():
            try:
                self.mqtt_client.publish_state(self.id, self.current_state)
                self.log_callback(f"[{self.id}] → MQTT | {compact_log}")
                return  # Éxito, no usar fallback
            except Exception as e:
                self.logger.warning(f"Error MQTT: {e}")
                self.communication_errors += 1
        
        # Fallback 2: P2P mesh local
        if self.p2p_mesh and self.p2p_enabled:
            try:
                self.p2p_mesh.broadcast_state(self.current_state)
                self.log_callback(f"[{self.id}] → P2P BROADCAST | {compact_log}")
            except Exception as e:
                self.logger.warning(f"Error P2P: {e}")
                self.communication_errors += 1
        else:
            self.log_callback(f"[{self.id}] ⚠️ SIN COMUNICACIÓN | {compact_log}")

    def _handle_https_backup(self) -> None:
        """
        Maneja sincronización periódica HTTPS para backup de datos críticos.
        """
        current_time = time.time()
        sync_interval = max(5.0, 10.0 / self.speed_multiplier)  # Mínimo 5 segundos
        
        if (current_time - self.last_https_sync >= sync_interval and 
            self.http_enabled and 
            self.https_client):
            
            try:
                # Enviar solo datos críticos para backup con estructura correcta
                payload = {
                    "ambulance_id": self.id,
                    "timestamp": current_time,
                    "critical_data": {
                        "position": {
                            "lat": self.logistics.lat,
                            "lon": self.logistics.lon
                        },
                        "patient_status": self.vitals.patient_status.value if self.vitals.has_patient else PatientStatus.NONE.value,
                        "fuel_level": self.mechanical.fuel_level,
                        "mission_status": self.logistics.mission_status
                    }
                }
                
                self.https_client.sync_backup(payload)
                self.last_https_sync = current_time
                self.log_callback(f"[{self.id}] → HTTP | Backup crítico enviado")
                
            except Exception as e:
                self.logger.warning(f"Error HTTPS backup: {e}")
                self.communication_errors += 1

    def inject_incident(self, category: str, incident_type: str) -> bool:
        """
        Inyecta un incidente específico en el sistema.
        
        Args:
            category: 'mechanical', 'vitals', o 'logistics'
            incident_type: Tipo específico de incidente
            
        Returns:
            True si el incidente fue inyectado correctamente
        """
        self.logger.info(f"Inyectando incidente {category}: {incident_type}")
        
        try:
            if category == "mechanical":
                if hasattr(self.mechanical, 'inject_fault'):
                    self.mechanical.inject_fault(incident_type)
                    self.log_callback(f"[{self.id}] ⚠️ Incidente mecánico inyectado: {incident_type}")
                    return True
                    
            elif category == "vitals":
                if hasattr(self.vitals, 'inject_incident'):
                    self.vitals.inject_incident(incident_type)
                    self.log_callback(f"[{self.id}] ⚠️ Incidente médico inyectado: {incident_type}")
                    return True
                    
            elif category == "logistics":
                if hasattr(self.logistics, 'inject_interference'):
                    self.logistics.inject_interference(incident_type)
                    self.log_callback(f"[{self.id}] ⚠️ Incidente logístico inyectado: {incident_type}")
                    return True
                    
            self.logger.warning(f"Tipo de incidente no soportado: {category}/{incident_type}")
            return False
            
        except Exception as e:
            self.logger.error(f"Error inyectando incidente: {e}")
            return False

    def administer_treatment(self, treatment_type: str) -> bool:
        """
        Administra un tratamiento médico al paciente.
        
        Args:
            treatment_type: Tipo de tratamiento a administrar
            
        Returns:
            True si el tratamiento fue administrado correctamente
        """
        if not self.vitals.has_patient:
            self.logger.warning(f"Intento de tratamiento sin paciente en {self.id}")
            return False
            
        try:
            if hasattr(self.vitals, 'administer_treatment'):
                success = self.vitals.administer_treatment(treatment_type)
                if success:
                    self.log_callback(f"[{self.id}] 💊 Tratamiento administrado: {treatment_type}")
                return success
            return False
        except Exception as e:
            self.logger.error(f"Error administrando tratamiento: {e}")
            return False

    def perform_maintenance(self) -> bool:
        """
        Realiza mantenimiento completo en la ambulancia.
        
        Returns:
            True si el mantenimiento fue realizado
        """
        try:
            if hasattr(self.mechanical, 'perform_maintenance'):
                self.mechanical.perform_maintenance()
                self.log_callback(f"[{self.id}] 🔧 Mantenimiento completo realizado")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error realizando mantenimiento: {e}")
            return False

    def set_patient_info(self, age: int = 45, has_patient: bool = True) -> bool:
        """
        Configura información del paciente en la ambulancia.
        
        Args:
            age: Edad del paciente en años
            has_patient: Si hay un paciente en la ambulancia
            
        Returns:
            True si la información fue configurada
        """
        try:
            if hasattr(self.vitals, 'set_patient_info'):
                self.vitals.set_patient_info(age, has_patient)
                status = "con paciente" if has_patient else "sin paciente"
                self.log_callback(f"[{self.id}] 👤 Configurado {status} (edad: {age})")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error configurando paciente: {e}")
            return False

    def toggle_pause(self) -> None:
        """Alterna estado de pausa de la simulación."""
        self.is_paused = not self.is_paused
        status = "PAUSADA" if self.is_paused else "REANUDADA"
        self.log_callback(f"[{self.id}] ⏸️ Simulación {status}")
        
    def get_detailed_status(self) -> Dict[str, Any]:
        """
        Retorna un estado detallado de la ambulancia para diagnóstico.
        
        Returns:
            Diccionario con estado detallado
        """
        return {
            "id": self.id,
            "running": self.running,
            "paused": self.is_paused,
            "speed_multiplier": self.speed_multiplier,
            "operational_hours": round(self.operational_hours, 2),
            "communication_errors": self.communication_errors,
            "mechanical_status": self.mechanical.get_state() if hasattr(self.mechanical, 'get_state') else {},
            "vitals_status": self.vitals.get_state() if hasattr(self.vitals, 'get_state') else {},
            "logistics_status": self.logistics.get_state() if hasattr(self.logistics, 'get_state') else {},
            "communication_status": self._get_communication_status()
        }