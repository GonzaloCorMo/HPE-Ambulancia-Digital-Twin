import paho.mqtt.client as mqtt
import json

class MQTTHandler:
    def __init__(self, broker="localhost", port=1883):
        self.broker = broker
        self.port = port
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.connected = False
        
    def connect(self):
        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
        except Exception as e:
            print(f"[MQTT] Failed to connect to broker: {e}")
            self.connected = False

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("[MQTT] Connected to Central Broker")
            self.connected = True
        else:
            print(f"[MQTT] Connection failed with code {rc}")

    def on_disconnect(self, client, userdata, rc):
        print("[MQTT] Disconnected from Central Broker")
        self.connected = False

    def is_connected(self):
        return self.connected

    def publish_state(self, ambulance_id, state_dict):
        if self.connected:
            topic = f"ambulance/{ambulance_id}/state"
            payload = json.dumps(state_dict)
            self.client.publish(topic, payload, qos=0)
            
    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
