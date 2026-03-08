import random
import math
import osmnx as ox
import networkx as nx
import threading
import time
import logging
import requests
from typing import Dict, List, Tuple, Optional, Any, Literal
from dataclasses import dataclass
from enum import Enum

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Shared Global State for dynamic map elements
POIS: List[Dict[str, Any]] = []

GRAPH_LOCK = threading.Lock()

# Jams are geofenced circles: {"lat": ..., "lon": ..., "radius": 0.005}
JAMS: List[Dict[str, Any]] = []

# Distancia máxima de ruta permitida (rutas más largas son rechazadas)
MAX_ROUTE_DISTANCE_KM = 150.0

# Enum para tipos de misión
class MissionStatus(Enum):
    ACTIVE = "ACTIVE"
    IN_USE = "IN_USE"
    INACTIVE = "INACTIVE"
    REFUELING = "REFUELING"
    MAINTENANCE = "MAINTENANCE"
    EMERGENCY = "EMERGENCY"
    STRANDED = "STRANDED"   # Varada por agotamiento de combustible

class RoadType(Enum):
    URBAN = "urban"
    HIGHWAY = "highway"
    RURAL = "rural"
    RESIDENTIAL = "residential"

class TrafficStatus(Enum):
    CLEAR = "clear"
    MODERATE = "moderate"
    HEAVY = "heavy"
    STANDSTILL = "standstill"
    ACCIDENT = "accident"

@dataclass
class POI:
    """Punto de interés en el mapa."""
    type: str  # HOSPITAL, GAS_STATION, etc.
    lat: float
    lon: float
    name: str = ""
    capacity: int = 1
    
@dataclass
class TrafficJam:
    """Zona de atasco de tráfico."""
    lat: float
    lon: float
    radius: float = 0.005
    severity: float = 0.8  # 0.0 a 1.0
    cause: str = "congestion"

def add_poi(poi_type: str, lat: float, lon: float, name: str = "") -> None:
    """Añade un punto de interés al mapa."""
    POIS.append({"type": poi_type, "lat": lat, "lon": lon, "name": name})
    logger.info(f"POI añadido: {poi_type} en ({lat:.6f}, {lon:.6f})")

def add_jam(lat: float, lon: float, radius: float = 0.005, 
            severity: float = 0.8, cause: str = "congestion") -> None:
    """Añade una zona de atasco al mapa."""
    JAMS.append({
        "lat": lat, 
        "lon": lon, 
        "radius": radius,
        "severity": severity,
        "cause": cause
    })
    logger.info(f"Atasco añadido: {cause} en ({lat:.6f}, {lon:.6f}) con severidad {severity}")

def remove_jam(lat: float, lon: float, threshold: float = 0.001) -> bool:
    """Elimina un atasco cercano a las coordenadas especificadas."""
    global JAMS
    for i, jam in enumerate(JAMS):
        d = math.sqrt((jam["lat"] - lat)**2 + (jam["lon"] - lon)**2)
        if d <= threshold:
            removed = JAMS.pop(i)
            logger.info(f"Atasco eliminado en ({lat:.6f}, {lon:.6f})")
            return True
    return False

ROUTE_CACHE: Dict[str, List[Tuple[float, float]]] = {}

# --------------------------------------------------------------------------
# OSRM routing (Docker local, puerto 5001)
# Motor primario. Si no está disponible, se usa la API pública de OSRM.
# --------------------------------------------------------------------------
OSRM_BASE_URL = "http://localhost:5001"
OSRM_PUBLIC_URL = "http://router.project-osrm.org"
_OSRM_AVAILABLE: Optional[bool] = None   # None = no comprobado aún
_OSRM_LAST_CHECK: float = 0.0
_OSRM_CHECK_INTERVAL: float = 30.0       # Recomprobar disponibilidad cada 30 s
_OSRM_LOCK = threading.Lock()
_OSRM_PUBLIC_LAST_CALL: float = 0.0      # Para rate-limiting de la API pública
_OSRM_PUBLIC_LOCK = threading.Lock()     # Lock para acceso a _OSRM_PUBLIC_LAST_CALL


