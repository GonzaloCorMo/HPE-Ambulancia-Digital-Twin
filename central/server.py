from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import paho.mqtt.client as mqtt
import json
import uvicorn
import threading
import time
import math
import uuid
from datetime import datetime, timedelta

app = FastAPI(title="Ambulance Centralita")

# Add CORS middleware to allow requests from the dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for demonstration
mqtt_state_db = {}
https_backup_db = []
backup_stats = {
    "total_received": 0,
    "last_24h": 0,
    "unique_ambulances": set(),
    "start_time": time.time()
}

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

# --- Models for Backup API ---
class BackupRequest(BaseModel):
    ambulance_id: str
    timestamp: Optional[float] = None
    critical_data: Dict[str, Any]

class BackupFilter(BaseModel):
    ambulance_id: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    data_type: Optional[str] = None  # position, patient, fuel, mechanical
    limit: Optional[int] = 100
        
# --- HTTP Endpoints ---
@app.get("/api/health")
async def health_check():
    """Endpoint de health check para el servidor central."""
    try:
        now = time.time()
        
        # Calcular métricas de salud
        backup_count = len(https_backup_db)
        unique_ambulances = len(backup_stats["unique_ambulances"])
        recent_backups = [b for b in https_backup_db if b.get("timestamp", 0) > now - 300]  # Últimos 5 minutos
        
        # Verificar conectividad MQTT (estado de la base de datos en memoria)
        mqtt_connected = len(mqtt_state_db) > 0  # Simplificado: asume conectado si hay datos
        
        return {
            "status": "healthy",
            "timestamp": now,
            "uptime_hours": (now - backup_stats["start_time"]) / 3600,
            "backups": {
                "total": backup_count,
                "unique_ambulances": unique_ambulances,
                "recent_5min": len(recent_backups)
            },
            "mqtt": {
                "connected": mqtt_connected,
                "active_ambulances": len(mqtt_state_db)
            },
            "version": "1.0.0",
            "service": "central_server"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": time.time()
        }

@app.post("/api/backup_state")
async def receive_backup(request: Request):
    """Endpoint para recibir backups HTTPS de ambulancias."""
    try:
        data = await request.json()
        
        # Asegurar que el backup tenga ID y timestamp
        backup_id = data.get("id", f"backup-{uuid.uuid4().hex[:8]}")
        timestamp = data.get("timestamp", time.time())
        ambulance_id = data.get("ambulance_id", "unknown")
        critical_data = data.get("critical_data", {})
        
        # Crear backup enriquecido
        enriched_backup = {
            "id": backup_id,
            "ambulance_id": ambulance_id,
            "timestamp": timestamp,
            "received_at": time.time(),
            "critical_data": critical_data,
            "data_size": len(json.dumps(data))
        }
        
        # Agregar a la base de datos
        https_backup_db.append(enriched_backup)
        
        # Actualizar estadísticas
        backup_stats["total_received"] += 1
        backup_stats["unique_ambulances"].add(ambulance_id)
        
        # Limitar tamaño de la base de datos (mantener últimos 1000 backups)
        if len(https_backup_db) > 1000:
            removed = https_backup_db.pop(0)
            print(f"[CENTRALITA] Backup antiguo eliminado: {removed.get('id')}")
        
        # print(f"[HTTPS SERVER] Recibido backup de {ambulance_id}")
        return {
            "status": "success", 
            "message": "Backup stored",
            "backup_id": backup_id,
            "timestamp": timestamp
        }
    except Exception as e:
        print(f"[CENTRALITA] Error procesando backup: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/state")
async def get_current_state():
    """Endpoint para obtener estado actual del sistema."""
    return {
        "live_mqtt_data": mqtt_state_db, 
        "backup_count": len(https_backup_db),
        "backup_stats": {
            "total_received": backup_stats["total_received"],
            "unique_ambulances": len(backup_stats["unique_ambulances"]),
            "uptime_hours": (time.time() - backup_stats["start_time"]) / 3600
        }
    }

