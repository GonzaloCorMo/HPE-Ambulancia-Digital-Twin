import asyncio
import queue
import logging
import os
import time
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import socketio
import uvicorn
from contextlib import asynccontextmanager
from datetime import datetime

from engine import SimulatorEngine, SCENARIO_PRESETS
from telemetry.logistics import POIS, JAMS, add_poi, add_jam, remove_jam
from telemetry.vitals import PatientStatus
from telemetry.logistics import MissionStatus

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 1. Thread-safe log queue bridging sync Engine to async Sockets
log_queue = queue.Queue()

def engine_logger(msg: str) -> None:
    """Logger para el motor de simulación."""
    log_queue.put(msg)
    logger.info(msg)

# Inicializar motor
engine = SimulatorEngine(log_callback=engine_logger)

# 2. Async WebSockets Initialization
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

# 3. Main Data Broadcaster (Runs 10 times a second)
async def state_broadcaster():
    """Broadcastea estado de simulación a todos los clientes conectados."""
    logger.info("[SERVER] State broadcaster started.")
    broadcast_count = 0
    
    while True:
        try:
            # Drenar logs del queue
            log_messages = []
            while not log_queue.empty():
                try:
                    msg = log_queue.get_nowait()
                    log_messages.append(msg)
                except queue.Empty:
                    break
            
            # Enviar logs acumulados
            if log_messages:
                await sio.emit('log', {'messages': log_messages})
            
            # Compilar estado de la flota
            fleet_state = {}
            for am_id, amb in engine.ambulances.items():
                if hasattr(amb, 'current_state'):
                    fleet_state[am_id] = amb.current_state
            
            # Estadísticas del sistema
            system_stats = engine.get_statistics() if hasattr(engine, 'get_statistics') else {}
            
            state_payload = {
                "timestamp": datetime.now().isoformat(),
                "ambulances": fleet_state,
                "emergencies": engine.active_emergencies,
                "pois": POIS,
                "jams": JAMS,
                "is_simulating": engine.is_simulating,
                "speed_multiplier": engine.speed_multiplier,
                "system_stats": system_stats,
                "broadcast_id": broadcast_count
            }
            
            await sio.emit('sim_state', state_payload)
            broadcast_count += 1
            
            # Log de broadcast cada 100 ciclos
            if broadcast_count % 100 == 0:
                logger.debug(f"Broadcast #{broadcast_count}, ambulances: {len(fleet_state)}")
                
        except Exception as e:
            logger.error(f"Broadcaster Error: {e}")
        
        await asyncio.sleep(0.1)  # 10 Hz refresh rate

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestiona ciclo de vida de la aplicación FastAPI."""
    logger.info("Starting simulator application...")
    
    # Pre-cargar grafo de Madrid en background (al arrancar el servidor)
    def preload_graph():
        try:
            from telemetry.logistics import ensure_graph_for_area
            logger.info("Pre-cargando red viaria de Madrid en background...")
            ensure_graph_for_area(40.4168, -3.7038, 8000, "madrid")
            logger.info("Solicitud de precarga de grafo enviada.")
        except Exception as e:
            logger.error(f"Error pre-cargando grafo: {e}")
            engine.log_network(f"[SISTEMA] Aviso: {e}")
    
    # Ejecutar en thread separado para no bloquear
    asyncio.get_running_loop().run_in_executor(None, preload_graph)
    
    # Iniciar broadcaster
    broadcast_task = asyncio.create_task(state_broadcaster())
    engine.log_network("[SERVER] Simulador asíncrono inicializado. Cargando mapas en background...")
    
    yield  # La aplicación está corriendo
    
    # Shutdown
    logger.info("Shutting down simulator application...")
    broadcast_task.cancel()
    try:
        await broadcast_task
    except asyncio.CancelledError:
        pass
    
    if hasattr(engine, 'stop'):
        engine.stop()
    logger.info("Simulator application stopped.")

app = FastAPI(
    title="Ambulance Digital Twin API",
    description="API para simulación de gemelos digitales de ambulancias",
    version="2.0.0",
    lifespan=lifespan
)

socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Modelos Pydantic para validación
class SpawnRequest(BaseModel):
    """Modelo para solicitudes de creación de entidades."""
    type: str = Field(..., description="Tipo de entidad: AMBULANCE, EMERGENCY, HOSPITAL, GAS_STATION, JAM")
    lat: float = Field(..., ge=-90, le=90, description="Latitud")
    lon: float = Field(..., ge=-180, le=180, description="Longitud")
    severity: Optional[str] = Field("MEDIUM", description="Gravedad de emergencia: LOW, MEDIUM, HIGH, CRITICAL")
    name: Optional[str] = Field("", description="Nombre del POI")
    radius: Optional[float] = Field(0.005, description="Radio de atasco")

class DeleteRequest(BaseModel):
    """Modelo para solicitudes de eliminación."""
    lat: float = Field(..., ge=-90, le=90, description="Latitud")
    lon: float = Field(..., ge=-180, le=180, description="Longitud")
    threshold: Optional[float] = Field(0.005, description="Umbral de proximidad")

class SpeedRequest(BaseModel):
    """Modelo para cambio de velocidad."""
    multiplier: int = Field(..., ge=1, le=50, description="Multiplicador de velocidad (1-50)")

class NetworkRequest(BaseModel):
    """Modelo para configuración de red."""
    mqtt: bool = Field(True, description="Estado MQTT")
    p2p: bool = Field(True, description="Estado P2P")
    http: bool = Field(True, description="Estado HTTP")

class PresetRequest(BaseModel):
    """Modelo para carga de preset de escenario."""
    name: str = Field(..., description="Nombre del preset")

class MultiPresetRequest(BaseModel):
    """Modelo para carga múltiple de presets de escenario."""
    names: List[str] = Field(..., description="Lista de nombres de presets a cargar")
    clear_first: bool = Field(True, description="Limpiar el escenario antes de cargar")

class SeverityRequest(BaseModel):
    """Modelo para ajuste de severidad de eventos autónomos."""
    multiplier: float = Field(..., ge=0.1, le=10.0, description="Multiplicador de frecuencia de eventos (0.1-10)")

class FaultFrequencyRequest(BaseModel):
    """Modelo para ajuste de frecuencia de inyección de fallos mecánicos."""
    multiplier: float = Field(..., ge=0.1, le=10.0, description="Multiplicador de frecuencia de averías (0.1-10)")

class IncidentRequest(BaseModel):
    """Modelo para inyección de incidentes."""
    ambulance_id: str = Field(..., description="ID de ambulancia")
    category: str = Field(..., description="Categoría: mechanical, vitals, logistics")
    incident_type: str = Field(..., description="Tipo de incidente")

class TreatmentRequest(BaseModel):
    """Modelo para administración de tratamientos."""
    ambulance_id: str = Field(..., description="ID de ambulancia")
    treatment_type: str = Field(..., description="Tipo de tratamiento: oxygen, epinephrine, fluids, analgesia")

class MaintenanceRequest(BaseModel):
    """Modelo para solicitud de mantenimiento."""
    ambulance_id: str = Field(..., description="ID de ambulancia")

class AmbulanceCommandRequest(BaseModel):
    """Modelo para comandos de ambulancia."""
    ambulance_id: str = Field(..., description="ID de ambulancia")
    command: str = Field(..., description="Comando: hospital, emergency, refuel, maintenance, base")
    target_id: Optional[str] = Field(None, description="ID de objetivo (emergencia, hospital, etc.)")
    lat: Optional[float] = Field(None, description="Latitud del destino")
    lon: Optional[float] = Field(None, description="Longitud del destino")

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

# 5. REST Endpoints
@app.get("/api")
async def api_root():
    """Endpoint raíz de la API."""
    return {
        "name": "Ambulance Digital Twin API",
        "version": "2.0.0",
        "description": "Simulación de gemelos digitales de ambulancias en tiempo real",
        "endpoints": {
            "spawn": "/api/spawn",
            "delete": "/api/delete",
            "control": "/api/control",
            "ambulances": "/api/ambulances",
            "emergencies": "/api/emergencies",
            "statistics": "/api/statistics"
        },
        "status": "operational" if engine.running else "stopped"
    }

@app.get("/api/health")
async def health_check():
    """Endpoint de health check."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "engine_running": engine.running,
        "ambulances_count": len(engine.ambulances),
        "emergencies_active": len(engine.active_emergencies)
    }

