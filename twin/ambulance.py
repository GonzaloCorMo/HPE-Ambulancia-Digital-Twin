import time
import uuid
import threading
from telemetry.mechanical import MechanicalEngine
from telemetry.vitals import VitalsEngine
from telemetry.logistics import LogisticsEngine

class AmbulanceTwin:
    def __init__(self, am_id=None, log_callback=None):
        self.id = am_id or str(uuid.uuid4())
        self.log_callback = log_callback
        self.mechanical = MechanicalEngine()
        self.vitals = VitalsEngine()
        self.logistics = LogisticsEngine()
        
        # Communication handlers will be injected later
        self.mqtt_client = None
        self.https_client = None
        self.p2p_mesh = None
        
        self.running = False
        self._thread = None
        
        # Store latest state
        self.current_state = {}
        self.p2p_enabled = True
        self.http_enabled = True

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print(f"Ambulance Twin {self.id} started.")

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join()
        print(f"Ambulance Twin {self.id} stopped.")

    def _run_loop(self):
        last_https_sync = time.time()
        
        while self.running:
            # 1. Step Logistics and get metrics
            log_state = self.logistics.step(dt=1.0)
            dist_km = self.logistics.last_distance_km
            
            # ORCHESTRATION: Smart fuel management
            if self.mechanical.fuel_level < 15.0 and not self.mechanical.is_refueling:
                if self.logistics.destination_type != "GAS_STATION":
                    self.logistics.route_to_nearest("GAS_STATION")
                    if self.log_callback:
                        self.log_callback(f"[{self.id}] ⚠️ Combustible bajo ({int(self.mechanical.fuel_level)}%). Desviando a ⛽...")
                        
            if self.logistics.destination is None and self.logistics.destination_type == "GAS_STATION":
                # Arrived at Gas Station
                self.mechanical.is_refueling = True
                self.logistics.destination_type = None
                
            if self.mechanical.is_refueling:
                self.logistics.speed = 0.0
                self.logistics.acceleration = 0.0
                if self.mechanical.fuel_level >= 99.0:
                    # Finished Refueling
                    self.log_callback(f"[{self.id}] ⛽ Depósito Lleno. Retomando operaciones.")
                    self.logistics.route_to_nearest("HOSPITAL")

            # Orchestration: Out of fuel
            if self.mechanical.fuel_level <= 0.0:
                 self.logistics.speed = 0.0
                 self.logistics.acceleration = 0.0

            mech_state = self.mechanical.step(dt=1.0, distance_km=dist_km)
            vit_state = self.vitals.step(dt=1.0)
            
            # 2. Aggregate State
            self.current_state = {
                "ambulance_id": self.id,
                "timestamp": time.time(),
                "mechanical": mech_state,
                "vitals": vit_state,
                "logistics": log_state
            }
            
            m_stat = mech_state.get('status', 'OK')
            v_stat = vit_state.get('patient_status', 'stable')
            l_stat = log_state.get('traffic_status', 'clear')
            compact_log = f"Mech:{m_stat} | Vit:{v_stat} | Trf:{l_stat}"

            # 3. Communications
            if self.mqtt_client and self.mqtt_client.is_connected():
                if self.log_callback:
                    self.log_callback(f"[{self.id}] \u2192 MQTT | {compact_log}")
                self.mqtt_client.publish_state(self.id, self.current_state)
                
            # 3b. Fallback to P2P if MQTT is down
            elif self.p2p_mesh and self.p2p_enabled:
                if self.log_callback:
                    self.log_callback(f"[{self.id}] \u2192 P2P BROADCAST | {compact_log}")
                self.p2p_mesh.broadcast_state(self.current_state)

            # 4. HTTPS Backup (Every 10 seconds)
            current_time = time.time()
            if current_time - last_https_sync >= 10.0 and self.http_enabled:
                if self.https_client:
                    if self.log_callback:
                        self.log_callback(f"[{self.id}] \u2192 HTTP | Starting Backup Data Sync...")
                    self.https_client.sync_backup(self.current_state)
                last_https_sync = current_time

            time.sleep(1.0)

    def inject_incident(self, category, incident_type):
        """
        Allows external control to inject failures or interferences.
        category: 'mechanical', 'vitals', or 'logistics'
        """
        print(f"[{self.id}] Injecting {category} incident: {incident_type}")
        if category == "mechanical":
            self.mechanical.inject_fault(incident_type)
        elif category == "vitals":
            self.vitals.inject_incident(incident_type)
        elif category == "logistics":
            self.logistics.inject_interference(incident_type)