def _is_osrm_available() -> bool:
    """Comprueba si el servidor OSRM local está activo. Cachea el resultado."""
    global _OSRM_AVAILABLE, _OSRM_LAST_CHECK
    now = time.time()
    with _OSRM_LOCK:
        if _OSRM_AVAILABLE is not None and (now - _OSRM_LAST_CHECK) < _OSRM_CHECK_INTERVAL:
            return _OSRM_AVAILABLE
        try:
            r = requests.get(
                f"{OSRM_BASE_URL}/route/v1/driving/0,0;0,0",
                timeout=2.0,
                params={"overview": "false"},
            )
            # 200 = OK, 400 = parámetros inválidos pero servidor activo
            _OSRM_AVAILABLE = r.status_code in (200, 400)
        except Exception:
            _OSRM_AVAILABLE = False
        _OSRM_LAST_CHECK = now
        if _OSRM_AVAILABLE:
            logger.info("[OSRM] Servidor disponible en %s", OSRM_BASE_URL)
        else:
            logger.warning(
                "[OSRM] Servidor local no disponible en %s — se usará la API pública OSRM.",
                OSRM_BASE_URL,
            )
        return _OSRM_AVAILABLE


def _route_via_osrm(
    orig_lat: float, orig_lon: float,
    dest_lat: float, dest_lon: float,
) -> Optional[List[Tuple[float, float]]]:
    """
    Consulta el servidor OSRM local para obtener la geometría de una ruta.

    Returns:
        Lista de (lat, lon) o None si la consulta falla o no hay ruta.
    """
    try:
        url = (
            f"{OSRM_BASE_URL}/route/v1/driving/"
            f"{orig_lon},{orig_lat};{dest_lon},{dest_lat}"
        )
        r = requests.get(
            url,
            timeout=5.0,
            params={"overview": "full", "geometries": "geojson"},
        )
        if r.status_code != 200:
            logger.warning("[OSRM] HTTP %s al calcular ruta", r.status_code)
            return None
        data = r.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            logger.warning("[OSRM] Respuesta inesperada: %s", data.get("code"))
            return None
        # OSRM devuelve coordenadas como [lon, lat]; convertir a (lat, lon)
        coords_raw = data["routes"][0]["geometry"]["coordinates"]
        return [(c[1], c[0]) for c in coords_raw]
    except Exception as exc:
        logger.error("[OSRM] Error en consulta: %s", exc)
        return None


def _route_via_osrm_public(
    orig_lat: float, orig_lon: float,
    dest_lat: float, dest_lon: float,
) -> Optional[List[Tuple[float, float]]]:
    """
    Consulta la API pública de OSRM (router.project-osrm.org) para obtener la
    geometría de una ruta. Aplica un rate-limit mínimo de 0.5 s entre llamadas.

    Returns:
        Lista de (lat, lon) o None si la consulta falla o no hay ruta.
    """
    global _OSRM_PUBLIC_LAST_CALL
    try:
        with _OSRM_PUBLIC_LOCK:
            elapsed = time.time() - _OSRM_PUBLIC_LAST_CALL
            if elapsed < 0.5:
                time.sleep(0.5 - elapsed)
            _OSRM_PUBLIC_LAST_CALL = time.time()

        url = (
            f"{OSRM_PUBLIC_URL}/route/v1/driving/"
            f"{orig_lon},{orig_lat};{dest_lon},{dest_lat}"
        )
        r = requests.get(
            url,
            timeout=8.0,
            params={"overview": "full", "geometries": "geojson"},
        )
        if r.status_code != 200:
            logger.warning("[OSRM-PUBLIC] HTTP %s al calcular ruta", r.status_code)
            return None
        data = r.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            logger.warning("[OSRM-PUBLIC] Respuesta inesperada: %s", data.get("code"))
            return None
        coords_raw = data["routes"][0]["geometry"]["coordinates"]
        return [(c[1], c[0]) for c in coords_raw]
    except Exception as exc:
        logger.error("[OSRM-PUBLIC] Error en consulta: %s", exc)
        return None


# --------------------------------------------------------------------------
# Multi-city graph registry
# --------------------------------------------------------------------------
CITY_GRAPHS: Dict[str, Any] = {}                     # cache_key → networkx graph
CITY_GRAPH_BOUNDS: Dict[str, Tuple[float, float, float, float]] = {}  # key → (min_lat, min_lon, max_lat, max_lon)
_DL_IN_PROGRESS: set = set()                         # keys currently being downloaded

# Keep backward-compat alias (used by app.py preload)
CITY_GRAPH = None


