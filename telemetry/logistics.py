import random
import math

POIS = [
    {"type": "HOSPITAL", "lat": 40.4800, "lon": -3.6500},
    {"type": "HOSPITAL", "lat": 40.4100, "lon": -3.7000},
    {"type": "GAS_STATION", "lat": 40.4400, "lon": -3.6800}
]

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
        self.is_jammed = False
        
    def set_destination(self, lat, lon, dest_type="HOSPITAL"):
        self.destination = (lat, lon)
        self.destination_type = dest_type

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

    def step(self, dt=1.0):
        # Target speed
        target_speed = 80.0
        if self.is_jammed:
            target_speed = 10.0
            
            # Smart Routing: If jammed and heading to hospital, find alternative
            if self.speed < 15.0 and self.destination_type == "HOSPITAL":
                if random.random() < 0.2: # 20% chance per second to realize and detour
                    self.route_to_alternative("HOSPITAL")
                    self.is_jammed = False # Assume detour clears the jam

        if self.destination:
            dest_lat, dest_lon = self.destination
            d_lon = dest_lon - self.lon
            d_lat = dest_lat - self.lat
            self.heading = math.degrees(math.atan2(d_lon, d_lat))
            
            if self.speed < target_speed:
                self.acceleration = 2.0
                self.speed = min(target_speed, self.speed + (self.acceleration * dt * 3.6))
            elif self.speed > target_speed:
                self.speed = max(target_speed, self.speed - (5.0 * dt * 3.6))
                
            distance_to_dest = math.sqrt(d_lat**2 + d_lon**2)
            if distance_to_dest < 0.003: # Reached destination (approx 300m radius)
                self.speed = 0.0
                self.destination = None
        else:
            self.acceleration = 0.0
            self.speed = max(0, self.speed - 5.0 * dt)
            
        self.last_distance_km = (self.speed / 3600.0) * dt
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
            "destination_type": self.destination_type,
            "traffic_status": traffic_status,
            "road_type": self.road_type
        }

    def inject_interference(self, interference_type):
        if interference_type == "traffic_jam":
            self.is_jammed = True
            self.speed = min(self.speed, 10.0)