# --- Backup Management Endpoints ---
@app.post("/api/backups/list")
async def list_backups(filter: BackupFilter):
    """Lista backups con filtros opcionales."""
    try:
        filtered_backups = https_backup_db.copy()
        
        # Aplicar filtros
        if filter.ambulance_id:
            filtered_backups = [b for b in filtered_backups if b.get("ambulance_id") == filter.ambulance_id]
        
        if filter.start_time:
            filtered_backups = [b for b in filtered_backups if b.get("timestamp", 0) >= filter.start_time]
        
        if filter.end_time:
            filtered_backups = [b for b in filtered_backups if b.get("timestamp", 0) <= filter.end_time]
        
        if filter.data_type:
            # Filtrar por tipo de dato en critical_data
            filtered_backups = [b for b in filtered_backups if has_data_type(b.get("critical_data", {}), filter.data_type)]
        
        # Ordenar por timestamp descendente (más recientes primero)
        filtered_backups.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        
        # Limitar resultados
        if filter.limit and filter.limit > 0:
            filtered_backups = filtered_backups[:filter.limit]
        
        return {
            "status": "success",
            "count": len(filtered_backups),
            "total_available": len(https_backup_db),
            "backups": filtered_backups
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/backups/stats")
async def get_backup_stats():
    """Obtiene estadísticas detalladas de backups."""
    try:
        now = time.time()
        twenty_four_hours_ago = now - 86400
        
        # Calcular backups de las últimas 24h
        recent_backups = [b for b in https_backup_db if b.get("timestamp", 0) > twenty_four_hours_ago]
        
        # Agrupar por tipo de dato
        data_type_counts = {
            "position": 0,
            "patient": 0,
            "fuel": 0,
            "mechanical": 0,
            "mixed": 0
        }
        
        for backup in https_backup_db:
            data = backup.get("critical_data", {})
            data_types = []
            
            if data.get("position"):
                data_types.append("position")
            if data.get("patient_status"):
                data_types.append("patient")
            if data.get("fuel_level") is not None:
                data_types.append("fuel")
            if data.get("mechanical_status"):
                data_types.append("mechanical")
            
            if len(data_types) == 0:
                data_type_counts["mixed"] += 1
            elif len(data_types) == 1:
                data_type_counts[data_types[0]] += 1
            else:
                data_type_counts["mixed"] += 1
        
        # Calcular tamaño total de datos
        total_size_bytes = sum(b.get("data_size", 0) for b in https_backup_db)
        
        return {
            "status": "success",
            "stats": {
                "total_backups": len(https_backup_db),
                "last_24h": len(recent_backups),
                "unique_ambulances": len(backup_stats["unique_ambulances"]),
                "data_type_distribution": data_type_counts,
                "total_data_size_bytes": total_size_bytes,
                "avg_backup_size_bytes": total_size_bytes / len(https_backup_db) if https_backup_db else 0,
                "uptime_hours": (now - backup_stats["start_time"]) / 3600,
                "backups_per_hour": backup_stats["total_received"] / ((now - backup_stats["start_time"]) / 3600) if now > backup_stats["start_time"] else 0
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/backups/clear")
async def clear_backups(hours_old: Optional[int] = 24, max_backups: Optional[int] = None):
    """Elimina backups antiguos o limita la cantidad máxima."""
    try:
        initial_count = len(https_backup_db)
        
        if hours_old:
            # Eliminar backups más antiguos que hours_old
            cutoff_time = time.time() - (hours_old * 3600)
            before_clear = len(https_backup_db)
            https_backup_db[:] = [b for b in https_backup_db if b.get("timestamp", 0) > cutoff_time]
            cleared_by_age = before_clear - len(https_backup_db)
        else:
            cleared_by_age = 0
        
        if max_backups and max_backups > 0:
            # Mantener solo los últimos max_backups
            if len(https_backup_db) > max_backups:
                cleared_by_limit = len(https_backup_db) - max_backups
                https_backup_db[:] = https_backup_db[-max_backups:]
            else:
                cleared_by_limit = 0
        else:
            cleared_by_limit = 0
        
        final_count = len(https_backup_db)
        total_cleared = cleared_by_age + cleared_by_limit
        
        return {
            "status": "success",
            "message": f"Cleared {total_cleared} backups",
            "initial_count": initial_count,
            "final_count": final_count,
            "cleared_by_age": cleared_by_age,
            "cleared_by_limit": cleared_by_limit
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/backups/export")
async def export_backups(format: str = "json"):
    """Exporta todos los backups en el formato especificado."""
    try:
        if format.lower() == "json":
            return {
                "status": "success",
                "format": "json",
                "count": len(https_backup_db),
                "backups": https_backup_db,
                "exported_at": time.time()
            }
        else:
            raise HTTPException(status_code=400, detail=f"Formato no soportado: {format}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/backups/health")
async def backup_health():
    """Endpoint de health check para el sistema de backups."""
    try:
        now = time.time()
        recent_backups = [b for b in https_backup_db if b.get("timestamp", 0) > now - 300]  # Últimos 5 minutos
        
        return {
            "status": "healthy",
            "timestamp": now,
            "total_backups": len(https_backup_db),
            "recent_backups_5min": len(recent_backups),
            "unique_ambulances": len(backup_stats["unique_ambulances"]),
            "uptime_hours": (now - backup_stats["start_time"]) / 3600,
            "storage_usage_percent": (len(https_backup_db) / 1000) * 100  # Basado en límite de 1000
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Helper Functions ---
def has_data_type(critical_data: Dict[str, Any], data_type: str) -> bool:
    """Verifica si los datos críticos contienen un tipo específico."""
    if data_type == "position":
        return "position" in critical_data
    elif data_type == "patient":
        return "patient_status" in critical_data
    elif data_type == "fuel":
        return "fuel_level" in critical_data
    elif data_type == "mechanical":
        return "mechanical_status" in critical_data
    return False


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