def _register_graph(key: str, G) -> None:
    """Registra un grafo en el registro global y precomputa su bounding box."""
    global CITY_GRAPHS, CITY_GRAPH_BOUNDS
    lats = [d['y'] for _, d in G.nodes(data=True)]
    lons = [d['x'] for _, d in G.nodes(data=True)]
    if not lats:
        return
    pad = 0.02  # ~2 km padding
    with GRAPH_LOCK:
        CITY_GRAPHS[key] = G
        CITY_GRAPH_BOUNDS[key] = (
            min(lats) - pad, min(lons) - pad,
            max(lats) + pad, max(lons) + pad,
        )
    logger.info(f"[GRAPH] Grafo '{key}' registrado con {G.number_of_nodes()} nodos.")


def get_graph_covering(orig_lat: float, orig_lon: float,
                       dest_lat: float, dest_lon: float):
    """
    Devuelve el primer grafo registrado cuyo bounding box contenga AMBOS puntos.
    Devuelve None si ninguno cubre ambos extremos.
    """
    for key, (min_lat, min_lon, max_lat, max_lon) in CITY_GRAPH_BOUNDS.items():
        orig_in = (min_lat <= orig_lat <= max_lat) and (min_lon <= orig_lon <= max_lon)
        dest_in = (min_lat <= dest_lat <= max_lat) and (min_lon <= dest_lon <= max_lon)
        if orig_in and dest_in:
            return CITY_GRAPHS.get(key)
    return None


def ensure_graph_for_area(center_lat: float, center_lon: float,
                           radius_m: int, cache_key: str) -> None:
    """
    Asegura que existe un grafo viario para el área indicada.
    Si no está en memoria, lo carga desde disco (cache/) o lo descarga con OSMnx
    en un hilo daemon para no bloquear el servidor.

    Args:
        center_lat:  Latitud del centro del área
        center_lon:  Longitud del centro del área
        radius_m:    Radio en metros a cubrir
        cache_key:   Clave única de identificación del grafo (nombre de preset)
    """
    import os

    with GRAPH_LOCK:
        if cache_key in CITY_GRAPHS:
            return
        if cache_key in _DL_IN_PROGRESS:
            return
        _DL_IN_PROGRESS.add(cache_key)

    def _download():
        global CITY_GRAPH
        try:
            os.makedirs("cache", exist_ok=True)
            # Compatibilidad hacia atrás: Madrid puede estar en la raíz del proyecto
            legacy_path = "madrid_sim_graph.graphml"
            cache_path = os.path.join("cache", f"graph_{cache_key}.graphml")

            G = None
            if cache_key == "madrid" and os.path.exists(legacy_path):
                logger.info(f"[GRAPH] Cargando grafo '{cache_key}' desde {legacy_path}...")
                G = ox.load_graphml(legacy_path)
            elif os.path.exists(cache_path):
                logger.info(f"[GRAPH] Cargando grafo '{cache_key}' desde caché local...")
                G = ox.load_graphml(cache_path)
            else:
                logger.info(
                    f"[GRAPH] Descargando red viaria para '{cache_key}' "
                    f"({center_lat:.4f},{center_lon:.4f}) r={radius_m}m ..."
                )
                raw = ox.graph_from_point(
                    (center_lat, center_lon), dist=radius_m, network_type='drive'
                )
                scc = max(nx.strongly_connected_components(raw), key=len)
                G = raw.subgraph(scc).copy()
                ox.save_graphml(G, cache_path)
                logger.info(f"[GRAPH] Grafo '{cache_key}' guardado en {cache_path}.")

            _register_graph(cache_key, G)
            # Actualizar alias backward-compat para Madrid
            if cache_key == "madrid":
                CITY_GRAPH = G
        except Exception as exc:
            logger.error(f"[GRAPH] Error descargando grafo '{cache_key}': {exc}")
        finally:
            _DL_IN_PROGRESS.discard(cache_key)

    t = threading.Thread(target=_download, daemon=True, name=f"GraphDL-{cache_key}")
    t.start()


def get_city_graph():
    """
    Backward-compatible: devuelve el grafo de Madrid (lo descarga si es necesario).
    Bloquea hasta que el grafo esté disponible (máx. 60 s).
    """
    ensure_graph_for_area(40.4168, -3.7038, 8000, "madrid")
    # Esperar hasta que esté disponible (para el preload inicial)
    for _ in range(600):
        if "madrid" in CITY_GRAPHS:
            return CITY_GRAPHS["madrid"]
        time.sleep(0.1)
    return CITY_GRAPHS.get("madrid")

