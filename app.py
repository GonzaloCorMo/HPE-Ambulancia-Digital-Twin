import asyncio
import queue
from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import socketio
import uvicorn
from contextlib import asynccontextmanager

from engine import SimulatorEngine
from telemetry.logistics import POIS, JAMS, add_poi, add_jam

# 1. Thread-safe log queue bridging sync Engine to async Sockets
log_queue = queue.Queue()

def engine_logger(msg):
    log_queue.put(msg)

engine = SimulatorEngine(log_callback=engine_logger)

# 2. Async WebSockets Initialization
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

# 3. Main Data Broadcaster (Runs 10 times a second)
async def state_broadcaster():
    print("[SERVER] State broadcaster started.")
    while True:
        try:
            # Drain logs
            while not log_queue.empty():
                msg = log_queue.get_nowait()
                await sio.emit('log', {'msg': msg})
                
            # Compile Fleet State
            fleet_state = {}
            for am_id, amb in engine.ambulances.items():
                if amb.current_state:
                    fleet_state[am_id] = amb.current_state
                    
            state_payload = {
                "ambulances": fleet_state,
                "emergencies": engine.active_emergencies,
                "pois": POIS,
                "jams": JAMS,
                "is_simulating": engine.is_simulating,
                "speed_multiplier": engine.speed_multiplier
            }
            await sio.emit('sim_state', state_payload)
        except Exception as e:
            print(f"Broadcaster Error: {e}")
        await asyncio.sleep(0.1)  # 10 Hz refresh rate

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-cache graph asynchronously to avoid blocking first UI render
    def preload_graph():
        from telemetry.logistics import get_city_graph
        try:
            get_city_graph()
        except Exception as e:
            engine.log_network(f"[SISTEMA] Aviso: {e}")
            
    asyncio.get_running_loop().run_in_executor(None, preload_graph)
    
    # Startup
    task = asyncio.create_task(state_broadcaster())
    engine.log_network("[SERVER] Simulador asíncrono e inicializado. Cargando mapas en background...")
    yield
    # Shutdown
    task.cancel()
    engine.stop()

app = FastAPI(lifespan=lifespan)
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. REST Endpoints
class SpawnRequest(BaseModel):
    type: str # 'AMBULANCE', 'EMERGENCY', 'HOSPITAL', 'GAS_STATION', 'JAM'
    lat: float
    lon: float

@app.post("/api/spawn")
async def api_spawn(req: SpawnRequest):
    if req.type == "AMBULANCE":
        engine.spawn_ambulance(req.lat, req.lon)
    elif req.type == "EMERGENCY":
        engine.spawn_emergency(req.lat, req.lon)
    elif req.type == "HOSPITAL" or req.type == "GAS_STATION":
        add_poi(req.type, req.lat, req.lon)
        engine.log_network(f"[SISTEMA] Nuevo POI ({req.type}) construido.")
    elif req.type == "JAM":
        add_jam(req.lat, req.lon, 0.005)
        engine.log_network("[SISTEMA] Atasco topográfico registrado.")
    return {"status": "ok"}

class DeleteRequest(BaseModel):
    lat: float
    lon: float

@app.post("/api/delete")
async def api_delete(req: DeleteRequest):
    lat, lon = req.lat, req.lon
    # Ambulance
    for am_id, amb in list(engine.ambulances.items()):
        if abs(amb.logistics.lat - lat) < 0.005 and abs(amb.logistics.lon - lon) < 0.005:
            amb.stop()
            if amb.p2p_mesh: amb.p2p_mesh.stop()
            del engine.ambulances[am_id]
            engine.log_network(f"[SISTEMA] 💥 Unidad {am_id} desmantelada.")
            return {"status": "deleted_ambulance"}
            
    # POI
    for poi in list(POIS):
        if abs(poi["lat"] - lat) < 0.005 and abs(poi["lon"] - lon) < 0.005:
            POIS.remove(poi)
            engine.log_network(f"[SISTEMA] 💥 POI ({poi['type']}) destruido.")
            return {"status": "deleted_poi"}
            
    # Jam
    for jam in list(JAMS):
        if abs(jam["lat"] - lat) < 0.005 and abs(jam["lon"] - lon) < 0.005:
            JAMS.remove(jam)
            engine.log_network(f"[SISTEMA] 💥 Atasco eliminado.")
            return {"status": "deleted_jam"}
            
    return {"status": "not_found"}

@app.post("/api/control/toggle")
async def api_toggle_playback():
    engine.toggle_playback()
    return {"is_simulating": engine.is_simulating}

@app.get("/api/route/{amb_id}")
async def api_get_route(amb_id: str):
    if amb_id in engine.ambulances:
        geom = engine.ambulances[amb_id].logistics.route_geometry
        step = engine.ambulances[amb_id].logistics.route_step
        return {"route": geom, "step": step}
    return {"route": [], "step": 0}

@app.post("/api/control/clear")
async def api_clear():
    engine.clear_all_scenario()
    return {"status": "cleared"}

class SpeedRequest(BaseModel):
    multiplier: int

@app.post("/api/control/speed")
async def api_speed(req: SpeedRequest):
    engine.update_speed_multiplier(req.multiplier)
    return {"multiplier": req.multiplier}

class NetworkRequest(BaseModel):
    mqtt: bool
    p2p: bool
    http: bool

@app.post("/api/network")
async def api_network(req: NetworkRequest):
    engine.toggle_networks(req.mqtt, req.p2p, req.http)
    return {"status": "network_updated"}

# 5. Serve the Dashboard Frontend
import os
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("app:socket_app", host="0.0.0.0", port=5000, reload=False)
