from fastapi import FastAPI, Request
import paho.mqtt.client as mqtt
import json
import uvicorn
import threading
import time
import math

app = FastAPI(title="Ambulance Centralita")

# In-memory storage for demonstration
mqtt_state_db = {}
https_backup_db = []

# --- Traffic Analysis Logic ---
def detect_traffic_issues():
    # Simple algorithm: if multiple ambulances are very close and speed is very low -> traffic jam
    while True:
        time.sleep(5)
        ambulances_in_area = []
        for am_id, state in mqtt_state_db.items():
            try:
                log_data = state.get("logistics", {})
                lat = log_data.get("latitude")
                lon = log_data.get("longitude")
                speed = log_data.get("speed")
                if lat is not None and lon is not None and speed is not None:
                     if speed < 15.0: # arbitrary low speed threshold
                        ambulances_in_area.append((am_id, lat, lon))
            except Exception as e:
                pass
                
        # Calculate distances between slow ambulances
        jam_detected = False
        for i in range(len(ambulances_in_area)):
            for j in range(i+1, len(ambulances_in_area)):
                id1, lat1, lon1 = ambulances_in_area[i]
                id2, lat2, lon2 = ambulances_in_area[j]
                
                # Very rough distance (Euclidean on lat/lon, for demo purposes)
                dist = math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2)
                if dist < 0.005: # Arbitrary threshold roughly 500 meters
                    jam_detected = True
                    print(f"[CENTRALITA] 🚨 ALERTA: Posible atasco o accidente detectado entre las ambulancias {id1} y {id2}.")
        
# --- HTTP Endpoints ---
@app.post("/api/backup_state")
async def receive_backup(request: Request):
    data = await request.json()
    https_backup_db.append(data)
    # print(f"[HTTPS SERVER] Recibido backup de {data.get('ambulance_id')}")
    return {"status": "success", "message": "Backup stored"}

@app.get("/api/state")
async def get_current_state():
    return {"live_mqtt_data": mqtt_state_db, "backup_count": len(https_backup_db)}


# --- MQTT Handlers ---
def on_connect(client, userdata, flags, rc):
    print("[CENTRALITA MQTT] Conectado al broker de recepción")
    client.subscribe("ambulance/+/state")

def on_message(client, userdata, msg):
    try:
        topic_parts = msg.topic.split("/")
        am_id = topic_parts[1]
        payload = json.loads(msg.payload.decode("utf-8"))
        mqtt_state_db[am_id] = payload
        # print(f"[CENTRALITA MQTT] Recibida telemetría MQTT en vivo de {am_id}")
    except Exception as e:
        print(f"[CENTRALITA MQTT] Error procesando mensaje: {e}")

def run_mqtt_listener(broker_url="localhost", port=1883):
    client = mqtt.Client(client_id="Centralita_Receiver")
    client.on_connect = on_connect
    client.on_message = on_message
    
    # Try connecting, with retries if the broker is taking time to start
    connected = False
    while not connected:
        try:
            client.connect(broker_url, port, 60)
            connected = True
        except:
            print("[CENTRALITA] Esperando al Broker MQTT...")
            time.sleep(2)
            
    client.loop_forever()

if __name__ == "__main__":
    # Start traffic analysis thread
    threading.Thread(target=detect_traffic_issues, daemon=True).start()
    
    # Start MQTT listening in a background thread
    threading.Thread(target=run_mqtt_listener, daemon=True).start()
    
    print("[CENTRALITA] Iniciando servidor FastAPI...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
