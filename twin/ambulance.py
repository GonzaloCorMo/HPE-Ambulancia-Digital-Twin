import time
import uuid
import threading
from telemetry.mechanical import MechanicalEngine
from telemetry.vitals import VitalsEngine
from telemetry.logistics import LogisticsEngine

class AmbulanceTwin:
    def __init__(self, am_id=None):
        self.id = am_id or str(uuid.uuid4())
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
            # 1. Step simulations (dt = 1.0 second)
            mech_state = self.mechanical.step(dt=1.0)
            vit_state = self.vitals.step(dt=1.0)
            log_state = self.logistics.step(dt=1.0)
            
            # 2. Aggregate State
            self.current_state = {
                "ambulance_id": self.id,
                "timestamp": time.time(),
                "mechanical": mech_state,
                "vitals": vit_state,
                "logistics": log_state
            }
            
            # 3. Communications (Publish to MQTT every second)
            # We will implement this logic once comms modules are ready
            if self.mqtt_client:
                self.mqtt_client.publish_state(self.id, self.current_state)
                
            # 3b. Fallback to P2P if MQTT is down
            if self.mqtt_client and not self.mqtt_client.is_connected() and self.p2p_mesh:
                self.p2p_mesh.broadcast_state(self.current_state)

            # 4. HTTPS Backup (Every 10 seconds)
            current_time = time.time()
            if current_time - last_https_sync >= 10.0:
                if self.https_client:
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
