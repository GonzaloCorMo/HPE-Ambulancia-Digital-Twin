import time
import threading
import logging
import sys
from typing import Optional, Callable, Any, Dict, List
from twin.ambulance import AmbulanceTwin
from comms.mqtt_client import MQTTHandler
from comms.https_client import HTTPSHandler
from comms.p2p_mesh import P2PMeshHandler

logger = logging.getLogger(__name__)

def setup_logging(log_level: str = "INFO") -> None:
    """Configura el sistema de logging."""
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('ambulance_simulation.log', mode='a')
        ]
    )

def launch_ambulance(am_id: str, 
                     start_lat: float, 
                     start_lon: float, 
                     broker_url: str, 
                     log_callback: Optional[Callable[[str], None]] = None) -> AmbulanceTwin:
    """
    Despliega y configura un gemelo digital de ambulancia.
    
    Args:
        am_id: ID único de la ambulancia
        start_lat: Latitud inicial
        start_lon: Longitud inicial
        broker_url: URL del broker MQTT
        log_callback: Función callback para logging
        
    Returns:
        Instancia de AmbulanceTwin configurada
    """
    logger.info(f"Desplegando ambulancia {am_id} en ({start_lat:.4f}, {start_lon:.4f})")
    
    # Crear gemelo digital
    twin = AmbulanceTwin(am_id, log_callback=log_callback)
    
    # Configurar posición inicial
    twin.logistics.lat = start_lat
    twin.logistics.lon = start_lon
    
    # Inyectar dependencias de comunicación
    twin.mqtt_client = MQTTHandler(broker=broker_url, log_callback=log_callback)
    twin.https_client = HTTPSHandler(base_url="http://localhost:5000", log_callback=log_callback)
    twin.p2p_mesh = P2PMeshHandler(port=5005, log_callback=log_callback)
    
    # Configurar ID de ambulancia en P2P mesh
    twin.p2p_mesh.set_ambulance_id(am_id)
    
    # Encender módulos de red
    try:
        mqtt_success = twin.mqtt_client.connect()
        if not mqtt_success:
            logger.warning(f"No se pudo conectar al broker MQTT para {am_id}")
    except Exception as e:
        logger.error(f"Error conectando MQTT para {am_id}: {e}")
    
    try:
        p2p_success = twin.p2p_mesh.start()
        if not p2p_success:
            logger.warning(f"No se pudo iniciar P2P mesh para {am_id}")
    except Exception as e:
        logger.error(f"Error iniciando P2P mesh para {am_id}: {e}")
    
    # Verificar salud HTTPS
    https_healthy, health_info = twin.https_client.check_health()
    if not https_healthy:
        logger.warning(f"Backend HTTPS no disponible para {am_id}: {health_info.get('status', 'unknown')}")
    else:
        logger.info(f"Backend HTTPS disponible para {am_id}: {health_info.get('response_time', 0):.2f}s")
    
    # Arrancar simulación del gemelo
    twin.start()
    
    logger.info(f"Ambulancia {am_id} desplegada exitosamente")
    return twin

def demo_scenario() -> Dict[str, AmbulanceTwin]:
    """
    Ejecuta un escenario de demostración con múltiples ambulancias.
    
    Returns:
        Diccionario con las ambulancias desplegadas
    """
    logger.info("=== INICIANDO ESCENARIO DE DEMOSTRACIÓN ===")
    
    broker = "localhost"
    ambulances = {}
    
    # Desplegar flota
    try:
        ambulances["AMB-001"] = launch_ambulance("AMB-001", 40.4168, -3.7038, broker)
        ambulances["AMB-002"] = launch_ambulance("AMB-002", 40.4170, -3.7040, broker)
        ambulances["AMB-003"] = launch_ambulance("AMB-003", 40.4500, -3.6900, broker)
        
        logger.info(f"Flota desplegada: {len(ambulances)} ambulancias")
        
        # Configurar rutas iniciales
        ambulances["AMB-001"].logistics.set_destination(40.4800, -3.6500, destination_type="BASE")
        ambulances["AMB-002"].logistics.set_destination(40.4800, -3.6500, destination_type="BASE")
        ambulances["AMB-003"].logistics.set_destination(40.4100, -3.7000, destination_type="PATROL")
        
        # Configurar pacientes para demostración
        ambulances["AMB-001"].vitals.set_patient_info(age=45, has_patient=True)
        ambulances["AMB-001"].vitals.patient_status = "STABLE"
        
        ambulances["AMB-003"].vitals.set_patient_info(age=62, has_patient=True)
        ambulances["AMB-003"].vitals.patient_status = "SERIOUS"
        
        # Monitorear P2P
        time.sleep(2)
        for am_id, amb in ambulances.items():
            if hasattr(amb, 'p2p_mesh'):
                peers = amb.p2p_mesh.get_active_peers()
                if peers:
                    logger.info(f"{am_id} detectó {len(peers)} vecinos P2P: {list(peers.keys())}")
        
        return ambulances
        
    except Exception as e:
        logger.error(f"Error en escenario de demostración: {e}")
        raise

