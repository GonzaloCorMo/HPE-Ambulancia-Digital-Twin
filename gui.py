import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import json
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
        self.root.after(100, self.start_simulation)
        
        # Start UI updater thread
        self.root.after(200, lambda: threading.Thread(target=self.update_ui_loop, daemon=True).start())

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
        
        self.selected_amb = tk.StringVar(value="AMB-001")
        amb_selector = ttk.Combobox(self.ctrl_frame, textvariable=self.selected_amb, values=["AMB-001", "AMB-002", "AMB-003"], state="readonly", width=12)
        amb_selector.grid(row=0, column=0, padx=5, pady=5)
        
        ttk.Button(self.ctrl_frame, text="🚗 Inyectar Atasco", command=self.inject_traffic).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(self.ctrl_frame, text="🫀 Paciente Crítico", command=self.inject_vitals).grid(row=0, column=2, padx=5, pady=5)
        ttk.Button(self.ctrl_frame, text="🛞 Fallo Mecánico", command=self.inject_mechanical).grid(row=0, column=3, padx=5, pady=5)
        ttk.Button(self.ctrl_frame, text="Pausar MQTT", command=self.cut_mqtt).grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(self.ctrl_frame, text="💥 Tirar Centralita Abajo", command=self.kill_centralita).grid(row=1, column=2, padx=5, pady=5)
        
        # Network Log Dashboard
        self.log_frame = ttk.LabelFrame(self.root, text="Monitor de Red P2P y MQTT")
        self.log_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        self.log_text = tk.Text(self.log_frame, height=8, bg="#1e1e1e", fg="#00ff00", font=("Courier", 9))
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.log_text.insert(tk.END, "=== Iniciando subsistemas de telemetría y red ===\n")
        
        # Adjust geometry slightly to fit new panel
        self.root.geometry("850x650")

    def init_ambulance_ui(self, am_id):
        frame = ttk.Frame(self.amb_frame, borderwidth=2, relief="groove")
        frame.pack(fill="x", padx=10, pady=5)
        
        def on_click(event, a_id=am_id):
            self.show_telemetry_details(a_id)
            
        frame.bind("<Button-1>", on_click)
        
        lbl_title = tk.Label(frame, text=f"🚑 {am_id}", font=("Helvetica", 12, "bold"), width=15, anchor="w", cursor="hand2")
        lbl_title.grid(row=0, column=0, rowspan=2, padx=5, pady=5)
        lbl_title.bind("<Button-1>", on_click)
        
        # Sub-labels
        lbl_vitals = tk.Label(frame, text="Vitales: Cargando...", width=30, anchor="w", fg="blue", cursor="hand2")
        lbl_vitals.grid(row=0, column=1, padx=5)
        lbl_vitals.bind("<Button-1>", on_click)
        
        lbl_mech = tk.Label(frame, text="Mecánica: Cargando...", width=30, anchor="w", fg="green", cursor="hand2")
        lbl_mech.grid(row=1, column=1, padx=5)
        lbl_mech.bind("<Button-1>", on_click)
        
        lbl_log = tk.Label(frame, text="Logística: Cargando...", width=30, anchor="w", fg="purple", cursor="hand2")
        lbl_log.grid(row=0, column=2, padx=5)
        lbl_log.bind("<Button-1>", on_click)
        
        lbl_peers = tk.Label(frame, text="Conexiones P2P: 0", width=25, anchor="w", fg="orange", cursor="hand2")
        lbl_peers.grid(row=1, column=2, padx=5)
        lbl_peers.bind("<Button-1>", on_click)
        
        self.info_labels[am_id] = {
            "vitals": lbl_vitals,
            "mech": lbl_mech,
            "log": lbl_log,
            "peers": lbl_peers
        }

    def start_simulation(self):
        broker = "localhost"
        
        # Instanciamos usando la funcion del main.py, pasando log_network
        self.ambulances["AMB-001"] = launch_ambulance("AMB-001", 40.4168, -3.7038, broker, log_callback=self.log_network)
        self.ambulances["AMB-002"] = launch_ambulance("AMB-002", 40.4170, -3.7040, broker, log_callback=self.log_network)
        self.ambulances["AMB-003"] = launch_ambulance("AMB-003", 40.4500, -3.6900, broker, log_callback=self.log_network)
        
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

    def log_network(self, message):
        def _append():
            if self.running and self.log_text.winfo_exists():
                timestamp = time.strftime("%H:%M:%S")
                # Limitar a ~100 líneas para no ralentizar la GUI
                if int(self.log_text.index('end-1c').split('.')[0]) > 100:
                    self.log_text.delete('1.0', '2.0')
                self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
                self.log_text.see(tk.END)
        self.root.after(0, _append)

    def inject_traffic(self):
        target = self.selected_amb.get()
        if target in self.ambulances:
            self.ambulances[target].inject_incident("logistics", "traffic_jam")
            messagebox.showinfo("Incidente", f"Atasco inyectado en {target}.")

    def inject_vitals(self):
        target = self.selected_amb.get()
        if target in self.ambulances:
            self.ambulances[target].inject_incident("vitals", "drop_oxygen")
            messagebox.showwarning("Emergencia", f"El oxígeno del paciente en {target} ha caído a estado crítico.")

    def inject_mechanical(self):
        target = self.selected_amb.get()
        if target in self.ambulances:
            self.ambulances[target].inject_incident("mechanical", "flat_tire")
            messagebox.showerror("Fallo Mecánico", f"Rueda pinchada en {target}. La temperatura subirá.")

    def cut_mqtt(self):
        target = self.selected_amb.get()
        if target in self.ambulances:
            self.ambulances[target].mqtt_client.disconnect()
            messagebox.showwarning("Cobertura Perdida", f"Desconexión MQTT forzada en {target}. Pasa a P2P.")

    def kill_centralita(self):
        for amb in self.ambulances.values():
            if amb.mqtt_client:
                amb.mqtt_client.disconnect()
        messagebox.showerror("Fallo Crítico", "La centralita ha caído. Todas las ambulancias pasan a modo P2P.")

    def show_telemetry_details(self, am_id):
        if am_id not in self.ambulances:
            return
            
        twin = self.ambulances[am_id]
        if not twin.current_state:
            messagebox.showinfo("Espere", "Aún no hay datos de telemetría disponibles.")
            return
            
        top = tk.Toplevel(self.root)
        top.title(f"Telemetría Detallada - {am_id}")
        top.geometry("450x650")
        
        ttk.Label(top, text=f"Datos en Tiempo Real: {am_id}", font=("Helvetica", 12, "bold")).pack(pady=10)
        
        text_widget = tk.Text(top, wrap="word", font=("Courier", 10), bg="#1e1e1e", fg="#00ff00")
        text_widget.pack(fill="both", expand=True, padx=10, pady=10)
        
        def update_text():
            if not top.winfo_exists():
                return
            state = twin.current_state
            text_widget.delete(1.0, tk.END)
            text_widget.insert(tk.END, json.dumps(state, indent=4))
            top.after(1000, update_text)
            
        update_text()

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