class LogisticsEngine:
    """
    Motor logístico que gestiona navegación, rutas y tráfico para una ambulancia.
    """
    
    def __init__(self, start_lat: float = 40.4168, start_lon: float = -3.7038):
        """
        Inicializa el motor logístico.
        
        Args:
            start_lat: Latitud inicial
            start_lon: Longitud inicial
        """
        self.lat = start_lat
        self.lon = start_lon
        self.speed = 0.0  # km/h
        self.heading = random.uniform(0, 360)  # grados
        self.acceleration = 0.0  # m/s²
        self.destination: Optional[Tuple[float, float]] = None
        self.destination_type: Optional[str] = None
        self.road_type = RoadType.URBAN.value
        self.last_distance_km = 0.0
        self.mission_status = MissionStatus.ACTIVE.value
        self.route_geometry: List[Tuple[float, float]] = []
        self.route_step = 0
        self.action_message = "Esperando asignación..."
        
        # Métricas adicionales
        self.total_distance_km = 0.0
        self.average_speed_kmh = 0.0
        self.trip_start_time = time.time()
        self.last_position_update = time.time()
        self.route_efficiency = 1.0  # Eficiencia de ruta (0.0 a 1.0)
        self.fuel_efficiency = 0.15  # L/km (consumo base)
        
        # Historial de posiciones (últimas 100 posiciones)
        self.position_history: List[Tuple[float, float, float]] = []  # (lat, lon, timestamp)
        
        # Estado de tráfico local
        self.local_traffic_status = TrafficStatus.CLEAR.value
        self.traffic_congestion_level = 0.0  # 0.0 a 1.0
        self.last_traffic_update = 0.0
        
        # Contadores de rendimiento
        self.routes_calculated = 0
        self.route_calculation_errors = 0

    def set_destination(self, lat: float, lon: float, dest_type: str = "HOSPITAL") -> bool:
        """
        Establece un destino y calcula la ruta óptima.
        
        Args:
            lat: Latitud destino
            lon: Longitud destino
            dest_type: Tipo de destino
            
        Returns:
            True si la ruta se calculó correctamente
        """
        # Protección: rechazar rutas que excedan el límite operativo (vuelos intercontinentales)
        dist_check = self._calculate_distance(self.lat, self.lon, lat, lon)
        if dist_check > MAX_ROUTE_DISTANCE_KM:
            logger.warning(
                f"[LOGÍSTICA] Destino rechazado para {dest_type}: "
                f"distancia {dist_check:.1f} km supera el límite de {MAX_ROUTE_DISTANCE_KM} km."
            )
            return False

        self.destination = (lat, lon)
        self.destination_type = dest_type
        self.route_geometry = []
        self.route_step = 0
        self.trip_start_time = time.time()
        
        # Construir clave de caché
        cache_key = f"{round(self.lon, 6)},{round(self.lat, 6)}_{round(lon, 6)},{round(lat, 6)}"
        
        # Verificar caché
        if cache_key in ROUTE_CACHE:
            self.route_geometry = ROUTE_CACHE[cache_key].copy()
            logger.info(f"Ruta cargada desde caché para {dest_type}")
            self.routes_calculated += 1
            return True

        # ── Motor primario: OSRM (Docker local, puerto 5001) ─────────────────
        if _is_osrm_available():
            osrm_coords = _route_via_osrm(self.lat, self.lon, lat, lon)
            if osrm_coords:
                direct_distance = self._calculate_distance(self.lat, self.lon, lat, lon)
                osrm_km = sum(
                    self._calculate_distance(
                        osrm_coords[i][0], osrm_coords[i][1],
                        osrm_coords[i + 1][0], osrm_coords[i + 1][1],
                    )
                    for i in range(len(osrm_coords) - 1)
                ) if len(osrm_coords) > 1 else direct_distance
                if direct_distance > 0 and osrm_km > 0:
                    self.route_efficiency = min(1.0, max(0.1, direct_distance / osrm_km))
                self.route_geometry = osrm_coords
                ROUTE_CACHE[cache_key] = self.route_geometry.copy()
                logger.info(
                    "[OSRM] Ruta a %s: %d puntos, eficiencia %.2f",
                    dest_type, len(osrm_coords), self.route_efficiency,
                )
                self.routes_calculated += 1
                return True
            # OSRM activo pero sin ruta para este par orig→dest
            logger.warning(
                "[OSRM] Sin ruta (%s,%s)→(%s,%s) — fallback a API pública OSRM",
                self.lat, self.lon, lat, lon,
            )

        # ── Fallback: API pública OSRM ────────────────────────────────────────
        public_coords = _route_via_osrm_public(self.lat, self.lon, lat, lon)
        if public_coords:
            direct_distance = self._calculate_distance(self.lat, self.lon, lat, lon)
            public_km = sum(
                self._calculate_distance(
                    public_coords[i][0], public_coords[i][1],
                    public_coords[i + 1][0], public_coords[i + 1][1],
                )
                for i in range(len(public_coords) - 1)
            ) if len(public_coords) > 1 else direct_distance
            if direct_distance > 0 and public_km > 0:
                self.route_efficiency = min(1.0, max(0.1, direct_distance / public_km))
            self.route_geometry = public_coords
            ROUTE_CACHE[cache_key] = self.route_geometry.copy()
            logger.info(
                "[OSRM-PUBLIC] Ruta a %s: %d puntos, eficiencia %.2f",
                dest_type, len(public_coords), self.route_efficiency,
            )
            self.routes_calculated += 1
            return True

        # ── Sin ruta disponible: línea recta + aviso ──────────────────────────
        logger.warning(
            "[ROUTING] ⚠️ Sin conexión con OSRM (local ni público) — "
            "usando ruta directa a %s. Comprueba el estado del servidor.",
            dest_type,
        )
        self.route_geometry = [(lat, lon)]
        self.routes_calculated += 1
        return True

    def route_to_nearest(self, dest_type: str) -> bool:
        """
        Encuentra y establece ruta al POI más cercano del tipo especificado.
        
        Args:
            dest_type: Tipo de POI a buscar
            
        Returns:
            True si se encontró y estableció un destino
        """
        best, min_d = None, float('inf')
        for p in POIS:
            if p["type"] == dest_type:
                d = self._calculate_distance(self.lat, self.lon, p["lat"], p["lon"])
                if d < min_d:
                    min_d, best = d, p
        
        if best:
            success = self.set_destination(best["lat"], best["lon"], dest_type)
            if success:
                logger.info(f"Ruta establecida al {dest_type} más cercano ({min_d:.2f} km)")
            return success
        return False

    def route_to_alternative(self, dest_type: str) -> bool:
        """
        Encuentra un destino alternativo del mismo tipo si la ruta actual tiene problemas.
        
        Args:
            dest_type: Tipo de destino
            
        Returns:
            True si se encontró un destino alternativo
        """
        # Excluir el destino actual si existe
        current_dest = self.destination
        current_coords = (round(self.destination[0], 4), round(self.destination[1], 4)) if self.destination else None
        
        best, min_d = None, float('inf')
        for p in POIS:
            if p["type"] == dest_type:
                # Excluir destino actual
                if current_dest and abs(p["lat"] - current_dest[0]) < 0.0001:
                    continue
                    
                d = self._calculate_distance(self.lat, self.lon, p["lat"], p["lon"])
                if d < min_d:
                    min_d, best = d, p
        
        if best:
            return self.set_destination(best["lat"], best["lon"], dest_type)
        return False

    def step(self, dt: float = 1.0, speed_multiplier: float = 1.0) -> Dict[str, Any]:
        """
        Avanza la simulación logística un paso de tiempo.
        
        Args:
            dt: Paso de tiempo en segundos
            speed_multiplier: Multiplicador de velocidad de simulación
            
        Returns:
            Estado actual del motor logístico
        """
        adjusted_dt = dt * speed_multiplier
        
        # Actualizar historial de posiciones
        self._update_position_history()
        
        # Detección de atascos y análisis de tráfico
        self._analyze_traffic_conditions(adjusted_dt)
        
        # Velocidad objetivo basada en condiciones
        target_speed = self._calculate_target_speed()
        
        # Seguir ruta si existe
        if self.destination and self.route_geometry:
            self._follow_route(adjusted_dt, target_speed)
        elif self.destination:
            # Destino asignado pero sin geometría de ruta
            self._handle_missing_route(adjusted_dt)
        else:
            # Sin destino, movimiento aleatorio o estacionado
            self._handle_no_destination(adjusted_dt)
        
        # Actualizar métricas
        self._update_metrics(adjusted_dt)
        
        return self.get_state()

    def _calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calcula distancia en km entre dos puntos."""
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return 6371 * c  # Radio terrestre en km

    def _update_position_history(self) -> None:
        """Actualiza el historial de posiciones."""
        current_time = time.time()
        self.position_history.append((self.lat, self.lon, current_time))
        
        # Mantener solo las últimas 100 posiciones
        if len(self.position_history) > 100:
            self.position_history.pop(0)

    def _analyze_traffic_conditions(self, dt: float) -> None:
        """Analiza condiciones de tráfico locales."""
        current_time = time.time()
        
        # Actualizar solo cada 2 segundos para eficiencia
        if current_time - self.last_traffic_update < 2.0:
            return
            
        # Detección de atascos geofence
        in_jam = False
        max_severity = 0.0
        jam_cause = "clear"
        
        for jam in JAMS:
            d = math.sqrt((jam["lat"] - self.lat)**2 + (jam["lon"] - self.lon)**2)
            if d <= jam["radius"]:
                in_jam = True
                if jam.get("severity", 0.8) > max_severity:
                    max_severity = jam["severity"]
                    jam_cause = jam.get("cause", "congestion")
        
        # Determinar estado de tráfico basado en múltiples factores
        if in_jam:
            if max_severity > 0.9:
                self.local_traffic_status = TrafficStatus.STANDSTILL.value
                self.traffic_congestion_level = 1.0
            elif max_severity > 0.7:
                self.local_traffic_status = TrafficStatus.HEAVY.value
                self.traffic_congestion_level = max_severity
            else:
                self.local_traffic_status = TrafficStatus.MODERATE.value
                self.traffic_congestion_level = max_severity
                
            self.action_message = f"Atasco: {jam_cause} ({max_severity:.0%})"
        elif self.speed > 0:
            # Basado en velocidad actual y densidad de tráfico
            if self.speed < 20:
                self.local_traffic_status = TrafficStatus.HEAVY.value
                self.traffic_congestion_level = 0.7
            elif self.speed < 50:
                self.local_traffic_status = TrafficStatus.MODERATE.value
                self.traffic_congestion_level = 0.4
            else:
                self.local_traffic_status = TrafficStatus.CLEAR.value
                self.traffic_congestion_level = 0.1
        else:
            self.local_traffic_status = TrafficStatus.CLEAR.value
            self.traffic_congestion_level = 0.0
            
        self.last_traffic_update = current_time

    def _calculate_target_speed(self) -> float:
        """Calcula velocidad objetivo basada en condiciones."""
        base_speed = 80.0  # km/h en condiciones ideales
        
        # Reducción por tráfico
        traffic_factor = 1.0 - self.traffic_congestion_level
        
        # Reducción por tipo de vía
        road_factor = 1.0
        if self.road_type == RoadType.URBAN.value:
            road_factor = 0.7
        elif self.road_type == RoadType.RESIDENTIAL.value:
            road_factor = 0.5
        elif self.road_type == RoadType.HIGHWAY.value:
            road_factor = 1.2
        
        # Reducción por misión de emergencia
        emergency_factor = 1.2 if self.mission_status == MissionStatus.EMERGENCY.value else 1.0
        
        target_speed = base_speed * traffic_factor * road_factor * emergency_factor
        
        # Límites según estado de tráfico
        if self.local_traffic_status == TrafficStatus.STANDSTILL.value:
            target_speed = 5.0
        elif self.local_traffic_status == TrafficStatus.HEAVY.value:
            target_speed = min(target_speed, 30.0)
        elif self.local_traffic_status == TrafficStatus.MODERATE.value:
            target_speed = min(target_speed, 60.0)
            
        return max(5.0, target_speed)  # Mínimo 5 km/h

    def _follow_route(self, dt: float, target_speed: float) -> None:
        """Sigue la ruta calculada."""
        # Aceleración/desaceleración suave
        if self.speed < target_speed:
            self.acceleration = 2.0  # m/s²
            self.speed = min(target_speed, self.speed + (self.acceleration * dt * 3.6))
        elif self.speed > target_speed:
            self.acceleration = -3.0  # m/s² (frenado)
            self.speed = max(target_speed, self.speed + (self.acceleration * dt * 3.6))
        else:
            self.acceleration = 0.0
        
        # Distancia a mover en este paso
        distance_to_move_km = (self.speed / 3600.0) * dt
        self.last_distance_km = distance_to_move_km
        
        # Mover a lo largo de la ruta
        while distance_to_move_km > 0 and self.route_step < len(self.route_geometry):
            target_lat, target_lon = self.route_geometry[self.route_step]
            d_lat = target_lat - self.lat
            d_lon = target_lon - self.lon
            
            # Corrección por curvatura terrestre
            d_deg = math.sqrt(d_lat**2 + (d_lon * math.cos(math.radians(self.lat)))**2)
            d_km = d_deg * 111.0  # Aproximación: 1 grado ≈ 111 km
            
            if d_km <= distance_to_move_km:
                # Llegamos al siguiente punto de la ruta
                distance_to_move_km -= d_km
                self.lat, self.lon = target_lat, target_lon
                self.route_step += 1
                
                # Actualizar heading
                if d_deg > 0:
                    self.heading = math.degrees(math.atan2(d_lon, d_lat))
            else:
                # Movimiento parcial hacia el siguiente punto
                fraction = distance_to_move_km / d_km
                self.lat += d_lat * fraction
                self.lon += d_lon * fraction
                
                # Actualizar heading
                if d_deg > 0:
                    self.heading = math.degrees(math.atan2(d_lon, d_lat))
                
                distance_to_move_km = 0
        
        # Verificar si llegamos al destino
        if self.route_step >= len(self.route_geometry):
            self._arrive_at_destination()

    def _arrive_at_destination(self) -> None:
        """Maneja la llegada al destino."""
        self.speed = 0.0
        self.acceleration = 0.0
        
        # Calcular tiempo de viaje
        trip_time = time.time() - self.trip_start_time
        trip_time_min = trip_time / 60.0
        
        # Mensaje según tipo de destino
        if self.destination_type == "HOSPITAL":
            self.action_message = "🏥 Llegada al Hospital - Paciente entregado"
        elif self.destination_type == "GAS_STATION":
            self.action_message = "⛽ En gasolinera - Listo para repostar"
        elif self.destination_type == "EMERGENCY":
            self.action_message = "🚨 En escena de emergencia"
        else:
            self.action_message = f"✓ Destino alcanzado ({self.destination_type})"
        
        logger.info(f"Llegada a destino {self.destination_type}. "
                   f"Tiempo de viaje: {trip_time_min:.1f} min, "
                   f"Distancia: {self.total_distance_km:.2f} km")
        
        # Resetear destino
        self.destination = None
        self.destination_type = None
        self.route_geometry = []
        self.route_step = 0

    def _handle_missing_route(self, dt: float) -> None:
        """Maneja situación con destino pero sin ruta calculada."""
        self.acceleration = 0.0
        self.speed = max(0, self.speed - (5.0 * dt * 3.6))  # Frenado suave
        
        # Reintentar cálculo de ruta periódicamente
        if not hasattr(self, '_route_retry_timer'):
            self._route_retry_timer = 0.0
        self._route_retry_timer += dt
        
        if self._route_retry_timer > 3.0:  # Reintentar cada 3 segundos
            self._route_retry_timer = 0.0
            if self.destination:
                self.action_message = "Recalculando ruta..."
                self.set_destination(self.destination[0], self.destination[1], self.destination_type or "UNKNOWN")

    def _handle_no_destination(self, dt: float) -> None:
        """Maneja movimiento sin destino específico."""
        self.acceleration = 0.0
        
        if self.speed > 0:
            # Frenado gradual
            self.speed = max(0, self.speed - (2.0 * dt * 3.6))
            self.last_distance_km = (self.speed / 3600.0) * dt
            
            # Movimiento en dirección actual
            self.lat += (self.last_distance_km * math.cos(math.radians(self.heading))) / 111.0
            self.lon += (self.last_distance_km * math.sin(math.radians(self.heading))) / (111.0 * math.cos(math.radians(self.lat)))
            
            if self.speed <= 0:
                self.action_message = "Estacionada - Esperando órdenes"
        else:
            self.action_message = "Estacionada - Esperando órdenes"
            self.last_distance_km = 0.0

    def _update_metrics(self, dt: float) -> None:
        """Actualiza métricas de rendimiento."""
        # Actualizar distancia total
        self.total_distance_km += self.last_distance_km
        
        # Actualizar velocidad promedio (media móvil)
        if dt > 0:
            instant_speed = self.last_distance_km / (dt / 3600)  # km/h
            alpha = 0.1  # Factor de suavizado
            self.average_speed_kmh = (alpha * instant_speed) + ((1 - alpha) * self.average_speed_kmh)

    def get_state(self) -> Dict[str, Any]:
        """
        Retorna el estado actual del motor logístico.
        
        Returns:
            Diccionario con todas las métricas logísticas
        """
        # Determinar estado de tráfico para display
        display_traffic_status = self.local_traffic_status
        
        return {
            "latitude": round(self.lat, 6),
            "longitude": round(self.lon, 6),
            "speed": round(self.speed, 2),
            "heading": round(self.heading, 2),
            "acceleration": round(self.acceleration, 2),
            "has_destination": self.destination is not None,
            "destination_lat": round(self.destination[0], 6) if self.destination else None,
            "destination_lon": round(self.destination[1], 6) if self.destination else None,
            "destination_type": self.destination_type,
            "route_step": self.route_step,
            "route_total_steps": len(self.route_geometry),
            "traffic_status": display_traffic_status,
            "traffic_congestion_level": round(self.traffic_congestion_level, 2),
            "road_type": self.road_type,
            "mission_status": self.mission_status,
            "action_message": self.action_message,
            "total_distance_km": round(self.total_distance_km, 2),
            "average_speed_kmh": round(self.average_speed_kmh, 1),
            "route_efficiency": round(self.route_efficiency, 2),
            "routes_calculated": self.routes_calculated,
            "route_errors": self.route_calculation_errors,
            "position_history_count": len(self.position_history)
        }

    def inject_interference(self, interference_type: str) -> None:
        """
        Inyecta una interferencia en el sistema logístico.
        
        Args:
            interference_type: Tipo de interferencia a inyectar
        """
        if interference_type == "traffic_jam":
            # Crear atasco en la posición actual
            add_jam(self.lat, self.lon, radius=0.005, severity=0.9, cause="simulated_accident")
            logger.info(f"Atasco simulado inyectado en ({self.lat:.6f}, {self.lon:.6f})")
        elif interference_type == "gps_failure":
            # Simular fallo de GPS
            self.route_geometry = []
            self.action_message = "⚠️ FALLO GPS - Navegación offline"
            logger.info("Fallo GPS simulado inyectado")
        elif interference_type == "route_blocked":
            # Bloquear ruta actual
            if self.route_geometry and self.route_step < len(self.route_geometry):
                # Añadir atasco en el siguiente punto de la ruta
                next_point = self.route_geometry[min(self.route_step, len(self.route_geometry)-1)]
                add_jam(next_point[0], next_point[1], radius=0.003, severity=1.0, cause="road_blocked")
                self.action_message = "🚧 Ruta bloqueada - Buscando alternativa"
                logger.info("Ruta bloqueada simulada")
        elif interference_type == "detour":
            # Forzar desvío
            if self.destination_type and self.destination:
                self.route_to_alternative(self.destination_type)
                self.action_message = "🔄 Desvío forzado - Ruta alternativa"
                logger.info("Desvío forzado inyectado")

    def get_position_history(self, max_points: int = 50) -> List[Dict[str, Any]]:
        """
        Retorna historial de posiciones para visualización.
        
        Args:
            max_points: Máximo número de puntos a retornar
            
        Returns:
            Lista de posiciones con timestamps
        """
        history = []
        step = max(1, len(self.position_history) // max_points)
        
        for i in range(0, len(self.position_history), step):
            lat, lon, timestamp = self.position_history[i]
            history.append({
                "lat": lat,
                "lon": lon,
                "timestamp": timestamp,
                "age": time.time() - timestamp
            })
            if len(history) >= max_points:
                break
                
        return history

    def estimate_arrival_time(self) -> Optional[float]:
        """
        Estima tiempo de llegada al destino en minutos.
        
        Returns:
            Tiempo estimado en minutos, o None si no hay destino
        """
        if not self.destination or not self.route_geometry:
            return None
            
        # Calcular distancia restante
        remaining_steps = len(self.route_geometry) - self.route_step
        if remaining_steps <= 0:
            return 0.0
            
        # Estimación simple: asumir velocidad actual
        if self.speed > 0:
            # Distancia aproximada por punto restante
            distance_per_step = 0.1  # km por paso (estimación)
            remaining_km = remaining_steps * distance_per_step
            eta_hours = remaining_km / self.speed
            return eta_hours * 60  # Convertir a minutos
        
        return None