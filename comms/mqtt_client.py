import paho.mqtt.client as mqtt
import json
import logging
import time
from typing import Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)

class MQTTHandler:
    """
    Handler MQTT para comunicación con centralita de ambulancias.
    Proporciona conexión robusta con reconexión automática y QoS configurable.
    """
    
    def __init__(self, 
                 broker: str = "localhost", 
                 port: int = 1883, 
                 client_id: Optional[str] = None,
                 keepalive: int = 60,
                 log_callback: Optional[Callable[[str], None]] = None):
        """
        Inicializa el handler MQTT.
        
        Args:
            broker: Dirección del broker MQTT
            port: Puerto del broker
            client_id: ID único del cliente (auto-generado si None)
            keepalive: Keepalive en segundos
            log_callback: Función callback para logging
        """
        self.broker = broker
        self.port = port
        self.keepalive = keepalive
        self.log_callback = log_callback or self._default_logger
        
        # Configurar cliente
        self.client_id = client_id or f"ambulance-mqtt-{int(time.time())}"
        self.client = mqtt.Client(client_id=self.client_id)
        
        # Callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish
        self.client.on_message = self._on_message
        
        # Estado
        self.connected = False
        self.connection_attempts = 0
        self.last_connection_time = 0.0
        self.last_publish_time = 0.0
        
        # Estadísticas
        self.messages_published = 0
        self.messages_received = 0
        self.publish_errors = 0
        
        # Suscripciones
        self.subscriptions: Dict[str, Callable] = {}
        
        # Configurar logger
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
    
    def _default_logger(self, message: str) -> None:
        """Logger por defecto."""
        logger.info(message)
    
    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Dict, rc: int) -> None:
        """
        Callback ejecutado cuando se conecta al broker.
        
        Args:
            client: Cliente MQTT
            userdata: Datos de usuario
            flags: Flags de conexión
            rc: Código de resultado (0 = éxito)
        """
        self.connection_attempts += 1
        self.last_connection_time = time.time()
        
        if rc == 0:
            self.connected = True
            msg = f"[MQTT] ✅ Conectado al broker {self.broker}:{self.port} (ID: {self.client_id})"
            self.log_callback(msg)
            logger.info(msg)
            
            # Re-suscribir a topics si existen suscripciones previas
            for topic, callback in self.subscriptions.items():
                self._subscribe_internal(topic, callback)
        else:
            self.connected = False
            error_msgs = {
                1: "Protocol version incorrect",
                2: "Client identifier invalid",
                3: "Server unavailable",
                4: "Bad username or password",
                5: "Not authorized"
            }
            error_msg = error_msgs.get(rc, f"Unknown error code: {rc}")
            msg = f"[MQTT] ❌ Conexión fallida: {error_msg} (code: {rc})"
            self.log_callback(msg)
            logger.error(msg)
    
    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        """
        Callback ejecutado cuando se desconecta del broker.
        
        Args:
            client: Cliente MQTT
            userdata: Datos de usuario
            rc: Código de resultado (0 = desconexión normal)
        """
        self.connected = False
        if rc == 0:
            msg = "[MQTT] 🔌 Desconexión normal del broker"
            self.log_callback(msg)
            logger.info(msg)
        else:
            msg = f"[MQTT] ⚠️ Desconexión inesperada (code: {rc}), intentando reconectar..."
            self.log_callback(msg)
            logger.warning(msg)
            # El cliente MQTT manejará la reconexión automática
    
    def _on_publish(self, client: mqtt.Client, userdata: Any, mid: int) -> None:
        """
        Callback ejecutado cuando se publica un mensaje.
        
        Args:
            client: Cliente MQTT
            userdata: Datos de usuario
            mid: Message ID
        """
        self.messages_published += 1
        self.last_publish_time = time.time()
        logger.debug(f"Message published (mid: {mid})")
    
    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """
        Callback ejecutado cuando se recibe un mensaje.
        
        Args:
            client: Cliente MQTT
            userdata: Datos de usuario
            msg: Mensaje recibido
        """
        self.messages_received += 1
        logger.debug(f"Message received on {msg.topic}: {msg.payload[:50]}...")
        
        # Ejecutar callback específico del topic si existe
        if msg.topic in self.subscriptions:
            try:
                payload = json.loads(msg.payload.decode('utf-8')) if msg.payload else {}
                self.subscriptions[msg.topic](msg.topic, payload)
            except json.JSONDecodeError:
                logger.error(f"Error decoding JSON from topic {msg.topic}")
            except Exception as e:
                logger.error(f"Error in subscription callback for {msg.topic}: {e}")
    
    def _subscribe_internal(self, topic: str, callback: Callable) -> None:
        """Suscripción interna al topic."""
        try:
            result = self.client.subscribe(topic, qos=1)
            if result[0] == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Subscribed to topic: {topic}")
            else:
                logger.error(f"Failed to subscribe to {topic}: error code {result[0]}")
        except Exception as e:
            logger.error(f"Error subscribing to {topic}: {e}")
    
    def connect(self, max_retries: int = 3, retry_delay: float = 2.0) -> bool:
        """
        Conecta al broker MQTT con reintentos.
        
        Args:
            max_retries: Máximo número de reintentos
            retry_delay: Delay entre reintentos en segundos
            
        Returns:
            True si la conexión fue exitosa
        """
        if self.connected:
            logger.warning("Already connected to MQTT broker")
            return True
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Connecting to MQTT broker at {self.broker}:{self.port} (attempt {attempt + 1}/{max_retries})...")
                self.client.connect(self.broker, self.port, self.keepalive)
                self.client.loop_start()
                
                # Esperar conexión (máximo 5 segundos)
                timeout = 5.0
                start_time = time.time()
                while not self.connected and (time.time() - start_time) < timeout:
                    time.sleep(0.1)
                
                if self.connected:
                    return True
                else:
                    logger.warning(f"Connection attempt {attempt + 1} failed")
                    
            except ConnectionRefusedError as e:
                logger.error(f"Connection refused: {e}")
            except TimeoutError as e:
                logger.error(f"Connection timeout: {e}")
            except Exception as e:
                logger.error(f"Connection error: {e}")
            
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
        
        logger.error(f"Failed to connect to MQTT broker after {max_retries} attempts")
        return False
    
    def disconnect(self) -> None:
        """Desconecta del broker MQTT."""
        try:
            if self.connected:
                self.client.loop_stop()
                self.client.disconnect()
                self.connected = False
                logger.info("Disconnected from MQTT broker")
        except Exception as e:
            logger.error(f"Error disconnecting from MQTT broker: {e}")
    
    def is_connected(self) -> bool:
        """
        Verifica si está conectado al broker.
        
        Returns:
            True si está conectado
        """
        return self.connected
    
    def publish_state(self, ambulance_id: str, state_dict: Dict[str, Any], 
                     qos: int = 1, retain: bool = False) -> bool:
        """
        Publica estado de una ambulancia.
        
        Args:
            ambulance_id: ID de la ambulancia
            state_dict: Diccionario con estado de la ambulancia
            qos: Calidad de servicio (0, 1, 2)
            retain: Si el mensaje debe ser retain
            
        Returns:
            True si el mensaje fue publicado exitosamente
        """
        if not self.connected:
            logger.warning("Cannot publish: not connected to MQTT broker")
            return False
        
        try:
            topic = f"ambulance/{ambulance_id}/state"
            payload = json.dumps(state_dict, default=str)
            
            result = self.client.publish(topic, payload, qos=qos, retain=retain)
            
            # Esperar confirmación para QoS > 0
            if qos > 0:
                result.wait_for_publish(timeout=2.0)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"State published to {topic}")
                return True
            else:
                self.publish_errors += 1
                logger.error(f"Failed to publish to {topic}: error code {result.rc}")
                return False
                
        except Exception as e:
            self.publish_errors += 1
            logger.error(f"Error publishing state for {ambulance_id}: {e}")
            return False
    
    def publish_alert(self, ambulance_id: str, alert_type: str, 
                     alert_data: Dict[str, Any], qos: int = 2) -> bool:
        """
        Publica una alerta de emergencia.
        
        Args:
            ambulance_id: ID de la ambulancia
            alert_type: Tipo de alerta (critical, warning, info)
            alert_data: Datos de la alerta
            qos: Calidad de servicio (usualmente 2 para alertas)
            
        Returns:
            True si la alerta fue publicada exitosamente
        """
        if not self.connected:
            logger.warning("Cannot publish alert: not connected to MQTT broker")
            return False
        
        try:
            topic = f"ambulance/{ambulance_id}/alerts/{alert_type}"
            payload = json.dumps({
                "timestamp": time.time(),
                "ambulance_id": ambulance_id,
                "alert_type": alert_type,
                **alert_data
            }, default=str)
            
            result = self.client.publish(topic, payload, qos=qos, retain=False)
            
            if qos > 0:
                result.wait_for_publish(timeout=2.0)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Alert published: {alert_type} for {ambulance_id}")
                return True
            else:
                self.publish_errors += 1
                logger.error(f"Failed to publish alert for {ambulance_id}: error code {result.rc}")
                return False
                
        except Exception as e:
            self.publish_errors += 1
            logger.error(f"Error publishing alert for {ambulance_id}: {e}")
            return False
    
    def subscribe(self, topic: str, callback: Callable[[str, Dict], None]) -> bool:
        """
        Suscribe a un topic específico.
        
        Args:
            topic: Topic al que suscribirse
            callback: Función a ejecutar cuando llega mensaje (topic, payload)
            
        Returns:
            True si la suscripción fue exitosa
        """
        try:
            self.subscriptions[topic] = callback
            
            if self.connected:
                self._subscribe_internal(topic, callback)
                return True
            else:
                logger.warning(f"Subscription queued (not connected): {topic}")
                return False
                
        except Exception as e:
            logger.error(f"Error subscribing to {topic}: {e}")
            return False
    
    def unsubscribe(self, topic: str) -> bool:
        """
        Cancela suscripción a un topic.
        
        Args:
            topic: Topic a desuscribir
            
        Returns:
            True si la desuscripción fue exitosa
        """
        try:
            if topic in self.subscriptions:
                if self.connected:
                    self.client.unsubscribe(topic)
                del self.subscriptions[topic]
                logger.info(f"Unsubscribed from topic: {topic}")
                return True
            else:
                logger.warning(f"Not subscribed to topic: {topic}")
                return False
        except Exception as e:
            logger.error(f"Error unsubscribing from {topic}: {e}")
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Retorna estadísticas del handler MQTT.
        
        Returns:
            Diccionario con estadísticas
        """
        return {
            "connected": self.connected,
            "broker": f"{self.broker}:{self.port}",
            "client_id": self.client_id,
            "connection_attempts": self.connection_attempts,
            "last_connection_time": self.last_connection_time,
            "last_publish_time": self.last_publish_time,
            "messages_published": self.messages_published,
            "messages_received": self.messages_received,
            "publish_errors": self.publish_errors,
            "subscriptions_count": len(self.subscriptions),
            "subscriptions": list(self.subscriptions.keys())
        }
    
    def set_will(self, topic: str, payload: Dict[str, Any], qos: int = 1, retain: bool = True) -> None:
        """
        Configura mensaje de última voluntad (LWT).
        
        Args:
            topic: Topic para mensaje LWT
            payload: Payload del mensaje
            qos: Calidad de servicio
            retain: Si el mensaje debe ser retain
        """
        try:
            will_payload = json.dumps(payload, default=str)
            self.client.will_set(topic, will_payload, qos=qos, retain=retain)
            logger.info(f"LWT configured for topic: {topic}")
        except Exception as e:
            logger.error(f"Error setting LWT: {e}")
    
    def reconnect(self) -> bool:
        """
        Fuerza reconexión al broker.
        
        Returns:
            True si la reconexión fue exitosa
        """
        logger.info("Forcing MQTT reconnection...")
        self.disconnect()
        time.sleep(1.0)  # Breve pausa
        return self.connect(max_retries=2, retry_delay=1.0)