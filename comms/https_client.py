import requests
import threading
import logging
import time
import json
from typing import Dict, Any, Optional, Callable, List, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class HTTPMethod(Enum):
    """Métodos HTTP soportados."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"

@dataclass
class RequestConfig:
    """Configuración para peticiones HTTP."""
    timeout: float = 10.0
    max_retries: int = 3
    retry_delay: float = 2.0
    verify_ssl: bool = True
    auth: Optional[Tuple[str, str]] = None
    headers: Optional[Dict[str, str]] = None

class HTTPResponse:
    """Respuesta HTTP estructurada."""
    
    def __init__(self, 
                 status_code: int, 
                 data: Any, 
                 headers: Dict[str, str],
                 elapsed_time: float,
                 success: bool):
        self.status_code = status_code
        self.data = data
        self.headers = headers
        self.elapsed_time = elapsed_time
        self.success = success
        self.timestamp = time.time()
    
    def is_success(self) -> bool:
        """Verifica si la respuesta es exitosa (2xx)."""
        return 200 <= self.status_code < 300
    
    def is_client_error(self) -> bool:
        """Verifica si es error del cliente (4xx)."""
        return 400 <= self.status_code < 500
    
    def is_server_error(self) -> bool:
        """Verifica si es error del servidor (5xx)."""
        return 500 <= self.status_code < 600
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte respuesta a diccionario."""
        return {
            "status_code": self.status_code,
            "data": self.data,
            "headers": self.headers,
            "elapsed_time": self.elapsed_time,
            "success": self.success,
            "timestamp": self.timestamp
        }

