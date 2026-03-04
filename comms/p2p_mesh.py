import socket
import json
import threading
import time

class P2PMeshHandler:
    def __init__(self, port=5005):
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        
        # Permitir reutilizar el puerto para que múltiples ambulancias en el mismo PC no choquen
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Enable broadcasting mode
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        # Bind for listening to other ambulances on the same port
        self.sock.bind(("", self.port))
        
        self.running = False
        self.listen_thread = None
        self.peers_detected = {} # Track other ambulances

    def start(self):
        self.running = True
        self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listen_thread.start()
        print(f"[P2P] Mesh activated, listening on UDP {self.port}")

    def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()

    def broadcast_state(self, state_dict):
        # When MQTT is down, broadcast the critical data (especially Logistics)
        try:
            payload = json.dumps(state_dict).encode("utf-8")
            self.sock.sendto(payload, ('<broadcast>', self.port))
        except Exception as e:
            print(f"[P2P] Broadcast error: {e}")

    def _listen_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                msg = json.loads(data.decode("utf-8"))
                
                # Check if it's from another ambulance
                am_id = msg.get("ambulance_id")
                if am_id:
                    self.peers_detected[am_id] = {
                        "last_seen": time.time(),
                        "ip": addr[0]
                    }
                    # Minimal log to show peer communication working
                    # print(f"[P2P] Heard from peer: {am_id} at {addr[0]}")
            except socket.error:
                # Socket closed or error
                break
            except Exception as e:
                pass
                
    def get_active_peers(self, timeout=10.0):
        # Returns peers heard from in the last 10 seconds
        current_time = time.time()
        active = {k: v for k, v in self.peers_detected.items() if (current_time - v['last_seen']) <= timeout}
        return active
