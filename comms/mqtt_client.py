import paho.mqtt.client as mqtt
import json

class MQTTHandler:
    def __init__(self, broker="localhost", port=1883, log_callback=None):
        self.broker = broker
        self.port = port
        self.log_callback = log_callback
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.connected = False
        
    def connect(self):
        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
        except Exception as e:
            msg = f"[MQTT] Failed to connect to broker: {e}"
            if self.log_callback: self.log_callback(msg)
            else: print(msg)
            self.connected = False

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            msg = "[MQTT] Connected to Central Broker 🟢"
            if self.log_callback: self.log_callback(msg)
            else: print(msg)
            self.connected = True
        else:
            msg = f"[MQTT] Connection failed with code {rc} 🔴"
            if self.log_callback: self.log_callback(msg)
            else: print(msg)

    def on_disconnect(self, client, userdata, rc):
        msg = "[MQTT] Disconnected from Central Broker 🔴"
        if self.log_callback: self.log_callback(msg)
        else: print(msg)
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
