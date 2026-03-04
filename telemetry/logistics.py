import random
import math

class LogisticsEngine:
    def __init__(self, start_lat=40.4168, start_lon=-3.7038): # Default: Madrid
        self.lat = start_lat
        self.lon = start_lon
        self.speed = 0.0 # km/h
        self.heading = random.uniform(0, 360) # degrees
        self.acceleration = 0.0 # m/s^2
        self.destination = None
        
    def set_destination(self, lat, lon):
        self.destination = (lat, lon)

    def step(self, dt=1.0):
        # Very simplified generic movement
        if self.destination:
            # Calculate heading towards destination
            dest_lat, dest_lon = self.destination
            d_lon = dest_lon - self.lon
            d_lat = dest_lat - self.lat
            self.heading = math.degrees(math.atan2(d_lon, d_lat))
            
            # Accelerate up to 80 km/h
            if self.speed < 80:
                self.acceleration = 2.0
                self.speed += self.acceleration * dt * 3.6 # m/s to km/h
            else:
                self.acceleration = 0.0
                
            distance_to_dest = math.sqrt(d_lat**2 + d_lon**2)
            if distance_to_dest < 0.001: # Reached destination
                self.speed = 0.0
                self.destination = None
        else:
            self.acceleration = 0.0
            self.speed = max(0, self.speed - 5.0 * dt) # Brake if no destination
            
        # Move
        distance_km = (self.speed / 3600.0) * dt
        # 1 degree lat = 111 km approx
        self.lat += (distance_km * math.cos(math.radians(self.heading))) / 111.0
        self.lon += (distance_km * math.sin(math.radians(self.heading))) / (111.0 * math.cos(math.radians(self.lat)))

        return self.get_state()

    def get_state(self):
        return {
            "latitude": round(self.lat, 6),
            "longitude": round(self.lon, 6),
            "speed": round(self.speed, 2),
            "heading": round(self.heading, 2),
            "acceleration": round(self.acceleration, 2),
            "has_destination": self.destination is not None
        }

    def inject_interference(self, interference_type):
        if interference_type == "traffic_jam":
            self.speed = min(self.speed, 10.0) # Max 10 km/h
        elif interference_type == "accident_ahead":
            self.speed = 0.0