class HTTPSHandler:
    """
    Handler HTTP/HTTPS para comunicación con backend central.
    Proporciona métodos robustos con reintentos, timeouts y métricas.
    """
    
    def __init__(self, 
                 base_url: str = "http://localhost:8000",
                 default_config: Optional[RequestConfig] = None,
                 log_callback: Optional[Callable[[str], None]] = None):
        """
        Inicializa el handler HTTPS.
        
        Args:
            base_url: URL base del backend (incluye protocolo://host:port)
            default_config: Configuración por defecto para peticiones
            log_callback: Función callback para logging
        """
        self.base_url = base_url.rstrip('/')
        self.default_config = default_config or RequestConfig()
        self.log_callback = log_callback or self._default_logger
        
        # Sesión HTTP para reutilizar conexiones
        self.session = requests.Session()
        
        # Estadísticas
        self.requests_sent = 0
        self.requests_failed = 0
        self.total_request_time = 0.0
        self.last_request_time = 0.0
        
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
            self.log_callback(message)
        
        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)
    
    def _make_request(self, 
                     method: HTTPMethod, 
                     endpoint: str, 
                     data: Optional[Dict[str, Any]] = None,
                     config: Optional[RequestConfig] = None) -> HTTPResponse:
        """
        Realiza petición HTTP con reintentos.
        
        Args:
            method: Método HTTP
            endpoint: Endpoint (sin base_url)
            data: Datos a enviar (para POST/PUT/PATCH)
            config: Configuración específica para esta petición
            
        Returns:
            HTTPResponse con resultado
        """
        config = config or self.default_config
        url = f"{self.base_url}{endpoint}"
        
        # Preparar headers
        headers = config.headers or {}
        if 'Content-Type' not in headers and data is not None:
            headers['Content-Type'] = 'application/json'
        
        # Preparar datos
        json_data = None
        if data is not None and method in [HTTPMethod.POST, HTTPMethod.PUT, HTTPMethod.PATCH]:
            json_data = data
        
        # Intentar con retries
        last_exception = None
        
        for attempt in range(config.max_retries):
            try:
                self._log(f"HTTP {method.value} to {url} (attempt {attempt + 1}/{config.max_retries})...")
                
                start_time = time.time()
                
                response = self.session.request(
                    method=method.value,
                    url=url,
                    json=json_data,
                    headers=headers,
                    timeout=config.timeout,
                    verify=config.verify_ssl,
                    auth=config.auth
                )
                
                elapsed_time = time.time() - start_time
                self.total_request_time += elapsed_time
                self.last_request_time = start_time
                self.requests_sent += 1
                
                # Parsear respuesta
                try:
                    response_data = response.json() if response.content else {}
                except json.JSONDecodeError:
                    response_data = response.text
                
                # Crear objeto de respuesta
                http_response = HTTPResponse(
                    status_code=response.status_code,
                    data=response_data,
                    headers=dict(response.headers),
                    elapsed_time=elapsed_time,
                    success=response.status_code < 400
                )
                
                # Log basado en código de estado
                if http_response.is_success():
                    self._log(f"HTTP {method.value} {url} - {response.status_code} OK ({elapsed_time:.2f}s)")
                elif http_response.is_client_error():
                    self._log(f"HTTP {method.value} {url} - Client error {response.status_code}", "warning")
                else:
                    self._log(f"HTTP {method.value} {url} - Server error {response.status_code}", "error")
                
                return http_response
                
            except requests.exceptions.Timeout as e:
                last_exception = e
                self._log(f"HTTP {method.value} {url} - Timeout (attempt {attempt + 1})", "warning")
                
            except requests.exceptions.ConnectionError as e:
                last_exception = e
                self._log(f"HTTP {method.value} {url} - Connection error (attempt {attempt + 1})", "error")
                
            except requests.exceptions.RequestException as e:
                last_exception = e
                self._log(f"HTTP {method.value} {url} - Request error: {e} (attempt {attempt + 1})", "error")
            
            except Exception as e:
                last_exception = e
                self._log(f"HTTP {method.value} {url} - Unexpected error: {e} (attempt {attempt + 1})", "error")
            
            # Esperar antes de reintentar (excepto en último intento)
            if attempt < config.max_retries - 1:
                time.sleep(config.retry_delay)
        
        # Todos los intentos fallaron
        self.requests_failed += 1
        self._log(f"HTTP {method.value} {url} - All {config.max_retries} attempts failed", "error")
        
        return HTTPResponse(
            status_code=0,
            data={"error": str(last_exception) if last_exception else "Unknown error"},
            headers={},
            elapsed_time=0.0,
            success=False
        )
    
    def get(self, endpoint: str, config: Optional[RequestConfig] = None) -> HTTPResponse:
        """
        Realiza petición GET.
        
        Args:
            endpoint: Endpoint (sin base_url)
            config: Configuración específica
            
        Returns:
            HTTPResponse
        """
        return self._make_request(HTTPMethod.GET, endpoint, config=config)
    
    def post(self, endpoint: str, data: Dict[str, Any], config: Optional[RequestConfig] = None) -> HTTPResponse:
        """
        Realiza petición POST.
        
        Args:
            endpoint: Endpoint (sin base_url)
            data: Datos a enviar
            config: Configuración específica
            
        Returns:
            HTTPResponse
        """
        return self._make_request(HTTPMethod.POST, endpoint, data=data, config=config)
    
    def put(self, endpoint: str, data: Dict[str, Any], config: Optional[RequestConfig] = None) -> HTTPResponse:
        """
        Realiza petición PUT.
        
        Args:
            endpoint: Endpoint (sin base_url)
            data: Datos a enviar
            config: Configuración específica
            
        Returns:
            HTTPResponse
        """
        return self._make_request(HTTPMethod.PUT, endpoint, data=data, config=config)
    
    def delete(self, endpoint: str, config: Optional[RequestConfig] = None) -> HTTPResponse:
        """
        Realiza petición DELETE.
        
        Args:
            endpoint: Endpoint (sin base_url)
            config: Configuración específica
            
        Returns:
            HTTPResponse
        """
        return self._make_request(HTTPMethod.DELETE, endpoint, config=config)
    
    def patch(self, endpoint: str, data: Dict[str, Any], config: Optional[RequestConfig] = None) -> HTTPResponse:
        """
        Realiza petición PATCH.
        
        Args:
            endpoint: Endpoint (sin base_url)
            data: Datos a enviar
            config: Configuración específica
            
        Returns:
            HTTPResponse
        """
        return self._make_request(HTTPMethod.PATCH, endpoint, data=data, config=config)
    
    def sync_backup(self, state_dict: Dict[str, Any], async_mode: bool = True) -> Optional[HTTPResponse]:
        """
        Sincroniza estado con backend (backup).
        
        Args:
            state_dict: Diccionario con estado completo
            async_mode: Si True, ejecuta en thread separado
            
        Returns:
            HTTPResponse si async_mode=False, None en caso contrario
        """
        def do_backup():
            """Función interna para backup."""
            response = self.post("/api/backup_state", state_dict)
            if response.is_success():
                self._log(f"[HTTPS] Backup sync successful - {response.elapsed_time:.2f}s ✅")
            else:
                self._log(f"[HTTPS] Backup sync failed: HTTP {response.status_code} 🔴", "warning")
            return response
        
        if async_mode:
            # Ejecutar en thread separado
            thread = threading.Thread(target=do_backup, daemon=True)
            thread.start()
            return None
        else:
            # Ejecutar sincrónicamente
            return do_backup()
    
    def sync_telemetry(self, 
                      ambulance_id: str, 
                      telemetry_data: Dict[str, Any],
                      async_mode: bool = True) -> Optional[HTTPResponse]:
        """
        Sincroniza telemetría de ambulancia.
        
        Args:
            ambulance_id: ID de la ambulancia
            telemetry_data: Datos de telemetría
            async_mode: Si True, ejecuta en thread separado
            
        Returns:
            HTTPResponse si async_mode=False, None en caso contrario
        """
        payload = {
            "ambulance_id": ambulance_id,
            "timestamp": time.time(),
            "telemetry": telemetry_data
        }
        
        return self.sync_backup(payload, async_mode)
    
    def report_incident(self, 
                       ambulance_id: str, 
                       incident_type: str,
                       incident_data: Dict[str, Any],
                       priority: str = "medium") -> HTTPResponse:
        """
        Reporta incidente al backend.
        
        Args:
            ambulance_id: ID de la ambulancia
            incident_type: Tipo de incidente
            incident_data: Datos del incidente
            priority: Prioridad (low, medium, high, critical)
            
        Returns:
            HTTPResponse
        """
        payload = {
            "ambulance_id": ambulance_id,
            "incident_type": incident_type,
            "incident_data": incident_data,
            "priority": priority,
            "timestamp": time.time(),
            "source": "ambulance_twin"
        }
        
        # Configuración para incidentes (timeout más corto, más retries)
        incident_config = RequestConfig(
            timeout=5.0,
            max_retries=5,
            retry_delay=1.0
        )
        
        response = self.post("/api/incidents/report", payload, config=incident_config)
        
        if response.is_success():
            self._log(f"[HTTPS] Incident reported successfully: {incident_type} for {ambulance_id} ✅")
        else:
            self._log(f"[HTTPS] Failed to report incident: HTTP {response.status_code} 🔴", "error")
        
        return response
    
    def check_health(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Verifica salud del backend.
        
        Returns:
            Tuple (is_healthy, health_info)
        """
        try:
            response = self.get("/api/health", config=RequestConfig(timeout=3.0, max_retries=1))
            
            if response.is_success():
                health_data = response.data if isinstance(response.data, dict) else {}
                return True, {
                    "status": "healthy",
                    "response_time": response.elapsed_time,
                    "data": health_data
                }
            else:
                return False, {
                    "status": "unhealthy",
                    "status_code": response.status_code,
                    "error": response.data
                }
                
        except Exception as e:
            return False, {
                "status": "unreachable",
                "error": str(e)
            }
    
    def get_configuration(self, ambulance_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene configuración para ambulancia específica.
        
        Args:
            ambulance_id: ID de la ambulancia
            
        Returns:
            Configuración o None si falla
        """
        response = self.get(f"/api/ambulances/{ambulance_id}/configuration")
        
        if response.is_success() and isinstance(response.data, dict):
            return response.data
        
        self._log(f"Failed to get configuration for {ambulance_id}", "warning")
        return None
    
    def update_configuration(self, 
                           ambulance_id: str, 
                           config_data: Dict[str, Any]) -> bool:
        """
        Actualiza configuración de ambulancia.
        
        Args:
            ambulance_id: ID de la ambulancia
            config_data: Datos de configuración
            
        Returns:
            True si la actualización fue exitosa
        """
        response = self.put(f"/api/ambulances/{ambulance_id}/configuration", config_data)
        return response.is_success()
    
    def upload_diagnostic(self, 
                         ambulance_id: str, 
                         diagnostic_data: Dict[str, Any]) -> bool:
        """
        Sube diagnóstico al backend.
        
        Args:
            ambulance_id: ID de la ambulancia
            diagnostic_data: Datos de diagnóstico
            
        Returns:
            True si la subida fue exitosa
        """
        response = self.post(f"/api/ambulances/{ambulance_id}/diagnostics", diagnostic_data)
        
        if response.is_success():
            self._log(f"Diagnostic uploaded for {ambulance_id} ✅")
            return True
        else:
            self._log(f"Failed to upload diagnostic for {ambulance_id}", "warning")
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Retorna estadísticas del handler HTTPS.
        
        Returns:
            Diccionario con estadísticas
        """
        avg_request_time = 0.0
        if self.requests_sent > 0:
            avg_request_time = self.total_request_time / self.requests_sent
        
        success_rate = 0.0
        if self.requests_sent > 0:
            success_rate = ((self.requests_sent - self.requests_failed) / self.requests_sent) * 100
        
        return {
            "base_url": self.base_url,
            "requests_sent": self.requests_sent,
            "requests_failed": self.requests_failed,
            "success_rate_percent": round(success_rate, 1),
            "average_request_time_seconds": round(avg_request_time, 3),
            "total_request_time_seconds": round(self.total_request_time, 2),
            "last_request_time": self.last_request_time,
            "session_active": hasattr(self, 'session') and self.session is not None
        }
    
    def close(self) -> None:
        """Cierra la sesión HTTP."""
        try:
            if hasattr(self, 'session') and self.session:
                self.session.close()
                self._log("HTTPS session closed")
        except Exception as e:
            logger.error(f"Error closing HTTPS session: {e}")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()