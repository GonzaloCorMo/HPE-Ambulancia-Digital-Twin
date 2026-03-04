import random
import math

# Shared Global State for dynamic map elements
POIS = []

# Jams are geofenced circles: {"lat": ..., "lon": ..., "radius": 0.005}
JAMS = []

def add_poi(poi_type, lat, lon):
    POIS.append({"type": poi_type, "lat": lat, "lon": lon})

def add_jam(lat, lon, radius=0.005):
    JAMS.append({"lat": lat, "lon": lon, "radius": radius})

class LogisticsEngine:
    def __init__(self, start_lat=40.4168, start_lon=-3.7038):
        self.lat = start_lat
        self.lon = start_lon
        self.speed = 0.0 # km/h
        self.heading = random.uniform(0, 360) 
        self.acceleration = 0.0
        self.destination = None
        self.destination_type = None
        self.road_type = "urban"
        self.last_distance_km = 0.0
        self.mission_status = "ACTIVE" # ACTIVE, IN_USE, INACTIVE
        self.route_geometry = []
        self.route_step = 0
        
    def set_destination(self, lat, lon, dest_type="HOSPITAL"):
        self.destination = (lat, lon)
        self.destination_type = dest_type
        self.route_geometry = []
        self.route_step = 0
        try:
            import urllib.request, json
            url = f"https://router.project-osrm.org/route/v1/driving/{self.lon},{self.lat};{lon},{lat}?overview=full&geometries=geojson"
            req = urllib.request.Request(url, headers={'User-Agent': 'AmbulanceTwin/1.0'})
            with urllib.request.urlopen(req, timeout=2) as response:
                data = json.loads(response.read().decode())
                if data.get("routes") and len(data["routes"]) > 0:
                    coords = data["routes"][0]["geometry"]["coordinates"]
                    self.route_geometry = [(c[1], c[0]) for c in coords] # Store as (lat, lon)
        except Exception as e:
            print(f"OSRM Route fetch error: {e}")
            self.route_geometry = [(self.lat, self.lon), (lat, lon)]

    def route_to_nearest(self, dest_type):
        best, min_d = None, 999999
        for p in POIS:
            if p["type"] == dest_type:
                d = math.sqrt((p["lat"]-self.lat)**2 + (p["lon"]-self.lon)**2)
                if d < min_d:
                    min_d, best = d, p
        if best:
            self.set_destination(best["lat"], best["lon"], dest_type)

    def route_to_alternative(self, dest_type):
        # Find a different location of the same type if current path is bad
        best, min_d = None, 999999
        for p in POIS:
            if p["type"] == dest_type and self.destination:
                if abs(p["lat"] - self.destination[0]) < 0.0001:
                    continue # Skip current
            if p["type"] == dest_type:
                d = math.sqrt((p["lat"]-self.lat)**2 + (p["lon"]-self.lon)**2)
                if d < min_d:
                    min_d, best = d, p
        if best:
            self.set_destination(best["lat"], best["lon"], dest_type)

    def step(self, dt=1.0, speed_multiplier=1.0):
        adjusted_dt = dt * speed_multiplier
        
        # Geofence Jam Detection
        in_jam = False
        for jam in JAMS:
            d = math.sqrt((jam["lat"] - self.lat)**2 + (jam["lon"] - self.lon)**2)
            if d <= jam["radius"]:
                in_jam = True
                break

        # Target speed
        target_speed = 80.0
        if in_jam:
            target_speed = 10.0
            
            # Smart Routing: If jammed and heading to hospital, find alternative
            if self.speed < 15.0 and self.destination_type == "HOSPITAL":
                if random.random() < 0.2 * adjusted_dt: # 20% chance per second to realize and detour
                    self.route_to_alternative("HOSPITAL")

        if self.destination and getattr(self, "route_geometry", None) and getattr(self, "route_step", 0) < len(self.route_geometry):
            target_lat, target_lon = self.route_geometry[self.route_step]
            d_lon = target_lon - self.lon
            d_lat = target_lat - self.lat
            self.heading = math.degrees(math.atan2(d_lon, d_lat))
            
            if self.speed < target_speed:
                self.acceleration = 2.0
                self.speed = min(target_speed, self.speed + (self.acceleration * adjusted_dt * 3.6))
            elif self.speed > target_speed:
                self.speed = max(target_speed, self.speed - (5.0 * adjusted_dt * 3.6))
                
            distance_to_dest = math.sqrt(d_lat**2 + d_lon**2)
            if distance_to_dest < 0.005: # reached local node
                self.route_step += 1
                if self.route_step >= len(self.route_geometry):
                    self.speed = 0.0
                    self.destination = None
                    self.lat, self.lon = target_lat, target_lon # Snap exactly to target instantly
                    self.route_geometry = []
        else:
            self.acceleration = 0.0
            self.speed = max(0, self.speed - 5.0 * adjusted_dt)
            
        self.last_distance_km = (self.speed / 3600.0) * adjusted_dt
        self.lat += (self.last_distance_km * math.cos(math.radians(self.heading))) / 111.0
        self.lon += (self.last_distance_km * math.sin(math.radians(self.heading))) / (111.0 * math.cos(math.radians(self.lat)))

        return self.get_state()

    def get_state(self):
        traffic_status = "clear"
        if self.speed > 0 and self.speed < 20 and self.destination:
            traffic_status = "heavy"
        elif self.speed >= 20 and self.speed < 50:
            traffic_status = "moderate"
            
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
            "traffic_status": traffic_status,
            "road_type": self.road_type,
            "mission_status": self.mission_status
        }

    def inject_interference(self, interference_type):
        if interference_type == "traffic_jam":
            # Just create a dynamic jam right on top of the ambulance
            add_jam(self.lat, self.lon, 0.005)
