import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import json
import math
from main import launch_ambulance

# Estilos globales Dark Mode
BG_COLOR = "#121212"
PANEL_BG = "#1E1E1E"
TEXT_COLOR = "#FFFFFF"
ACCENT_COLOR = "#FF9800"

# Bounding box para transformar Lat/Lon locales a Píxeles en Canvas (600x400)
MIN_LAT, MAX_LAT = 40.4000, 40.5000
MIN_LON, MAX_LON = -3.7500, -3.6000
CANVAS_W, CANVAS_H = 600, 400

def coord_to_pixel(lat, lon):
    x = (lon - MIN_LON) / (MAX_LON - MIN_LON) * CANVAS_W
    y = CANVAS_H - ((lat - MIN_LAT) / (MAX_LAT - MIN_LAT) * CANVAS_H)
    return int(x), int(y)

# Puntos de interés fijos
POIS = [
    {"type": "HOSPITAL", "lat": 40.4800, "lon": -3.6500, "color": "#FF2A2A", "symbol": "H"},
    {"type": "HOSPITAL", "lat": 40.4100, "lon": -3.7000, "color": "#FF2A2A", "symbol": "H"},
    {"type": "GAS_STATION", "lat": 40.4400, "lon": -3.6800, "color": "#E5E500", "symbol": "G"}
]

class SimulatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Ambulance Digital Twin - COMMAND CENTER")
        self.root.geometry("1100x750")
        self.root.configure(bg=BG_COLOR)
        
        self.ambulances = {}
        self.running = True
        self.amb_icons = {} # Canvas items
        self.info_labels = {}
        
        # Estado de redes
        self.mqtt_on = tk.BooleanVar(value=True)
        self.p2p_on = tk.BooleanVar(value=True)
        self.http_on = tk.BooleanVar(value=True)

        self.setup_ui()
        self.root.after(100, self.start_simulation)
        self.root.after(200, lambda: threading.Thread(target=self.update_ui_loop, daemon=True).start())

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background=BG_COLOR)
        style.configure("TLabelframe", background=PANEL_BG, foreground=TEXT_COLOR, bordercolor="#333333")
        style.configure("TLabelframe.Label", background=PANEL_BG, foreground=ACCENT_COLOR, font=("Helvetica", 11, "bold"))
        style.configure("TButton", background="#333333", foreground=TEXT_COLOR, padding=5)
        style.map("TButton", background=[("active", ACCENT_COLOR)])
        style.configure("TCheckbutton", background=PANEL_BG, foreground=TEXT_COLOR)

        top_frame = tk.Frame(self.root, bg=BG_COLOR)
        top_frame.pack(fill="x", pady=5)
        tk.Label(top_frame, text="CENTRO DE MANDO DE SIMULACIONES - GEMELOS DIGITALES", font=("Consolas", 18, "bold"), bg=BG_COLOR, fg=ACCENT_COLOR).pack()

        main_pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=BG_COLOR, bd=0)
        main_pane.pack(fill="both", expand=True, padx=10, pady=5)

        # Izquierda: Lista de Ambulancias + Controles Red
        left_frame = tk.Frame(main_pane, bg=BG_COLOR)
        main_pane.add(left_frame, minsize=400)

        # Red Toggles
        net_frame = ttk.LabelFrame(left_frame, text="⚡ Control de Infraestructura de Red")
        net_frame.pack(fill="x", pady=5)
        ttk.Checkbutton(net_frame, text="Centralita (MQTT)", variable=self.mqtt_on, command=self.toggle_networks).grid(row=0, column=0, padx=10, pady=5)
        ttk.Checkbutton(net_frame, text="Malla Local (P2P)", variable=self.p2p_on, command=self.toggle_networks).grid(row=0, column=1, padx=10, pady=5)
        ttk.Checkbutton(net_frame, text="Backup Backend (HTTP)", variable=self.http_on, command=self.toggle_networks).grid(row=1, column=0, columnspan=2, padx=10, pady=5)

        # Flota
        self.amb_frame = ttk.LabelFrame(left_frame, text="🚑 Estado de la Flota en Tiempo Real")
        self.amb_frame.pack(fill="both", expand=True, pady=5)

        # Control Incidentes
        ctrl_frame = ttk.LabelFrame(left_frame, text="⚠️ Inyección de Incidentes (Pruebas)")
        ctrl_frame.pack(fill="x", pady=5)
        
        self.selected_amb = tk.StringVar(value="AMB-001")
        amb_selector = ttk.Combobox(ctrl_frame, textvariable=self.selected_amb, values=["AMB-001", "AMB-002", "AMB-003"], state="readonly", width=12)
        amb_selector.grid(row=0, column=0, padx=5, pady=5)
        ttk.Button(ctrl_frame, text="🚗 Inyectar Atasco", command=self.inject_traffic).grid(row=0, column=1, padx=3, pady=5)
        ttk.Button(ctrl_frame, text="🫀 Paciente Crítico", command=self.inject_vitals).grid(row=1, column=0, padx=3, pady=5)
        ttk.Button(ctrl_frame, text="🛞 Fallo Mecánico", command=self.inject_mechanical).grid(row=1, column=1, padx=3, pady=5)

        # Derecha: Mapa + Logs
        right_frame = tk.Frame(main_pane, bg=BG_COLOR)
        main_pane.add(right_frame, minsize=650)

        map_frame = ttk.LabelFrame(right_frame, text="🗺️ Radar Dinámico de Posicionamiento")
        map_frame.pack(fill="both", expand=True, pady=5)
        
        self.canvas = tk.Canvas(map_frame, bg="#0E1621", width=CANVAS_W, height=CANVAS_H, highlightthickness=1, highlightbackground="#333")
        self.canvas.pack(pady=10)
        
        self.draw_fixed_map_elements()

        self.log_frame = ttk.LabelFrame(right_frame, text="📡 Monitor de Señales (MQTT / P2P / HTTP)")
        self.log_frame.pack(fill="x", pady=5)
        self.log_text = tk.Text(self.log_frame, height=10, bg="#000000", fg="#00FF41", font=("Consolas", 10), bd=0)
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.log_text.insert(tk.END, "=== Iniciando subsistemas de telemetría y red ===\n")

    def draw_fixed_map_elements(self):
        # Dibujar POIs
        for poi in POIS:
            x, y = coord_to_pixel(poi["lat"], poi["lon"])
            r = 12
            self.canvas.create_oval(x-r, y-r, x+r, y+r, fill=poi["color"], outline="#FFF", width=2)
            self.canvas.create_text(x, y, text=poi["symbol"], fill="#000", font=("Helvetica", 10, "bold"))
            self.canvas.create_text(x, y+20, text=poi["type"], fill="#AAA", font=("Arial", 8))

    def init_ambulance_ui(self, am_id):
        frame = tk.Frame(self.amb_frame, bg=PANEL_BG, highlightbackground="#333", highlightthickness=1)
        frame.pack(fill="x", padx=10, pady=5)
        
        def on_click(event, a_id=am_id):
            self.show_telemetry_details(a_id)
            
        frame.bind("<Button-1>", on_click)
        
        lbl_title = tk.Label(frame, text=f"🚑 {am_id}", font=("Consolas", 12, "bold"), width=12, anchor="w", bg=PANEL_BG, fg=ACCENT_COLOR, cursor="hand2")
        lbl_title.grid(row=0, column=0, rowspan=2, padx=5, pady=5)
        lbl_title.bind("<Button-1>", on_click)
        
        lbl_vitals = tk.Label(frame, text="Vitales: -", width=35, anchor="w", bg=PANEL_BG, fg="#88CCFF", font=("Consolas", 9), cursor="hand2")
        lbl_vitals.grid(row=0, column=1, padx=5)
        lbl_vitals.bind("<Button-1>", on_click)
        
        lbl_mech = tk.Label(frame, text="Mecánica: -", width=35, anchor="w", bg=PANEL_BG, fg="#AADD88", font=("Consolas", 9), cursor="hand2")
        lbl_mech.grid(row=1, column=1, padx=5)
        lbl_mech.bind("<Button-1>", on_click)
        
        lbl_log = tk.Label(frame, text="Logística: -", width=35, anchor="w", bg=PANEL_BG, fg="#DDAAEE", font=("Consolas", 9), cursor="hand2")
        lbl_log.grid(row=0, column=2, padx=5)
        lbl_log.bind("<Button-1>", on_click)
        
        lbl_peers = tk.Label(frame, text="Net: -", width=35, anchor="w", bg=PANEL_BG, fg="#FFCC88", font=("Consolas", 9), cursor="hand2")
        lbl_peers.grid(row=1, column=2, padx=5)
        lbl_peers.bind("<Button-1>", on_click)
        
        self.info_labels[am_id] = {
            "vitals": lbl_vitals,
            "mech": lbl_mech,
            "log": lbl_log,
            "peers": lbl_peers
        }

        # Inicializar en el Canvas
        x, y = 0, 0 
        r = 8
        shape = self.canvas.create_oval(x-r, y-r, x+r, y+r, fill="#00AAFF", outline="#FFF")
        text = self.canvas.create_text(x, y-15, text=am_id, fill="#FFF", font=("Arial", 8))
        self.amb_icons[am_id] = {"shape": shape, "text": text}

    def toggle_networks(self):
        mqtt_on = self.mqtt_on.get()
        p2p_on = self.p2p_on.get()
        http_on = self.http_on.get()
        
        for am_id, amb in self.ambulances.items():
            if mqtt_on:
                if not amb.mqtt_client.is_connected():
                    amb.mqtt_client.connect()
            else:
                if amb.mqtt_client.is_connected():
                    amb.mqtt_client.disconnect()
                
            amb.p2p_enabled = p2p_on
            amb.http_enabled = http_on
            
        self.log_network(f"--- RECONFIGURACIÓN DE RED | MQTT:{'ON' if mqtt_on else 'OFF'} | P2P:{'ON' if p2p_on else 'OFF'} | HTTP:{'ON' if http_on else 'OFF'} ---")

    def start_simulation(self):
        broker = "localhost"
        
        self.ambulances["AMB-001"] = launch_ambulance("AMB-001", 40.4168, -3.7038, broker, log_callback=self.log_network)
        self.ambulances["AMB-002"] = launch_ambulance("AMB-002", 40.4170, -3.7040, broker, log_callback=self.log_network)
        self.ambulances["AMB-003"] = launch_ambulance("AMB-003", 40.4500, -3.6900, broker, log_callback=self.log_network)
        
        self.ambulances["AMB-001"].logistics.set_destination(40.4800, -3.6500)
        self.ambulances["AMB-002"].logistics.set_destination(40.4800, -3.6500)
        self.ambulances["AMB-003"].logistics.set_destination(40.4100, -3.7000)
        
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
                    
                    v_str = f"♥ {v.get('heart_rate')} bpm | O2: {v.get('oxygen_level')}% | {v.get('patient_status')}"
                    m_str = f"⛽ {m.get('fuel_level')}% | Temp: {m.get('engine_temperature')}C | {m.get('status')}"
                    l_str = f"📍 {l.get('speed')} km/h | Atasco: {'SI' if l.get('speed', 80) < 15.0 else 'NO'}"
                    
                    peers = len(twin.p2p_mesh.get_active_peers())
                    if twin.mqtt_client and twin.mqtt_client.is_connected():
                        p_str = f"📡 Vía MQTT | P2P listos: {peers}"
                    else:
                        p_str = f"⚠️ MQTT CAÍDO | P2P Broadcasting ({peers})"
                        
                    if not twin.p2p_enabled and not twin.mqtt_client.is_connected():
                         p_str = "❌ AISLADA (Solo HTTP Backup)"
                    
                    safe_update_label(ui_labels["vitals"], v_str)
                    safe_update_label(ui_labels["mech"], m_str)
                    safe_update_label(ui_labels["log"], l_str)
                    safe_update_label(ui_labels["peers"], p_str)
                    
                    # Update Canvas Coordinate Tracker
                    lat = l.get('latitude')
                    lon = l.get('longitude')
                    if lat and lon and am_id in self.amb_icons:
                        x, y = coord_to_pixel(lat, lon)
                        # Animar de forma fluida
                        current_coords = self.canvas.coords(self.amb_icons[am_id]["shape"])
                        if current_coords:
                            dx = x - (current_coords[0] + 8)
                            dy = y - (current_coords[1] + 8)
                            self.canvas.move(self.amb_icons[am_id]["shape"], dx, dy)
                            self.canvas.move(self.amb_icons[am_id]["text"], dx, dy)
                            
                            # Cambiar color basado en estado critico
                            color = "#00AAFF"
                            if m.get('status') == 'CRITICAL' or v.get('patient_status') == 'critical':
                                color = "#FF0000"
                            self.canvas.itemconfig(self.amb_icons[am_id]["shape"], fill=color)

    def log_network(self, message):
        def _append():
            if self.running and self.log_text.winfo_exists():
                timestamp = time.strftime("%H:%M:%S")
                if int(self.log_text.index('end-1c').split('.')[0]) > 100:
                    self.log_text.delete('1.0', '2.0')
                self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
                self.log_text.see(tk.END)
        self.root.after(0, _append)

    def inject_traffic(self):
        target = self.selected_amb.get()
        if target in self.ambulances:
            self.ambulances[target].inject_incident("logistics", "traffic_jam")
            self.log_network(f"[{target}] ⚠️ EVENTO: Atasco masivo inyectado en ruta.")

    def inject_vitals(self):
        target = self.selected_amb.get()
        if target in self.ambulances:
            self.ambulances[target].inject_incident("vitals", "drop_oxygen")
            self.log_network(f"[{target}] 🚨 EMERGENCIA: Oxígeno cayendo.")

    def inject_mechanical(self):
        target = self.selected_amb.get()
        if target in self.ambulances:
            self.ambulances[target].inject_incident("mechanical", "flat_tire")
            self.log_network(f"[{target}] 🛞 EVENTO: Rueda pinchada.")

    def show_telemetry_details(self, am_id):
        if am_id not in self.ambulances or not self.ambulances[am_id].current_state: return
        top = tk.Toplevel(self.root)
        top.title(f"Telemetría - {am_id}")
        top.geometry("450x650")
        top.configure(bg=BG_COLOR)
        tk.Label(top, text=f"Raw Stream: {am_id}", font=("Consolas", 12, "bold"), bg=BG_COLOR, fg=ACCENT_COLOR).pack(pady=10)
        tw = tk.Text(top, wrap="word", font=("Consolas", 10), bg="#000", fg="#0F0")
        tw.pack(fill="both", expand=True, padx=10, pady=10)
        def upd():
            if top.winfo_exists():
                tw.delete(1.0, tk.END)
                tw.insert(tk.END, json.dumps(self.ambulances[am_id].current_state, indent=4))
                top.after(1000, upd)
        upd()

    def on_closing(self):
        self.running = False
        for amb in self.ambulances.values():
            amb.stop()
            amb.p2p_mesh.stop()
        self.root.destroy()

def safe_update_label(label, text):
    try: label.config(text=text)
    except: pass

if __name__ == "__main__":
    root = tk.Tk()
    app = SimulatorGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
