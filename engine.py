import time
import math
import uuid
import threading
from main import launch_ambulance
from telemetry.logistics import POIS, JAMS

class SimulatorEngine:
    def __init__(self, log_callback=None):
        self.ambulances = {}
        self.active_emergencies = {}
        
        self.running = True
        self.is_simulating = False
        
        self.speed_multiplier = 1
        self.mqtt_on = True
        self.p2p_on = True
        self.http_on = True
        
        self.log_callback = log_callback
        
        self._dispatch_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._dispatch_thread.start()
        
    def log_network(self, message):
        if self.log_callback:
            self.log_callback(message)
            
    def spawn_ambulance(self, lat, lon):
        am_id = f"AMB-{len(self.ambulances)+1:03d}"
        self.ambulances[am_id] = launch_ambulance(am_id, lat, lon, "localhost", log_callback=self.log_network)
        self.ambulances[am_id].speed_multiplier = self.speed_multiplier
        self.ambulances[am_id].is_paused = not self.is_simulating
        
        # Idle starting state
        self.ambulances[am_id].logistics.route_to_nearest("GAS_STATION")
        self.log_network(f"[SISTEMA] Nueva unidad {am_id} desplegada en mapa.")
        return am_id

    def spawn_emergency(self, lat, lon):
        em_id = str(uuid.uuid4())[:8]
        emergency = {"id": em_id, "lat": lat, "lon": lon, "status": "INITIATED"}
        self.active_emergencies[em_id] = emergency
        self.log_network(f"[URGENCIA {em_id}] Estado: INITIATED. Registrada en mapa, esperando asignación de recursos...")
        self.evaluate_fleet_assignments()
        return em_id

    def evaluate_fleet_assignments(self):
        if not self.running or not self.is_simulating: return
        
        # 1. Predictive Calculus for Emergencies finding ambulances
        for em_id, em in list(self.active_emergencies.items()):
            if em["status"] != "INITIATED":
                continue
                
            best_amb, min_eff_dist = None, 999999
            
            hospitals = [p for p in POIS if p["type"] == "HOSPITAL"]
            if not hospitals: continue
            
            for am_id, amb in list(self.ambulances.items()):
                # Only dispatch if ACTIVE, or INACTIVE but NOT currently refueling
                is_available = amb.logistics.mission_status == "ACTIVE" or (amb.logistics.mission_status == "INACTIVE" and not amb.mechanical.is_refueling)
                if is_available:
                    # Distance to emergency
                    dist_to_em_deg = math.sqrt((amb.logistics.lat - em["lat"])**2 + (amb.logistics.lon - em["lon"])**2)
                    dist_to_em_km = dist_to_em_deg * 111.0 
                    
                    # Distance from emergency to nearest hospital
                    min_h_dist = min([math.sqrt((h["lat"] - em["lat"])**2 + (h["lon"] - em["lon"])**2) for h in hospitals])
                    min_h_dist_km = min_h_dist * 111.0
                    
                    total_dist_km = dist_to_em_km + min_h_dist_km
                    fuel_cost = (total_dist_km * 5.0) * 1.5 + 5.0 # 1.5 multiplier + buffer
                    
                    has_enough_fuel = amb.mechanical.fuel_level >= fuel_cost
                    if has_enough_fuel:
                        if dist_to_em_deg < min_eff_dist:
                            min_eff_dist = dist_to_em_deg
                            best_amb = amb
                            
            if best_amb:
                em["status"] = "PROCESSING"
                em["assigned_ambulance"] = best_amb.id
                was_refueling_route = best_amb.logistics.mission_status == "INACTIVE"
                best_amb.logistics.mission_status = "IN_USE"
                best_amb.logistics.set_destination(em["lat"], em["lon"], "EMERGENCY")
                
                divert_msg = " [DESVÍO DE REPOSTAJE]" if was_refueling_route else ""
                self.log_network(f"[URGENCIA {em_id}] Estado: PROCESSING. Asignada a Unidad {best_amb.id}.{divert_msg}")
                # Dispatch loop will handle arrival detection
                
    def _dispatch_loop(self):
        while self.running:
            if not self.is_simulating:
                time.sleep(0.5)
                continue
                
            for em_id, em in list(self.active_emergencies.items()):
                if em["status"] == "PROCESSING":
                    # Find the assigned ambulance that reached THIS emergency
                    amb_id = em.get("assigned_ambulance")
                    if amb_id and amb_id in self.ambulances:
                        amb = self.ambulances[amb_id]
                        if amb.logistics.mission_status == "IN_USE" and amb.logistics.destination_type == "EMERGENCY":
                            if amb.logistics.destination is None and abs(amb.logistics.lat - em["lat"]) < 0.001 and abs(amb.logistics.lon - em["lon"]) < 0.001:
                                amb.vitals.has_patient = True 
                                self.log_network(f"[DISPATCHER] 🏥 Unidad {amb.id} estabilizando a paciente en escena. Buscando Hospital cercano...")
                                
                                hospitals = [p for p in POIS if p["type"] == "HOSPITAL"]
                                if hospitals:
                                    # Load balancing calculation
                                    hospital_loads = { (h["lat"], h["lon"]): 0 for h in hospitals }
                                    for fleet_amb in list(self.ambulances.values()):
                                        dest = fleet_amb.logistics.destination
                                        if dest and fleet_amb.logistics.destination_type == "HOSPITAL":
                                            if dest in hospital_loads: hospital_loads[dest] += 1
                                    
                                    best_h = min(hospitals, key=lambda h: (hospital_loads.get((h["lat"], h["lon"]), 0), math.sqrt((amb.logistics.lat - h["lat"])**2 + (amb.logistics.lon - h["lon"])**2)))
                                    
                                    dist_info = math.sqrt((amb.logistics.lat - best_h["lat"])**2 + (amb.logistics.lon - best_h["lon"])**2) * 111.0
                                    self.log_network(f"[DISPATCHER] 🏥 Unidad {amb.id} transportando al Hospital [Dist: {dist_info:.2f} km].")
                                    
                                    amb.logistics.set_destination(best_h["lat"], best_h["lon"], "HOSPITAL")
                                    amb.logistics.action_message = "Transportando al Hospital" # Added action_message
                                    em["status"] = "TRANSPORTING"
                                
                elif em["status"] == "TRANSPORTING":
                    # Check if reached hospital
                    amb_id = em.get("assigned_ambulance")
                    if amb_id and amb_id in self.ambulances:
                        amb = self.ambulances[amb_id]
                        if amb.logistics.mission_status == "IN_USE" and amb.vitals.has_patient and amb.logistics.destination_type == "HOSPITAL":
                            if amb.logistics.destination is None:
                                # We assume this transport corresponds to the emergency in transporting state
                                amb.logistics.mission_status = "ACTIVE"
                                amb.vitals.has_patient = False
                                amb.logistics.action_message = "Esperando asignación" # Added action_message
                                
                                em["status"] = "RESOLVED"
                                if em["id"] in self.active_emergencies:
                                    del self.active_emergencies[em["id"]]
                                    
                                self.log_network(f"[URGENCIA {em['id']}] Estado: RESOLVED. Paciente ingresado con éxito por Unidad {amb.id}.")
                                self.evaluate_fleet_assignments()

            time.sleep(0.1) # 10 Hz refresh to cleanly catch triggers instantly
                    
        # 2. Free ambulances without a destination should dock at a hospital
        for am_id, amb in list(self.ambulances.items()):
           if amb.logistics.mission_status == "ACTIVE" and amb.logistics.destination is None:
               docked = False
               has_unassigned = any(e["status"] == "INITIATED" for e in self.active_emergencies.values())
               hospitals = [p for p in POIS if p["type"] == "HOSPITAL"]
               
               for h in hospitals:
                   if abs(amb.logistics.lat - h["lat"]) < 0.006 and abs(amb.logistics.lon - h["lon"]) < 0.006:
                       docked = True
                       break
               
               if not docked and not has_unassigned and hospitals:
                    # Find least busy hospital
                    hospital_loads = { (h["lat"], h["lon"]): 0 for h in hospitals }
                    for fleet_amb in list(self.ambulances.values()):
                         dest = fleet_amb.logistics.destination
                         d_type = fleet_amb.logistics.destination_type
                         if dest and d_type == "HOSPITAL":
                              if dest in hospital_loads: hospital_loads[dest] += 1
                         elif not dest and fleet_amb.logistics.mission_status == "ACTIVE":
                              for h_latlon in hospital_loads.keys():
                                   if abs(fleet_amb.logistics.lat - h_latlon[0]) < 0.006 and abs(fleet_amb.logistics.lon - h_latlon[1]) < 0.006:
                                        hospital_loads[h_latlon] += 1
                                        
                    # Tie-break minimal load with distance
                    best_h = min(hospitals, key=lambda h: (hospital_loads.get((h["lat"], h["lon"]), 0), math.sqrt((amb.logistics.lat - h["lat"])**2 + (amb.logistics.lon - h["lon"])**2)))
                    amb.logistics.set_destination(best_h["lat"], best_h["lon"], "HOSPITAL")
                    self.log_network(f"[SISTEMA] {amb.id} retira a base hospitalaria (Carga Actual: {hospital_loads.get((best_h['lat'], best_h['lon']), 0)}).")

    def update_speed_multiplier(self, val):
        self.speed_multiplier = val
        for amb in self.ambulances.values():
            amb.speed_multiplier = val
        self.log_network(f"[SISTEMA] Reloj temporal del motor ajustado a {val}x.")

    def toggle_playback(self):
        self.is_simulating = not self.is_simulating
        if self.is_simulating:
            self.log_network("=== ▶️ MUNDO REACTIVADO ===")
            for amb in self.ambulances.values():
                amb.is_paused = False
            self.evaluate_fleet_assignments()
        else:
            self.log_network("=== ⏸️ MUNDO PAUSADO ===")
            for amb in self.ambulances.values():
                amb.is_paused = True

    def clear_all_scenario(self):
        self.log_network("=== 🗑️ BORRADO DE SEGURIDAD. LIMPIANDO ESCENARIO... ===")
        was_simulating = self.is_simulating
        
        for am_id, amb in list(self.ambulances.items()):
             amb.stop()
             if amb.p2p_mesh: amb.p2p_mesh.stop()
        
        self.ambulances.clear()
        POIS.clear()
        JAMS.clear()
        self.active_emergencies.clear()
        
        self.log_network("[SISTEMA] MEMORIA PURGADA. Lienzo táctico preparado para nuevo vector.")
        if was_simulating:
            self.toggle_playback()

    def toggle_networks(self, mqtt, p2p, http):
        self.mqtt_on, self.p2p_on, self.http_on = mqtt, p2p, http
        for am_id, amb in list(self.ambulances.items()):
            if self.mqtt_on:
                if amb.mqtt_client and not amb.mqtt_client.is_connected(): amb.mqtt_client.connect()
            else:
                if amb.mqtt_client and amb.mqtt_client.is_connected(): amb.mqtt_client.disconnect()
            amb.p2p_enabled = self.p2p_on
            amb.http_enabled = self.http_on
        self.log_network(f"--- RED CONFIGURADA | MQTT:{'OK' if self.mqtt_on else 'OFF'} | P2P:{'OK' if self.p2p_on else 'OFF'} | HTTP:{'OK' if self.http_on else 'OFF'} ---")

    def stop(self):
        self.running = False
        for amb in list(self.ambulances.values()):
            amb.stop()
            amb.p2p_mesh.stop()
