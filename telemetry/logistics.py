import random
import math
import osmnx as ox
import networkx as nx
import threading
import time
import logging
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
CITY_GRAPH = None

def get_city_graph():
    """
    Obtiene el grafo de la ciudad, cargándolo desde disco o descargándolo si es necesario.
    
    Returns:
        networkx.MultiDiGraph: Grafo de calles de la ciudad
    """
    global CITY_GRAPH
    if CITY_GRAPH is None:
        with GRAPH_LOCK:
            if CITY_GRAPH is None:
                import os
                graph_path = "madrid_sim_graph.graphml"
                if os.path.exists(graph_path):
                    logger.info("Cargando red viaria local desde disco...")
                    CITY_GRAPH = ox.load_graphml(graph_path)
                    logger.info("Grafo físico cargado exitosamente.")
                else:
                    logger.info("Descargando red viaria de Madrid (Puede tardar la primera vez)...")
                    # 5km covers the inner tactical city rapidly.
                    raw_graph = ox.graph_from_point((40.4168, -3.7038), dist=5000, network_type='drive')
                    # Guarantee purely contiguous network mathematically
                    largest_scc = max(nx.strongly_connected_components(raw_graph), key=len)
                    CITY_GRAPH = raw_graph.subgraph(largest_scc).copy()
                    
                    ox.save_graphml(CITY_GRAPH, graph_path)
                    logger.info("Grafo guardado en disco y cargado.")
    return CITY_GRAPH

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

        # Calcular nueva ruta
        try:
            G = get_city_graph()
            orig_node = ox.distance.nearest_nodes(G, self.lon, self.lat)
            dest_node = ox.distance.nearest_nodes(G, lon, lat)
            
            # Calcular ruta más corta considerando longitud y tiempo estimado
            route_nodes = nx.shortest_path(G, orig_node, dest_node, weight='length')
            
            coords = []
            total_distance = 0.0
            for i in range(len(route_nodes) - 1):
                node_a = route_nodes[i]
                node_b = route_nodes[i + 1]
                
                # Obtener coordenadas
                n_data_a = G.nodes[node_a]
                n_data_b = G.nodes[node_b]
                coords.append((n_data_a['y'], n_data_a['x']))  # Store as (lat, lon)
                
                # Calcular distancia acumulada
                edge_data = G.get_edge_data(node_a, node_b)
                if edge_data:
                    # Tomar la primera edge (puede haber múltiples)
                    first_key = list(edge_data.keys())[0]
                    total_distance += edge_data[first_key].get('length', 0)
            
            # Añadir último nodo
            if route_nodes:
                last_node = route_nodes[-1]
                last_data = G.nodes[last_node]
                coords.append((last_data['y'], last_data['x']))
            
            # Añadir destino exacto
            coords.append((lat, lon))
            
            # Calcular eficiencia de ruta
            direct_distance = self._calculate_distance(self.lat, self.lon, lat, lon)
            if direct_distance > 0:
                self.route_efficiency = direct_distance / (total_distance + 0.001)
                self.route_efficiency = min(1.0, max(0.1, self.route_efficiency))
            
            self.route_geometry = coords
            ROUTE_CACHE[cache_key] = self.route_geometry.copy()
            
            logger.info(f"Ruta calculada a {dest_type}: {len(coords)} puntos, "
                       f"distancia {total_distance:.0f}m, eficiencia {self.route_efficiency:.2f}")
            self.routes_calculated += 1
            return True
            
        except Exception as e:
            logger.error(f"Error calculando ruta: {e}")
            self.route_geometry = []  # Sin fallback a línea recta
            self.route_calculation_errors += 1
            self.action_message = f"Error ruta: {str(e)[:30]}"
            return False

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