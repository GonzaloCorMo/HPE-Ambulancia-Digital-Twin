import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
from main import launch_ambulance

class SimulatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Ambulance Digital Twin - Panel de Control")
        self.root.geometry("850x500")
        
        self.ambulances = {}
        self.running = True
        
        self.amb_frame = None
        self.ctrl_frame = None
        self.info_labels = {}
        self.peer_labels = {}
        
        self.setup_ui()
        self.start_simulation()
        
        # Start UI updater thread
        threading.Thread(target=self.update_ui_loop, daemon=True).start()

    def setup_ui(self):
        # Title
        tk.Label(self.root, text="Centro de Mando de Simulaciones", font=("Helvetica", 16, "bold")).pack(pady=10)
        
        # Frame for ambulances
        self.amb_frame = ttk.LabelFrame(self.root, text="Estado de la Flota en Tiempo Real")
        self.amb_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Info labels dictionary
        self.info_labels = {}
        self.peer_labels = {}

        # Control Panel
        self.ctrl_frame = ttk.LabelFrame(self.root, text="Inyección de Incidentes (Pruebas)")
        self.ctrl_frame.pack(fill="x", padx=20, pady=10)
        
        ttk.Button(self.ctrl_frame, text="🚗 Inyectar Atasco (AMB-001 y AMB-002)", command=self.inject_traffic).grid(row=0, column=0, padx=5, pady=5)
        ttk.Button(self.ctrl_frame, text="🫀 Paciente Crítico: Bajada O2 (AMB-003)", command=self.inject_vitals).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(self.ctrl_frame, text="🛞 Fallo Mecánico: Pinchazo (AMB-001)", command=self.inject_mechanical).grid(row=0, column=2, padx=5, pady=5)
        ttk.Button(self.ctrl_frame, text="Pausar MQTT a AMB-001 (Forzar P2P)", command=self.cut_mqtt).grid(row=1, column=0, padx=5, pady=5)

    def init_ambulance_ui(self, am_id):
        frame = ttk.Frame(self.amb_frame, borderwidth=2, relief="groove")
        frame.pack(fill="x", padx=10, pady=5)
        
        lbl_title = tk.Label(frame, text=f"🚑 {am_id}", font=("Helvetica", 12, "bold"), width=15, anchor="w")
        lbl_title.grid(row=0, column=0, rowspan=2, padx=5, pady=5)
        
        # Sub-labels
        lbl_vitals = tk.Label(frame, text="Vitales: Cargando...", width=30, anchor="w", fg="blue")
        lbl_vitals.grid(row=0, column=1, padx=5)
        
        lbl_mech = tk.Label(frame, text="Mecánica: Cargando...", width=30, anchor="w", fg="green")
        lbl_mech.grid(row=1, column=1, padx=5)
        
        lbl_log = tk.Label(frame, text="Logística: Cargando...", width=30, anchor="w", fg="purple")
        lbl_log.grid(row=0, column=2, padx=5)
        
        lbl_peers = tk.Label(frame, text="Conexiones P2P: 0", width=25, anchor="w", fg="orange")
        lbl_peers.grid(row=1, column=2, padx=5)
        
        self.info_labels[am_id] = {
            "vitals": lbl_vitals,
            "mech": lbl_mech,
            "log": lbl_log,
            "peers": lbl_peers
        }

    def start_simulation(self):
        broker = "localhost"
        
        # Instanciamos usando la funcion del main.py
        self.ambulances["AMB-001"] = launch_ambulance("AMB-001", 40.4168, -3.7038, broker)
        self.ambulances["AMB-002"] = launch_ambulance("AMB-002", 40.4170, -3.7040, broker)
        self.ambulances["AMB-003"] = launch_ambulance("AMB-003", 40.4500, -3.6900, broker)
        
        self.ambulances["AMB-001"].logistics.set_destination(40.4800, -3.6500)
        self.ambulances["AMB-002"].logistics.set_destination(40.4800, -3.6500)
        self.ambulances["AMB-003"].logistics.set_destination(40.4100, -3.7000)
        
        # Initialize UI rows
        for am_id in self.ambulances:
            self.init_ambulance_ui(am_id)

    def update_ui_loop(self):
        while self.running:
            time.sleep(1)
            for am_id, twin in self.ambulances.items():
                if am_id in self.info_labels and twin.current_state:
                    state = twin.current_state
                    ui_labels = self.info_labels[am_id]
                    
                    v = state.get("vitals", {})
                    m = state.get("mechanical", {})
                    l = state.get("logistics", {})
                    
                    v_str = f"♥ {v.get('heart_rate')} bpm | O2: {v.get('oxygen_level')}% | Estado: {v.get('patient_status')}"
                    m_str = f"⛽ {m.get('fuel_level')}% | Temp: {m.get('engine_temperature')}C"
                    l_str = f"📍 {l.get('speed')} km/h | Atasco: {'SI' if l.get('speed', 80) < 15.0 else 'NO'}"
                    
                    peers = len(twin.p2p_mesh.get_active_peers())
                    p_str = f"📡 Vía MQTT | P2P viendo a: {peers}"
                    if not twin.mqtt_client.is_connected():
                        p_str = f"⚠️ MQTT CAÍDO | Usando P2P (Vecinos: {peers})"
                    
                    safe_update_label(ui_labels["vitals"], v_str)
                    safe_update_label(ui_labels["mech"], m_str)
                    safe_update_label(ui_labels["log"], l_str)
                    safe_update_label(ui_labels["peers"], p_str)

    def inject_traffic(self):
        self.ambulances["AMB-001"].inject_incident("logistics", "traffic_jam")
        self.ambulances["AMB-002"].inject_incident("logistics", "traffic_jam")
        messagebox.showinfo("Incidente", "Atasco inyectado. La velocidad de AMB-001 y AMB-002 caerá drásticamente.")

    def inject_vitals(self):
        self.ambulances["AMB-003"].inject_incident("vitals", "drop_oxygen")
        messagebox.showwarning("Emergencia", "El oxígeno del paciente en AMB-003 ha caído a estado crítico.")

    def inject_mechanical(self):
        self.ambulances["AMB-001"].inject_incident("mechanical", "flat_tire")
        messagebox.showerror("Fallo Mecánico", "Rueda pinchada en AMB-001. La temperatura subirá y alertará mecánicamente.")

    def cut_mqtt(self):
        # Simulamos que la ambulancia pierde cobertura 4G/MQTT
        self.ambulances["AMB-001"].mqtt_client.disconnect()
        messagebox.showwarning("Cobertura Perdida", "Se ha forzado la desconexión MQTT de AMB-001. Iniciará el envío de emergencia por red local P2P.")

    def on_closing(self):
        self.running = False
        for amb in self.ambulances.values():
            amb.stop()
            amb.p2p_mesh.stop()
        self.root.destroy()

def safe_update_label(label, text):
    try:
        label.config(text=text)
    except:
        pass

if __name__ == "__main__":
    root = tk.Tk()
    app = SimulatorGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
