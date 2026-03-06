import socket
import json
import threading
import time
import logging
import select
from typing import Dict, Any, Optional, Callable, List, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class MessageType(Enum):
    """Tipos de mensajes soportados en la malla P2P."""
    HEARTBEAT = "heartbeat"
    STATE_BROADCAST = "state_broadcast"
    EMERGENCY_ALERT = "emergency_alert"
    RESOURCE_REQUEST = "resource_request"
    ROUTE_INFO = "route_info"
    PEER_DISCOVERY = "peer_discovery"

@dataclass
class PeerInfo:
    """Información de un nodo vecino en la malla."""
    ambulance_id: str
    ip_address: str
    port: int
    last_seen: float
    state: Optional[Dict[str, Any]] = None
    signal_strength: float = 1.0
    is_trusted: bool = False
    message_count: int = 0

@dataclass
class MeshMessage:
    """Mensaje estructurado para comunicación P2P."""
    message_id: str
    message_type: MessageType
    sender_id: str
    timestamp: float
    payload: Dict[str, Any]
    ttl: int = 3  # Time To Live para rebotes
    sequence_number: int = 0

class P2PMeshHandler:
    """
    Handler para comunicación P2P (Peer-to-Peer) entre ambulancias.
    Proporciona una malla local resistente para cuando falla la conexión central.
    """
    
    def __init__(self, 
                 port: int = 5005,
                 broadcast_address: str = "255.255.255.255",
                 local_address: str = "0.0.0.0",
                 log_callback: Optional[Callable[[str], None]] = None):
        """
        Inicializa el handler P2P Mesh.
        
        Args:
            port: Puerto UDP para comunicación
            broadcast_address: Dirección de broadcast
            local_address: Dirección local para bind
            log_callback: Función callback para logging
        """
        self.port = port
        self.broadcast_address = broadcast_address
        self.local_address = local_address
        self.log_callback = log_callback or self._default_logger
        
        # Socket UDP para comunicación
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        
        # Configurar socket
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        # Aumentar buffer de recepción
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        
        # Bind para escuchar
        try:
            self.sock.bind((self.local_address, self.port))
        except OSError as e:
            logger.error(f"Error binding to {self.local_address}:{self.port}: {e}")
            # Intentar con puerto diferente
            self.port += 1
            self.sock.bind((self.local_address, self.port))
        
        # Estado
        self.running = False
        self.listen_thread: Optional[threading.Thread] = None
        self.broadcast_thread: Optional[threading.Thread] = None
        self.ambulance_id: Optional[str] = None
        
        # Diccionario de vecinos
        self.peers: Dict[str, PeerInfo] = {}
        self.peers_lock = threading.Lock()
        
        # Historial de mensajes (para evitar duplicados)
        self.message_history: Dict[str, float] = {}
        self.message_history_max = 1000
        self.message_history_ttl = 30.0  # segundos
        
        # Estadísticas
        self.messages_sent = 0
        self.messages_received = 0
        self.broadcast_errors = 0
        self.peer_timeout = 30.0  # segundos
        
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
    
    def _log(self, message: str, level: str = "info") -> None:
        """Log con callback."""
        if self.log_callback:
            self.log_callback(f"[P2P] {message}")
        
        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)
    
    def set_ambulance_id(self, ambulance_id: str) -> None:
        """Establece el ID de la ambulancia para identificación."""
        self.ambulance_id = ambulance_id
    
    def start(self, heartbeat_interval: float = 5.0) -> bool:
        """
        Inicia el handler P2P Mesh.
        
        Args:
            heartbeat_interval: Intervalo entre heartbeats en segundos
            
        Returns:
            True si el inicio fue exitoso
        """
        if self.running:
            self._log("Mesh ya está activo", "warning")
            return True
        
        try:
            self.running = True
            
            # Hilo de escucha
            self.listen_thread = threading.Thread(
                target=self._listen_loop,
                daemon=True,
                name="P2P-Listener"
            )
            self.listen_thread.start()
            
            # Hilo de heartbeat/broadcast
            self.broadcast_thread = threading.Thread(
                target=self._broadcast_loop,
                args=(heartbeat_interval,),
                daemon=True,
                name="P2P-Broadcaster"
            )
            self.broadcast_thread.start()
            
            self._log(f"Mesh activado, UDP {self.local_address}:{self.port} 📡")
            return True
            
        except Exception as e:
            self._log(f"Error iniciando mesh: {e}", "error")
            self.running = False
            return False
    
    def stop(self) -> None:
        """Detiene el handler P2P Mesh."""
        self.running = False
        
        if self.sock:
            try:
                # Enviar mensaje de despedida
                if self.ambulance_id:
                    goodbye_msg = self._create_message(
                        MessageType.HEARTBEAT,
                        {"status": "offline", "timestamp": time.time()}
                    )
                    self._send_message(goodbye_msg, is_broadcast=True)
            except:
                pass
            
            time.sleep(0.1)  # Breve pausa para que se envíe el mensaje
            self.sock.close()
        
        self._log("Mesh detenido 🔌")
    
    def _listen_loop(self) -> None:
        """Loop principal de escucha de mensajes."""
        self._log("Escuchando mensajes P2P...")
        
        while self.running:
            try:
                # Usar select para timeout
                ready = select.select([self.sock], [], [], 1.0)
                if not ready[0]:
                    # Timeout, verificar estado
                    self._cleanup_old_messages()
                    continue
                
                # Recibir datos
                data, addr = self.sock.recvfrom(65536)
                self.messages_received += 1
                
                # Procesar en thread separado para no bloquear
                threading.Thread(
                    target=self._process_message,
                    args=(data, addr),
                    daemon=True
                ).start()
                
            except socket.timeout:
                continue
            except socket.error as e:
                if self.running:
                    self._log(f"Socket error en listen loop: {e}", "error")
                break
            except Exception as e:
                if self.running:
                    self._log(f"Error inesperado en listen loop: {e}", "error")
    
    def _process_message(self, data: bytes, addr: Tuple[str, int]) -> None:
        """Procesa un mensaje recibido."""
        try:
            # Decodificar JSON
            message_dict = json.loads(data.decode('utf-8'))
            
            # Validar estructura básica
            if not all(k in message_dict for k in ['message_id', 'message_type', 'sender_id', 'timestamp']):
                self._log(f"Mensaje malformado de {addr}", "warning")
                return
            
            # Verificar duplicado
            message_id = message_dict['message_id']
            if self._is_duplicate_message(message_id):
                return  # Ignorar duplicado
            
            # Registrar en historial
            self.message_history[message_id] = time.time()
            
            # Limitar tamaño del historial
            if len(self.message_history) > self.message_history_max:
                self._cleanup_old_messages()
            
            # Crear objeto de mensaje
            message = MeshMessage(
                message_id=message_id,
                message_type=MessageType(message_dict['message_type']),
                sender_id=message_dict['sender_id'],
                timestamp=message_dict['timestamp'],
                payload=message_dict.get('payload', {}),
                ttl=message_dict.get('ttl', 3),
                sequence_number=message_dict.get('sequence_number', 0)
            )
            
            # Actualizar información del vecino
            self._update_peer_info(
                ambulance_id=message.sender_id,
                ip_address=addr[0],
                port=addr[1],
                state=message.payload.get('state'),
                message_type=message.message_type
            )
            
            # Procesar según tipo
            self._handle_message_by_type(message, addr)
            
        except json.JSONDecodeError as e:
            self._log(f"Error decodificando JSON de {addr}: {e}", "warning")
        except Exception as e:
            self._log(f"Error procesando mensaje de {addr}: {e}", "error")
    
    def _handle_message_by_type(self, message: MeshMessage, addr: Tuple[str, int]) -> None:
        """Maneja mensaje según su tipo."""
        sender_id = message.sender_id
        
        if message.message_type == MessageType.HEARTBEAT:
            # Solo log si hay cambios
            with self.peers_lock:
                if sender_id in self.peers:
                    peer = self.peers[sender_id]
                    if peer.state != message.payload.get('state'):
                        self._log(f"Heartbeat de {sender_id}: {message.payload.get('status', 'alive')}")
                else:
                    self._log(f"Nuevo vecino detectado: {sender_id} desde {addr[0]}")
        
        elif message.message_type == MessageType.STATE_BROADCAST:
            # Log estado crítico
            state = message.payload.get('state', {})
            if state.get('status') in ['CRITICAL', 'EMERGENCY']:
                self._log(f"🚨 Alerta de {sender_id}: {state.get('status')}", "warning")
        
        elif message.message_type == MessageType.EMERGENCY_ALERT:
            # Alerta de emergencia - alta prioridad
            alert_data = message.payload.get('alert', {})
            alert_type = alert_data.get('type', 'unknown')
            severity = alert_data.get('severity', 'medium')
            
            self._log(f"🚨 EMERGENCIA de {sender_id}: {alert_type} ({severity})", "error")
            
            # Reenviar si TTL > 0 (flooding controlado)
            if message.ttl > 0:
                self._forward_message(message, addr)
        
        elif message.message_type == MessageType.ROUTE_INFO:
            # Información de ruta - útil para coordinación
            route_info = message.payload.get('route', {})
            if route_info:
                self._log(f"📡 Info ruta de {sender_id}: {route_info.get('destination_type', 'unknown')}")
        
        elif message.message_type == MessageType.RESOURCE_REQUEST:
            # Solicitud de recursos
            resource = message.payload.get('resource', {})
            self._log(f"🔄 Solicitud recurso de {sender_id}: {resource.get('type', 'unknown')}")
            
            # Responder si tenemos el recurso
            self._respond_to_resource_request(message, addr)
    
    def _update_peer_info(self, 
                         ambulance_id: str, 
                         ip_address: str, 
                         port: int,
                         state: Optional[Dict[str, Any]] = None,
                         message_type: Optional[MessageType] = None) -> None:
        """Actualiza información de un vecino."""
        current_time = time.time()
        
        with self.peers_lock:
            if ambulance_id in self.peers:
                peer = self.peers[ambulance_id]
                peer.last_seen = current_time
                peer.message_count += 1
                
                if state is not None:
                    peer.state = state
                
                # Actualizar señal basada en actividad
                time_since_last = current_time - peer.last_seen
                if time_since_last < 2.0:  # Mensajes frecuentes = buena señal
                    peer.signal_strength = min(1.0, peer.signal_strength + 0.1)
                else:
                    peer.signal_strength = max(0.1, peer.signal_strength - 0.05)
            else:
                # Nuevo vecino
                self.peers[ambulance_id] = PeerInfo(
                    ambulance_id=ambulance_id,
                    ip_address=ip_address,
                    port=port,
                    last_seen=current_time,
                    state=state,
                    signal_strength=1.0,
                    is_trusted=False,
                    message_count=1
                )
                
                # Marcar como trusted después de varios mensajes
                if message_type == MessageType.HEARTBEAT:
                    self.peers[ambulance_id].is_trusted = True
    
    def _cleanup_old_messages(self) -> None:
        """Limpia mensajes antiguos del historial."""
        current_time = time.time()
        expired_keys = [
            msg_id for msg_id, timestamp in self.message_history.items()
            if current_time - timestamp > self.message_history_ttl
        ]
        
        for msg_id in expired_keys:
            del self.message_history[msg_id]
    
    def _is_duplicate_message(self, message_id: str) -> bool:
        """Verifica si un mensaje es duplicado."""
        return message_id in self.message_history
    
    def _create_message(self, 
                       message_type: MessageType, 
                       payload: Dict[str, Any],
                       ttl: int = 3) -> MeshMessage:
        """
        Crea un mensaje estructurado.
        
        Args:
            message_type: Tipo de mensaje
            payload: Datos del mensaje
            ttl: Time To Live para reenvío
            
        Returns:
            Mensaje estructurado
        """
        return MeshMessage(
            message_id=f"{self.ambulance_id}-{int(time.time() * 1000)}-{self.messages_sent}",
            message_type=message_type,
            sender_id=self.ambulance_id or "unknown",
            timestamp=time.time(),
            payload=payload,
            ttl=ttl,
            sequence_number=self.messages_sent
        )
    
    def _send_message(self, 
                     message: MeshMessage, 
                     target_address: Optional[Tuple[str, int]] = None,
                     is_broadcast: bool = False) -> bool:
        """
        Envía un mensaje.
        
        Args:
            message: Mensaje a enviar
            target_address: Dirección específica (ip, port)
            is_broadcast: Si es broadcast general
            
        Returns:
            True si el envío fue exitoso
        """
        if not self.running or not self.sock:
            return False
        
        try:
            # Convertir a JSON
            message_dict = {
                "message_id": message.message_id,
                "message_type": message.message_type.value,
                "sender_id": message.sender_id,
                "timestamp": message.timestamp,
                "payload": message.payload,
                "ttl": message.ttl,
                "sequence_number": message.sequence_number
            }
            
            data = json.dumps(message_dict).encode('utf-8')
            
            if is_broadcast:
                # Broadcast a toda la red
                self.sock.sendto(data, (self.broadcast_address, self.port))
                self.messages_sent += 1
                return True
            elif target_address:
                # Envío directo
                self.sock.sendto(data, target_address)
                self.messages_sent += 1
                return True
            else:
                # Envío a todos los vecinos conocidos
                sent_count = 0
                with self.peers_lock:
                    for peer_id, peer in self.peers.items():
                        if peer_id != self.ambulance_id:
                            try:
                                self.sock.sendto(data, (peer.ip_address, peer.port))
                                sent_count += 1
                            except:
                                pass
                
                if sent_count > 0:
                    self.messages_sent += sent_count
                    return True
                
                return False
                
        except Exception as e:
            self.broadcast_errors += 1
            self._log(f"Error enviando mensaje: {e}", "warning")
            return False
    
    def _forward_message(self, message: MeshMessage, source_addr: Tuple[str, int]) -> None:
        """Reenvía un mensaje a otros vecinos (flooding controlado)."""
        # Reducir TTL
        message.ttl -= 1
        if message.ttl <= 0:
            return
        
        # Reenviar a todos excepto al remitente original
        with self.peers_lock:
            for peer_id, peer in self.peers.items():
                if (peer_id != message.sender_id and 
                    peer_id != self.ambulance_id and
                    (peer.ip_address, peer.port) != source_addr):
                    
                    # Actualizar ID del mensaje para evitar bucles
                    new_message_id = f"{self.ambulance_id}-forward-{message.message_id}"
                    message.message_id = new_message_id
                    
                    self._send_message(message, (peer.ip_address, peer.port))
    
    def _respond_to_resource_request(self, message: MeshMessage, addr: Tuple[str, int]) -> None:
        """Responde a una solicitud de recursos."""
        resource_type = message.payload.get('resource', {}).get('type', '')
        
        # Simular respuesta basada en recursos disponibles
        # En implementación real, verificaría recursos reales
        response_payload = {
            "request_id": message.message_id,
            "resource_type": resource_type,
            "available": False,
            "alternative": None,
            "timestamp": time.time()
        }
        
        # Crear mensaje de respuesta
        response = self._create_message(
            MessageType.RESOURCE_REQUEST,
            {"response": response_payload}
        )
        
        self._send_message(response, addr)
    
    def _broadcast_loop(self, interval: float) -> None:
        """Loop periódico de broadcast de estado."""
        self._log(f"Iniciando heartbeat cada {interval}s")
        
        while self.running:
            try:
                # Enviar heartbeat
                self.broadcast_heartbeat()
                
                # Limpiar vecinos antiguos
                self._cleanup_old_peers()
                
                # Esperar intervalo
                time.sleep(interval)
                
            except Exception as e:
                self._log(f"Error en broadcast loop: {e}", "error")
                time.sleep(interval)
    
    def broadcast_heartbeat(self) -> None:
        """Transmite heartbeat a la red."""
        if not self.ambulance_id:
            return
        
        heartbeat_payload = {
            "status": "alive",
            "timestamp": time.time(),
            "peers_count": len(self.peers),
            "position": None  # Será llenado por el caller si está disponible
        }
        
        message = self._create_message(
            MessageType.HEARTBEAT,
            heartbeat_payload,
            ttl=1  # Heartbeats no se reenvían
        )
        
        self._send_message(message, is_broadcast=True)
    
    def broadcast_state(self, state_dict: Dict[str, Any]) -> bool:
        """
        Transmite estado crítico a la red.
        
        Args:
            state_dict: Estado a transmitir
            
        Returns:
            True si la transmisión fue exitosa
        """
        if not self.ambulance_id:
            return False
        
        state_payload = {
            "state": state_dict,
            "timestamp": time.time(),
            "priority": "high" if state_dict.get('status') in ['CRITICAL', 'EMERGENCY'] else "normal"
        }
        
        message = self._create_message(
            MessageType.STATE_BROADCAST,
            state_payload,
            ttl=2  # Se reenvía una vez
        )
        
        return self._send_message(message, is_broadcast=True)
    
    def broadcast_emergency(self, 
                           emergency_type: str,
                           emergency_data: Dict[str, Any],
                           severity: str = "high") -> bool:
        """
        Transmite alerta de emergencia a la red.
        
        Args:
            emergency_type: Tipo de emergencia
            emergency_data: Datos de la emergencia
            severity: Severidad (low, medium, high, critical)
            
        Returns:
            True si la transmisión fue exitosa
        """
        alert_payload = {
            "alert": {
                "type": emergency_type,
                "severity": severity,
                "data": emergency_data,
                "timestamp": time.time(),
                "sender_id": self.ambulance_id
            }
        }
        
        message = self._create_message(
            MessageType.EMERGENCY_ALERT,
            alert_payload,
            ttl=5  # Alta prioridad, se reenvía varias veces
        )
        
        success = self._send_message(message, is_broadcast=True)
        
        if success:
            self._log(f"🚨 Alerta de emergencia transmitida: {emergency_type} ({severity})")
        
        return success
    
    def request_resource(self, 
                        resource_type: str,
                        resource_details: Dict[str, Any]) -> bool:
        """
        Solicita un recurso a la red.
        
        Args:
            resource_type: Tipo de recurso solicitado
            resource_details: Detalles del recurso
            
        Returns:
            True si la solicitud fue transmitida
        """
        resource_payload = {
            "resource": {
                "type": resource_type,
                "details": resource_details,
                "timestamp": time.time(),
                "requester_id": self.ambulance_id
            }
        }
        
        message = self._create_message(
            MessageType.RESOURCE_REQUEST,
            resource_payload,
            ttl=3
        )
        
        return self._send_message(message, is_broadcast=True)
    
    def send_route_info(self, 
                       route_data: Dict[str, Any],
                       target_ambulance: Optional[str] = None) -> bool:
        """
        Envía información de ruta.
        
        Args:
            route_data: Datos de la ruta
            target_ambulance: Ambulancia específica (None para broadcast)
            
        Returns:
            True si el envío fue exitoso
        """
        route_payload = {
            "route": route_data,
            "timestamp": time.time(),
            "intended_receiver": target_ambulance
        }
        
        message = self._create_message(
            MessageType.ROUTE_INFO,
            route_payload,
            ttl=2
        )
        
        if target_ambulance:
            # Envío directo
            with self.peers_lock:
                if target_ambulance in self.peers:
                    peer = self.peers[target_ambulance]
                    return self._send_message(message, (peer.ip_address, peer.port))
                else:
                    self._log(f"Vecino {target_ambulance} no encontrado para envío directo", "warning")
                    return False
        else:
            # Broadcast
            return self._send_message(message, is_broadcast=True)
    
    def _cleanup_old_peers(self) -> None:
        """Elimina vecinos antiguos del registro."""
        current_time = time.time()
        
        with self.peers_lock:
            expired_peers = [
                peer_id for peer_id, peer in self.peers.items()
                if current_time - peer.last_seen > self.peer_timeout
            ]
            
            for peer_id in expired_peers:
                peer = self.peers.pop(peer_id, None)
                if peer:
                    self._log(f"Vecino {peer_id} expirado (última vez: {peer.last_seen})")
    
    def get_active_peers(self, timeout: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
        """
        Retorna vecinos activos.
        
        Args:
            timeout: Tiempo máximo sin contacto en segundos (None = usar default)
            
        Returns:
            Diccionario con información de vecinos activos
        """
        timeout = timeout or self.peer_timeout
        current_time = time.time()
        
        active_peers = {}
        with self.peers_lock:
            for peer_id, peer in self.peers.items():
                if current_time - peer.last_seen <= timeout:
                    active_peers[peer_id] = {
                        "ip": peer.ip_address,
                        "port": peer.port,
                        "last_seen": peer.last_seen,
                        "signal_strength": peer.signal_strength,
                        "is_trusted": peer.is_trusted,
                        "message_count": peer.message_count,
                        "state": peer.state
                    }
        
        return active_peers
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Retorna estadísticas del handler P2P.
        
        Returns:
            Diccionario con estadísticas
        """
        with self.peers_lock:
            peer_count = len(self.peers)
            trusted_peers = sum(1 for p in self.peers.values() if p.is_trusted)
            avg_signal = sum(p.signal_strength for p in self.peers.values()) / max(1, peer_count)
        
        return {
            "running": self.running,
            "port": self.port,
            "ambulance_id": self.ambulance_id,
            "peers_count": peer_count,
            "trusted_peers": trusted_peers,
            "average_signal_strength": round(avg_signal, 2),
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
            "broadcast_errors": self.broadcast_errors,
            "message_history_size": len(self.message_history),
            "peer_timeout": self.peer_timeout
        }
    
    def is_connected(self) -> bool:
        """
        Verifica si hay conexión P2P activa.
        
        Returns:
            True si hay al menos un vecino activo
        """
        active_peers = self.get_active_peers(timeout=60.0)  # 1 minuto
        return len(active_peers) > 0
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()