@app.post("/api/spawn", status_code=201)
async def api_spawn(req: SpawnRequest):
    """
    Crea una nueva entidad en el mapa.
    
    Tipos soportados:
    - AMBULANCE: Despliega una ambulancia
    - EMERGENCY: Crea una emergencia
    - HOSPITAL/GAS_STATION: Añade punto de interés
    - JAM: Crea un atasco de tráfico
    """
    try:
        if req.type == "AMBULANCE":
            am_id = engine.spawn_ambulance(req.lat, req.lon)
            return {
                "status": "created",
                "type": "ambulance",
                "id": am_id,
                "location": {"lat": req.lat, "lon": req.lon}
            }
            
        elif req.type == "EMERGENCY":
            em_id = engine.spawn_emergency(req.lat, req.lon, req.severity)
            return {
                "status": "created",
                "type": "emergency",
                "id": em_id,
                "location": {"lat": req.lat, "lon": req.lon},
                "severity": req.severity
            }
            
        elif req.type in ["HOSPITAL", "GAS_STATION"]:
            add_poi(req.type, req.lat, req.lon, req.name)
            engine.log_network(f"[SISTEMA] Nuevo POI ({req.type}) construido en ({req.lat:.4f}, {req.lon:.4f}).")
            return {
                "status": "created",
                "type": "poi",
                "poi_type": req.type,
                "location": {"lat": req.lat, "lon": req.lon},
                "name": req.name
            }
            
        elif req.type == "JAM":
            add_jam(req.lat, req.lon, req.radius, severity=0.9, cause="user_created")
            engine.log_network(f"[SISTEMA] Atasco topográfico registrado en ({req.lat:.4f}, {req.lon:.4f}).")
            return {
                "status": "created",
                "type": "jam",
                "location": {"lat": req.lat, "lon": req.lon},
                "radius": req.radius
            }
            
        else:
            raise HTTPException(status_code=400, detail=f"Tipo no soportado: {req.type}")
            
    except Exception as e:
        logger.error(f"Error en spawn: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/delete")