def interactive_control(ambulances: Dict[str, AmbulanceTwin]) -> None:
    """
    Control interactivo por consola del escenario.
    
    Args:
        ambulances: Diccionario de ambulancias activas
    """
    while True:
        print("\n" + "="*50)
        print("CENTRO DE CONTROL - GEMELOS DIGITALES DE AMBULANCIAS")
        print("="*50)
        
        # Mostrar estado de la flota
        print("\n📊 ESTADO DE LA FLOTA:")
        for am_id, amb in ambulances.items():
            status = "ACTIVA" if getattr(amb, 'running', False) else "DETENIDA"
            patient = "👤" if getattr(amb.vitals, 'has_patient', False) else "🚫"
            fuel = f"{getattr(amb.mechanical, 'fuel_level', 0):.0f}%"
            position = f"({amb.logistics.lat:.4f}, {amb.logistics.lon:.4f})"
            print(f"  {am_id}: {status} {patient} Combustible: {fuel} Posición: {position}")
        
        # Mostrar opciones
        print("\n🎮 OPCIONES DE CONTROL:")
        print("1. Inyectar atasco de tráfico (AMB-001 y AMB-002)")
        print("2. Inyectar hipoxia en paciente (AMB-003)")
        print("3. Inyectar pinchazo de neumático (AMB-001)")
        print("4. Administrar oxígeno a paciente (AMB-003)")
        print("5. Realizar mantenimiento (AMB-001)")
        print("6. Ver estadísticas de comunicaciones")
        print("7. Ver vecinos P2P de cada ambulancia")
        print("8. Ver telemetría detallada")
        print("9. Sincronizar con backend HTTPS")
        print("0. Salir y apagar simulación")
        
        try:
            cmd = input("\n📝 Comando: ").strip()
            
            if cmd == "1":
                # Atasco de tráfico
                ambulances["AMB-001"].inject_incident("logistics", "traffic_jam")
                ambulances["AMB-002"].inject_incident("logistics", "traffic_jam")
                print("✅ Atasco de tráfico inyectado en AMB-001 y AMB-002")
                
            elif cmd == "2":
                # Hipoxia
                ambulances["AMB-003"].inject_incident("vitals", "drop_oxygen")
                print("✅ Hipoxia inyectada en paciente de AMB-003")
                
            elif cmd == "3":
                # Pinchazo
                ambulances["AMB-001"].inject_incident("mechanical", "flat_tire")
                print("✅ Pinchazo de neumático inyectado en AMB-001")
                
            elif cmd == "4":
                # Administrar oxígeno
                success = ambulances["AMB-003"].administer_treatment("oxygen")
                if success:
                    print("✅ Oxígeno administrado a paciente de AMB-003")
                else:
                    print("❌ No se pudo administrar oxígeno (sin paciente o error)")
                    
            elif cmd == "5":
                # Mantenimiento
                success = ambulances["AMB-001"].perform_maintenance()
                if success:
                    print("✅ Mantenimiento realizado en AMB-001")
                else:
                    print("❌ No se pudo realizar mantenimiento")
                    
            elif cmd == "6":
                # Estadísticas de comunicaciones
                print("\n📡 ESTADÍSTICAS DE COMUNICACIONES:")
                for am_id, amb in ambulances.items():
                    print(f"\n{am_id}:")
                    
                    if hasattr(amb, 'mqtt_client'):
                        mqtt_stats = amb.mqtt_client.get_statistics()
                        print(f"  MQTT: {mqtt_stats.get('messages_sent', 0)} enviados, "
                              f"{mqtt_stats.get('messages_received', 0)} recibidos, "
                              f"Conectado: {'✅' if mqtt_stats.get('is_connected') else '❌'}")
                    
                    if hasattr(amb, 'https_client'):
                        https_stats = amb.https_client.get_statistics()
                        print(f"  HTTPS: {https_stats.get('requests_sent', 0)} peticiones, "
                              f"Tasa éxito: {https_stats.get('success_rate_percent', 0):.1f}%")
                    
                    if hasattr(amb, 'p2p_mesh'):
                        p2p_stats = amb.p2p_mesh.get_statistics()
                        print(f"  P2P: {p2p_stats.get('peers_count', 0)} vecinos, "
                              f"{p2p_stats.get('messages_sent', 0)} mensajes enviados")
                
            elif cmd == "7":
                # Vecinos P2P
                print("\n🔗 VECINOS P2P:")
                for am_id, amb in ambulances.items():
                    if hasattr(amb, 'p2p_mesh'):
                        peers = amb.p2p_mesh.get_active_peers(timeout=30.0)
                        if peers:
                            print(f"  {am_id}: {len(peers)} vecinos - {list(peers.keys())}")
                        else:
                            print(f"  {am_id}: Sin vecinos detectados")
                            
            elif cmd == "8":
                # Telemetría detallada
                print("\n📊 TELEMETRÍA DETALLADA:")
                for am_id, amb in ambulances.items():
                    if hasattr(amb, 'get_detailed_status'):
                        status = amb.get_detailed_status()
                        print(f"\n{am_id}:")
                        print(f"  Mecánico: {status.get('mechanical_status', 'N/A')}")
                        print(f"  Vitales: {status.get('vitals_status', 'N/A')}")
                        print(f"  Logística: {status.get('logistics_status', 'N/A')}")
                        print(f"  Paciente: {'Presente' if status.get('has_patient') else 'Ausente'}")
                
            elif cmd == "9":
                # Sincronizar con backend
                print("\n🔄 SINCRONIZANDO CON BACKEND HTTPS...")
                for am_id, amb in ambulances.items():
                    if hasattr(amb, 'https_client') and hasattr(amb, 'current_state'):
                        # Construir payload con estructura correcta para /api/backup_state
                        payload = {
                            "ambulance_id": am_id,
                            "timestamp": time.time(),
                            "critical_data": {
                                "position": {
                                    "lat": amb.logistics.lat,
                                    "lon": amb.logistics.lon
                                },
                                "patient_status": amb.vitals.patient_status.value if amb.vitals.has_patient else "NONE",
                                "fuel_level": amb.mechanical.fuel_level,
                                "mission_status": amb.logistics.mission_status
                            }
                        }
                        response = amb.https_client.sync_backup(payload, async_mode=False)
                        if response and response.is_success():
                            print(f"  {am_id}: ✅ Sincronización exitosa ({response.elapsed_time:.2f}s)")
                        else:
                            print(f"  {am_id}: ❌ Error en sincronización")
                            
            elif cmd == "0":
                # Salir
                print("\n🛑 Apagando simulación...")
                break
                
            else:
                print("❌ Comando no reconocido")
                
            # Pequeña pausa para ver efectos
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("\n🛑 Interrupción por usuario")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(1)