async def api_delete(req: DeleteRequest):
    """
    Elimina una entidad cerca de las coordenadas especificadas.
    
    Busca en orden: ambulancias, POIs, atascos.
    """
    lat, lon = req.lat, req.lon
    threshold = req.threshold
    
    try:
        # Buscar ambulancia
        for am_id, amb in list(engine.ambulances.items()):
            # Support both .lat/.lon and .latitude/.longitude attribute naming
            amb_lat = getattr(amb.logistics, 'lat', None) or getattr(amb.logistics, 'latitude', None)
            amb_lon = getattr(amb.logistics, 'lon', None) or getattr(amb.logistics, 'longitude', None)
            if amb_lat is not None and amb_lon is not None:
                if (abs(amb_lat - lat) < threshold and abs(amb_lon - lon) < threshold):
                    if hasattr(amb, 'stop'):
                        amb.stop()
                    if hasattr(amb, 'p2p_mesh') and amb.p2p_mesh:
                        amb.p2p_mesh.stop()
                    
                    del engine.ambulances[am_id]
                    engine.log_network(f"[SISTEMA] 💥 Unidad {am_id} desmantelada.")
                    return {
                        "status": "deleted",
                        "type": "ambulance",
                        "id": am_id,
                        "location": {"lat": lat, "lon": lon}
                    }
        
        # Buscar POI
        for poi in list(POIS):
            if abs(poi["lat"] - lat) < threshold and abs(poi["lon"] - lon) < threshold:
                POIS.remove(poi)
                engine.log_network(f"[SISTEMA] 💥 POI ({poi.get('type', 'unknown')}) destruido.")
                return {
                    "status": "deleted",
                    "type": "poi",
                    "poi_type": poi.get("type"),
                    "location": {"lat": lat, "lon": lon}
                }
        
        # Buscar emergencia activa
        for em_id, em in list(engine.active_emergencies.items()):
            if abs(em.get("lat", 999) - lat) < threshold and abs(em.get("lon", 999) - lon) < threshold:
                del engine.active_emergencies[em_id]
                engine.log_network(f"[SISTEMA] 💥 Emergencia {em_id[:8]} eliminada.")
                return {
                    "status": "deleted",
                    "type": "emergency",
                    "id": em_id,
                    "location": {"lat": lat, "lon": lon}
                }
        
        # Buscar atasco
        for jam in list(JAMS):
            if abs(jam["lat"] - lat) < threshold and abs(jam["lon"] - lon) < threshold:
                JAMS.remove(jam)
                engine.log_network(f"[SISTEMA] 💥 Atasco eliminado.")
                return {
                    "status": "deleted",
                    "type": "jam",
                    "location": {"lat": lat, "lon": lon}
                }
        
        # Intentar remover atasco usando función específica
        if remove_jam(lat, lon, threshold):
            return {
                "status": "deleted",
                "type": "jam",
                "location": {"lat": lat, "lon": lon}
            }
        
        return {
            "status": "not_found",
            "message": "No se encontró entidad en las coordenadas especificadas"
        }
        
    except Exception as e:
        logger.error(f"Error en delete: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/control/toggle")
async def api_toggle_playback():
    """Alterna estado de reproducción de la simulación."""
    try:
        engine.toggle_playback()
        return {
            "status": "success",
            "is_simulating": engine.is_simulating,
            "message": "Simulación pausada" if not engine.is_simulating else "Simulación iniciada"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/control/status")
async def api_get_control_status():
    """Obtiene estado actual del control de simulación."""
    return {
        "is_simulating": engine.is_simulating,
        "speed_multiplier": engine.speed_multiplier,
        "network_status": {
            "mqtt": engine.mqtt_on,
            "p2p": engine.p2p_on,
            "http": engine.http_on
        }
    }

@app.post("/api/control/clear")
async def api_clear():
    """Limpia completamente el escenario de simulación."""
    try:
        engine.clear_all_scenario()
        return {
            "status": "cleared",
            "message": "Escenario limpiado exitosamente"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/control/speed")
async def api_speed(req: SpeedRequest):
    """Actualiza multiplicador de velocidad de simulación."""
    try:
        engine.update_speed_multiplier(req.multiplier)
        return {
            "status": "updated",
            "multiplier": req.multiplier,
            "message": f"Velocidad ajustada a {req.multiplier}x"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/network")
async def api_network(req: NetworkRequest):
    """Configura canales de comunicación."""
    try:
        engine.toggle_networks(req.mqtt, req.p2p, req.http)
        return {
            "status": "updated",
            "mqtt": req.mqtt,
            "p2p": req.p2p,
            "http": req.http,
            "message": "Configuración de red actualizada"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/route/{amb_id}")
async def api_get_route(amb_id: str):
    """Obtiene ruta actual de una ambulancia."""
    try:
        if amb_id in engine.ambulances:
            amb = engine.ambulances[amb_id]
            if hasattr(amb.logistics, 'route_geometry'):
                geom = amb.logistics.route_geometry
                step = getattr(amb.logistics, 'route_step', 0)
                total_steps = len(geom) if geom else 0
                
                # Calcular progreso
                progress = (step / total_steps * 100) if total_steps > 0 else 0
                
                return {
                    "ambulance_id": amb_id,
                    "route": geom,
                    "step": step,
                    "total_steps": total_steps,
                    "progress": round(progress, 1),
                    "has_destination": amb.logistics.destination is not None,
                    "destination_type": amb.logistics.destination_type
                }
        return {
            "ambulance_id": amb_id,
            "route": [],
            "step": 0,
            "total_steps": 0,
            "progress": 0,
            "has_destination": False
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ambulances")
async def api_get_ambulances():
    """Obtiene lista de todas las ambulancias con detalles."""
    try:
        ambulances = {}
        for am_id, amb in engine.ambulances.items():
            if hasattr(amb, 'get_detailed_status'):
                ambulances[am_id] = amb.get_detailed_status()
            else:
                # Información básica si no hay método detallado
                ambulances[am_id] = {
                    "id": am_id,
                    "running": getattr(amb, 'running', False),
                    "paused": getattr(amb, 'is_paused', False),
                    "position": {
                        "lat": amb.logistics.lat if hasattr(amb.logistics, 'lat') else 0,
                        "lon": amb.logistics.lon if hasattr(amb.logistics, 'lon') else 0
                    } if hasattr(amb, 'logistics') else {}
                }
        
        return {
            "count": len(ambulances),
            "ambulances": ambulances
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ambulances/{amb_id}")
async def api_get_ambulance(amb_id: str):
    """Obtiene detalles de una ambulancia específica."""
    try:
        if amb_id not in engine.ambulances:
            raise HTTPException(status_code=404, detail=f"Ambulance {amb_id} not found")
        
        amb = engine.ambulances[amb_id]
        details = {
            "id": amb_id,
            "running": getattr(amb, 'running', False),
            "paused": getattr(amb, 'is_paused', False),
            "speed_multiplier": getattr(amb, 'speed_multiplier', 1.0),
            "communication_errors": getattr(amb, 'communication_errors', 0) if hasattr(amb, 'communication_errors') else 0,
            "operational_hours": getattr(amb, 'operational_hours', 0.0) if hasattr(amb, 'operational_hours') else 0.0
        }
        
        # Añadir estados de motores si están disponibles
        if hasattr(amb, 'get_detailed_status'):
            details.update(amb.get_detailed_status())
        
        return details
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/emergencies")
async def api_get_emergencies():
    """Obtiene lista de emergencias activas."""
    try:
        return {
            "count": len(engine.active_emergencies),
            "emergencies": engine.active_emergencies
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/statistics")
async def api_get_statistics():
    """Obtiene estadísticas del sistema."""
    try:
        if hasattr(engine, 'get_statistics'):
            stats = engine.get_statistics()
        else:
            stats = {
                "total_ambulances": len(engine.ambulances),
                "active_emergencies": len(engine.active_emergencies),
                "emergencies_handled": 0,
                "average_response_time_min": 0,
                "is_simulating": engine.is_simulating,
                "speed_multiplier": engine.speed_multiplier,
                "network_status": {
                    "mqtt": engine.mqtt_on,
                    "p2p": engine.p2p_on,
                    "http": engine.http_on
                }
            }
        
        # Añadir estadísticas adicionales
        stats["timestamp"] = datetime.now().isoformat()
        stats["uptime"] = "N/A"  # Podría calcularse si se guarda start_time
        
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/state")
async def api_get_state():
    """Obtiene estado actual del sistema (similar a central/server.py para compatibilidad)."""
    try:
        # Compilar estado similar al servidor central
        state = {
            "timestamp": datetime.now().isoformat(),
            "engine_running": engine.running,
            "is_simulating": engine.is_simulating,
            "speed_multiplier": engine.speed_multiplier,
            "ambulances_count": len(engine.ambulances),
            "emergencies_active": len(engine.active_emergencies),
            "network_status": {
                "mqtt": engine.mqtt_on,
                "p2p": engine.p2p_on,
                "http": engine.http_on
            },
            "ambulances": {},
            "emergencies": engine.active_emergencies,
            "pois": POIS,
            "jams": JAMS
        }
        
        # Añadir información detallada de ambulancias
        for am_id, amb in engine.ambulances.items():
            if hasattr(amb, 'current_state') and amb.current_state:
                state["ambulances"][am_id] = amb.current_state
            else:
                # Información básica si no hay estado actual
                state["ambulances"][am_id] = {
                    "id": am_id,
                    "running": getattr(amb, 'running', False),
                    "position": {
                        "lat": amb.logistics.lat if hasattr(amb.logistics, 'lat') else 0,
                        "lon": amb.logistics.lon if hasattr(amb.logistics, 'lon') else 0
                    } if hasattr(amb, 'logistics') else {}
                }
        
        return state
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/incident/inject")
async def api_inject_incident(req: IncidentRequest):
    """Inyecta un incidente en una ambulancia."""
    try:
        if req.ambulance_id not in engine.ambulances:
            raise HTTPException(status_code=404, detail=f"Ambulance {req.ambulance_id} not found")
        
        amb = engine.ambulances[req.ambulance_id]
        if hasattr(amb, 'inject_incident'):
            success = amb.inject_incident(req.category, req.incident_type)
            if success:
                return {
                    "status": "injected",
                    "ambulance_id": req.ambulance_id,
                    "category": req.category,
                    "incident_type": req.incident_type,
                    "message": f"Incidente {req.incident_type} inyectado en {req.ambulance_id}"
                }
            else:
                raise HTTPException(status_code=400, detail="Failed to inject incident")
        else:
            raise HTTPException(status_code=400, detail="Ambulance does not support incident injection")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/treatment/administer")
async def api_administer_treatment(req: TreatmentRequest):
    """Administra un tratamiento médico a un paciente."""
    try:
        if req.ambulance_id not in engine.ambulances:
            raise HTTPException(status_code=404, detail=f"Ambulance {req.ambulance_id} not found")
        
        amb = engine.ambulances[req.ambulance_id]
        if hasattr(amb, 'administer_treatment'):
            success = amb.administer_treatment(req.treatment_type)
            if success:
                return {
                    "status": "administered",
                    "ambulance_id": req.ambulance_id,
                    "treatment_type": req.treatment_type,
                    "message": f"Tratamiento {req.treatment_type} administrado en {req.ambulance_id}"
                }
            else:
                raise HTTPException(status_code=400, detail="Failed to administer treatment (no patient or invalid type)")
        else:
            raise HTTPException(status_code=400, detail="Ambulance does not support treatment administration")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/maintenance/perform")
async def api_perform_maintenance(req: MaintenanceRequest):
    """Realiza mantenimiento en una ambulancia."""
    try:
        if req.ambulance_id not in engine.ambulances:
            raise HTTPException(status_code=404, detail=f"Ambulance {req.ambulance_id} not found")
        
        amb = engine.ambulances[req.ambulance_id]
        if hasattr(amb, 'perform_maintenance'):
            success = amb.perform_maintenance()
            if success:
                return {
                    "status": "maintained",
                    "ambulance_id": req.ambulance_id,
                    "message": f"Mantenimiento realizado en {req.ambulance_id}"
                }
            else:
                raise HTTPException(status_code=400, detail="Failed to perform maintenance")
        else:
            raise HTTPException(status_code=400, detail="Ambulance does not support maintenance")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/patient/set")
async def api_set_patient_info(ambulance_id: str, age: int = 45, has_patient: bool = True):
    """Configura información del paciente en una ambulancia."""
    try:
        if ambulance_id not in engine.ambulances:
            raise HTTPException(status_code=404, detail=f"Ambulance {ambulance_id} not found")
        
        amb = engine.ambulances[ambulance_id]
        if hasattr(amb, 'set_patient_info'):
            success = amb.set_patient_info(age, has_patient)
            if success:
                return {
                    "status": "set",
                    "ambulance_id": ambulance_id,
                    "age": age,
                    "has_patient": has_patient,
                    "message": f"Información de paciente configurada en {ambulance_id}"
                }
            else:
                raise HTTPException(status_code=400, detail="Failed to set patient info")
        else:
            raise HTTPException(status_code=400, detail="Ambulance does not support patient configuration")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ambulance/command")
async def api_ambulance_command(req: AmbulanceCommandRequest):
    """Ejecuta un comando en una ambulancia."""
    try:
        if req.ambulance_id not in engine.ambulances:
            raise HTTPException(status_code=404, detail=f"Ambulance {req.ambulance_id} not found")
        
        amb = engine.ambulances[req.ambulance_id]
        
        if req.command == "hospital":
            # Enviar a hospital más cercano
            hospitals = [p for p in POIS if p.get("type") == "HOSPITAL"]
            if hospitals:
                # Encontrar hospital más cercano
                nearest_hospital = min(
                    hospitals,
                    key=lambda h: engine._calculate_distance_km(
                        amb.logistics.lat, amb.logistics.lon,
                        h["lat"], h["lon"]
                    )
                )
                if hasattr(amb.logistics, 'set_destination'):
                    amb.logistics.set_destination(
                        nearest_hospital["lat"], nearest_hospital["lon"], "HOSPITAL"
                    )
                    amb.logistics.mission_status = MissionStatus.IN_USE.value
                    amb.logistics.action_message = "Dirigiéndose al hospital"
                    engine.log_network(f"[COMANDO] 🏥 Unidad {req.ambulance_id} enviada al hospital.")
                    return {
                        "status": "executed",
                        "ambulance_id": req.ambulance_id,
                        "command": "hospital",
                        "destination": {
                            "lat": nearest_hospital["lat"],
                            "lon": nearest_hospital["lon"],
                            "type": "HOSPITAL"
                        },
                        "message": f"Ambulancia {req.ambulance_id} enviada al hospital"
                    }
            else:
                raise HTTPException(status_code=400, detail="No hay hospitales disponibles")
        
        elif req.command == "emergency":
            # Asignar a emergencia existente o crear una nueva
            if req.target_id and req.target_id in engine.active_emergencies:
                # Asignar a emergencia existente
                emergency = engine.active_emergencies[req.target_id]
                if emergency["status"] == "INITIATED":
                    emergency["status"] = "PROCESSING"
                    emergency["assigned_ambulance"] = req.ambulance_id
                    emergency["assigned_at"] = time.time()
                    
                    if hasattr(amb.logistics, 'set_destination'):
                        amb.logistics.set_destination(
                            emergency["lat"], emergency["lon"], "EMERGENCY"
                        )
                        amb.logistics.mission_status = MissionStatus.IN_USE.value
                        amb.logistics.action_message = "Respondiendo a emergencia"
                    
                    engine.log_network(f"[COMANDO] 🚨 Unidad {req.ambulance_id} asignada a emergencia {req.target_id}.")
                    return {
                        "status": "executed",
                        "ambulance_id": req.ambulance_id,
                        "command": "emergency",
                        "target_id": req.target_id,
                        "message": f"Ambulancia {req.ambulance_id} asignada a emergencia {req.target_id}"
                    }
                else:
                    raise HTTPException(status_code=400, detail=f"Emergencia {req.target_id} no está disponible")
            else:
                # Crear nueva emergencia cerca de la ambulancia
                if req.lat is not None and req.lon is not None:
                    lat, lon = req.lat, req.lon
                else:
                    lat, lon = amb.logistics.lat + 0.001, amb.logistics.lon + 0.001
                
                em_id = engine.spawn_emergency(lat, lon, "HIGH")
                engine.active_emergencies[em_id]["assigned_ambulance"] = req.ambulance_id
                engine.active_emergencies[em_id]["status"] = "PROCESSING"
                engine.active_emergencies[em_id]["assigned_at"] = time.time()
                
                if hasattr(amb.logistics, 'set_destination'):
                    amb.logistics.set_destination(lat, lon, "EMERGENCY")
                    amb.logistics.mission_status = MissionStatus.IN_USE.value
                    amb.logistics.action_message = "Respondiendo a emergencia creada"
                
                engine.log_network(f"[COMANDO] 🚨 Unidad {req.ambulance_id} asignada a nueva emergencia {em_id}.")
                return {
                    "status": "executed",
                    "ambulance_id": req.ambulance_id,
                    "command": "emergency",
                    "emergency_id": em_id,
                    "message": f"Ambulancia {req.ambulance_id} asignada a nueva emergencia {em_id}"
                }
        
        elif req.command == "refuel":
            # Enviar a gasolinera más cercana
            gas_stations = [p for p in POIS if p.get("type") == "GAS_STATION"]
            if gas_stations:
                nearest_gas = min(
                    gas_stations,
                    key=lambda g: engine._calculate_distance_km(
                        amb.logistics.lat, amb.logistics.lon,
                        g["lat"], g["lon"]
                    )
                )
                if hasattr(amb.logistics, 'set_destination'):
                    amb.logistics.set_destination(
                        nearest_gas["lat"], nearest_gas["lon"], "GAS_STATION"
                    )
                    amb.logistics.mission_status = MissionStatus.REFUELING.value
                    amb.logistics.action_message = "Dirigiéndose a repostar"
                    engine.log_network(f"[COMANDO] ⛽ Unidad {req.ambulance_id} enviada a repostar.")
                    return {
                        "status": "executed",
                        "ambulance_id": req.ambulance_id,
                        "command": "refuel",
                        "destination": {
                            "lat": nearest_gas["lat"],
                            "lon": nearest_gas["lon"],
                            "type": "GAS_STATION"
                        },
                        "message": f"Ambulancia {req.ambulance_id} enviada a repostar"
                    }
            else:
                raise HTTPException(status_code=400, detail="No hay gasolineras disponibles")
        
        elif req.command == "maintenance":
            # Solicitar mantenimiento
            if hasattr(amb, 'perform_maintenance'):
                success = amb.perform_maintenance()
                if success:
                    engine.log_network(f"[COMANDO] 🔧 Unidad {req.ambulance_id} en mantenimiento.")
                    return {
                        "status": "executed",
                        "ambulance_id": req.ambulance_id,
                        "command": "maintenance",
                        "message": f"Ambulancia {req.ambulance_id} en mantenimiento"
                    }
                else:
                    raise HTTPException(status_code=400, detail="No se pudo realizar mantenimiento")
            else:
                # Simular mantenimiento cambiando estado
                amb.logistics.mission_status = MissionStatus.MAINTENANCE.value
                amb.logistics.action_message = "En mantenimiento"
                engine.log_network(f"[COMANDO] 🔧 Unidad {req.ambulance_id} puesta en mantenimiento.")
                return {
                    "status": "executed",
                    "ambulance_id": req.ambulance_id,
                    "command": "maintenance",
                    "message": f"Ambulancia {req.ambulance_id} puesta en mantenimiento"
                }
        
        elif req.command == "base":
            # Enviar a base (hospital más cercano como base)
            hospitals = [p for p in POIS if p.get("type") == "HOSPITAL"]
            if hospitals:
                nearest_hospital = min(
                    hospitals,
                    key=lambda h: engine._calculate_distance_km(
                        amb.logistics.lat, amb.logistics.lon,
                        h["lat"], h["lon"]
                    )
                )
                if hasattr(amb.logistics, 'set_destination'):
                    amb.logistics.set_destination(
                        nearest_hospital["lat"], nearest_hospital["lon"], "BASE"
                    )
                    amb.logistics.mission_status = MissionStatus.ACTIVE.value
                    amb.logistics.action_message = "Regresando a base"
                    engine.log_network(f"[COMANDO] 🏠 Unidad {req.ambulance_id} regresando a base.")
                    return {
                        "status": "executed",
                        "ambulance_id": req.ambulance_id,
                        "command": "base",
                        "destination": {
                            "lat": nearest_hospital["lat"],
                            "lon": nearest_hospital["lon"],
                            "type": "BASE"
                        },
                        "message": f"Ambulancia {req.ambulance_id} regresando a base"
                    }
            else:
                raise HTTPException(status_code=400, detail="No hay bases disponibles (hospitales)")
        
        else:
            raise HTTPException(status_code=400, detail=f"Comando no soportado: {req.command}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error ejecutando comando: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/presets")
async def api_list_presets():
    """Lista los presets de escenario disponibles."""
    return {
        "presets": {
            name: {
                "name": data["name"],
                "hospitals": len(data["hospitals"]),
                "gas_stations": len(data["gas_stations"]),
                "ambulances": len(data["ambulance_positions"]),
            }
            for name, data in SCENARIO_PRESETS.items()
        }
    }

@app.post("/api/preset", status_code=200)
async def api_load_preset(req: PresetRequest):
    """Carga un preset de escenario (hospitales, gasolineras, ambulancias)."""
    try:
        available = list(SCENARIO_PRESETS.keys())
        if req.name not in SCENARIO_PRESETS:
            raise HTTPException(
                status_code=400,
                detail=f"Preset '{req.name}' no encontrado. Disponibles: {available}"
            )
        success = engine.load_preset(req.name)
        if success:
            return {
                "status": "loaded",
                "preset": req.name,
                "message": f"Preset '{req.name}' cargado exitosamente",
                "ambulances": len(engine.ambulances),
            }
        else:
            raise HTTPException(status_code=500, detail="Error cargando preset")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/presets/load_multi", status_code=200)
async def api_load_multi_preset(req: MultiPresetRequest):
    """Carga múltiples presets de escenario simultáneamente."""
    try:
        available = list(SCENARIO_PRESETS.keys())
        invalid = [n for n in req.names if n not in SCENARIO_PRESETS]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Presets no encontrados: {invalid}. Disponibles: {available}"
            )
        if not req.names:
            raise HTTPException(status_code=400, detail="Debe seleccionar al menos un preset")

        loaded = []
        for i, name in enumerate(req.names):
            if i == 0 and req.clear_first:
                success = engine.load_preset(name)  # clears first
            else:
                success = engine.load_preset_additive(name)  # additive
            if success:
                loaded.append(name)

        return {
            "status": "loaded",
            "presets": loaded,
            "message": f"{len(loaded)} preset(s) cargados: {', '.join(loaded)}",
            "ambulances": len(engine.ambulances),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/control/severity", status_code=200)
async def api_set_severity(req: SeverityRequest):
    """Ajusta el multiplicador de frecuencia de eventos de simulación autónoma."""
    try:
        engine.set_event_severity(req.multiplier)
        return {
            "status": "updated",
            "multiplier": req.multiplier,
            "message": f"Frecuencia de eventos ajustada a {req.multiplier:.1f}x"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/control/fault_frequency", status_code=200)
async def api_set_fault_frequency(req: FaultFrequencyRequest):
    """Ajusta el multiplicador de frecuencia de inyección de fallos mecánicos."""
    try:
        engine.set_fault_frequency(req.multiplier)
        return {
            "status": "updated",
            "multiplier": req.multiplier,
            "message": f"Frecuencia de averías ajustada a {req.multiplier:.1f}x"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/auto_simulation", status_code=200)
async def api_auto_simulation():
    """
    Inicia la generación automática de eventos (emergencias, atascos, anomalías IA).
    Requiere hospitales y ambulancias en el mapa.
    """
    try:
        success, message = engine.start_auto_simulation()
        return {
            "status": "started" if success else "error",
            "message": message,
            "ambulances": len(engine.ambulances),
            "is_simulating": engine.is_simulating,
        }
    except Exception as e:
        logger.error(f"Error iniciando simulación autónoma: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 6. WebSocket Event Handlers
@sio.event
async def connect(sid, environ):
    """Maneja conexión de cliente WebSocket."""
    logger.info(f"Client connected: {sid}")
    await sio.emit('log', {'messages': [f"[SERVER] Cliente {sid[:8]} conectado al centro de operaciones."]}, room=sid)

@sio.event
async def disconnect(sid):
    """Maneja desconexión de cliente WebSocket."""
    logger.info(f"Client disconnected: {sid}")

@app.get("/backup_dashboard", include_in_schema=False)
async def serve_backup_dashboard():
    """Sirve el dashboard de backups."""
    from fastapi.responses import FileResponse
    backup_path = os.path.join("static", "backup_dashboard.html")
    if os.path.exists(backup_path):
        return FileResponse(backup_path)
    else:
        return {"message": "Backup dashboard no encontrado, ejecuta el servidor y accede a /static/backup_dashboard.html"}

# --- Backup API Endpoints ---
backup_store = []  # Simulación de almacenamiento de backups

@app.post("/api/backup_state", status_code=201)
async def api_backup_state(req: BackupRequest):
    """Guarda un estado de backup crítico."""
    try:
        if not req.timestamp:
            req.timestamp = time.time()
        
        backup_entry = {
            "id": f"backup-{len(backup_store)}",
            "ambulance_id": req.ambulance_id,
            "timestamp": req.timestamp,
            "critical_data": req.critical_data
        }
        
        backup_store.append(backup_entry)
        logger.info(f"Backup recibido: {req.ambulance_id} at {req.timestamp}")
        
        return {
            "status": "stored",
            "backup_id": backup_entry["id"],
            "ambulance_id": req.ambulance_id,
            "timestamp": req.timestamp,
            "message": "Backup almacenado exitosamente"
        }
    except Exception as e:
        logger.error(f"Error storing backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/backups/list")
async def api_list_backups(filter: BackupFilter = None):
    """Obtiene lista de backups con filtros opcionales."""
    try:
        if filter is None:
            filter = BackupFilter()
        
        filtered = backup_store
        
        # Aplicar filtros
        if filter.ambulance_id:
            filtered = [b for b in filtered if b["ambulance_id"] == filter.ambulance_id]
        
        if filter.start_time:
            filtered = [b for b in filtered if b["timestamp"] >= filter.start_time]
        
        if filter.end_time:
            filtered = [b for b in filtered if b["timestamp"] <= filter.end_time]
        
        if filter.data_type:
            filtered = [b for b in filtered if (
                (filter.data_type == "position" and "position" in b["critical_data"]) or
                (filter.data_type == "patient" and "patient_status" in b["critical_data"]) or
                (filter.data_type == "fuel" and "fuel_level" in b["critical_data"]) or
                (filter.data_type == "mechanical" and "mechanical_status" in b["critical_data"])
            )]
        
        # Ordenar por timestamp descendente
        filtered.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # Aplicar límite
        limited = filtered[:filter.limit]
        
        return {
            "count": len(filtered),
            "backups": limited,
            "filter": filter.dict() if filter else {}
        }
    except Exception as e:
        logger.error(f"Error listing backups: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/backups/count")
async def api_count_backups():
    """Obtiene conteo de backups."""
    return {
        "total": len(backup_store),
        "last_24h": len([b for b in backup_store if b["timestamp"] > time.time() - 86400]),
        "ambulance_count": len(set(b["ambulance_id"] for b in backup_store if "ambulance_id" in b))
    }

@app.delete("/api/backups/clear")
async def api_clear_backups():
    """Limpia todos los backups almacenados."""
    backup_store.clear()
    return {
        "status": "cleared",
        "message": "Todos los backups han sido eliminados"
    }

# 7. Serve the Dashboard Frontend
# Asegurar que el directorio static existe
if not os.path.exists("static"):
    os.makedirs("static")

# Montar archivos estáticos en la raíz para servir el frontend
app.mount("/", StaticFiles(directory="static", html=True), name="static")

# Redirigir / a index.html (ya lo hace StaticFiles con html=True)
# Pero agregamos un endpoint para / que redirija por si acaso
@app.get("/", include_in_schema=False)
async def serve_frontend():
    """Sirve el frontend del dashboard."""
    from fastapi.responses import FileResponse
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        return {"message": "Frontend no encontrado, ejecuta el servidor y accede a /static/index.html"}

if __name__ == "__main__":
    logger.info("Starting Ambulance Digital Twin server...")
    uvicorn.run(
        "app:socket_app",
        host="0.0.0.0",
        port=5000,
        reload=False,
        log_level="info"
    )