def shutdown_simulation(ambulances: Dict[str, AmbulanceTwin]) -> None:
    """
    Apaga limpiamente la simulación.
    
    Args:
        ambulances: Diccionario de ambulancias a detener
    """
    logger.info("Apagando simulación...")
    
    for am_id, amb in ambulances.items():
        try:
            # Detener gemelo
            if hasattr(amb, 'stop'):
                amb.stop()
                logger.info(f"Ambulancia {am_id} detenida")
            
            # Detener comunicaciones
            if hasattr(amb, 'mqtt_client') and amb.mqtt_client:
                amb.mqtt_client.disconnect()
            
            if hasattr(amb, 'p2p_mesh') and amb.p2p_mesh:
                amb.p2p_mesh.stop()
                
            if hasattr(amb, 'https_client') and amb.https_client:
                amb.https_client.close()
                
        except Exception as e:
            logger.error(f"Error deteniendo {am_id}: {e}")
    
    logger.info("Simulación apagada exitosamente")

def main() -> None:
    """Función principal de la simulación."""
    try:
        # Configurar logging
        setup_logging("INFO")
        
        logger.info("="*60)
        logger.info("SISTEMA DE GEMELOS DIGITALES DE AMBULANCIAS")
        logger.info("Versión 2.0 - Mejoras Completas")
        logger.info("="*60)
        
        # Ejecutar escenario de demostración
        ambulances = demo_scenario()
        
        if not ambulances:
            logger.error("No se pudo desplegar el escenario de demostración")
            return
        
        # Control interactivo
        interactive_control(ambulances)
        
        # Apagar limpiamente
        shutdown_simulation(ambulances)
        
        logger.info("Simulación finalizada exitosamente")
        
    except KeyboardInterrupt:
        logger.info("Simulación interrumpida por usuario")
        # Intentar apagar lo que se haya desplegado
        if 'ambulances' in locals():
            shutdown_simulation(ambulances)
    except Exception as e:
        logger.error(f"Error crítico en simulación: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()