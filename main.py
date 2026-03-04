import time
import threading
from twin.ambulance import AmbulanceTwin
from comms.mqtt_client import MQTTHandler
from comms.https_client import HTTPSHandler
from comms.p2p_mesh import P2PMeshHandler

# Orquestador Principal de Simulación

def launch_ambulance(am_id, start_lat, start_lon, broker_url, log_callback=None):
    twin = AmbulanceTwin(am_id, log_callback=log_callback)
    
    # Configurar posición inicial
    twin.logistics.lat = start_lat
    twin.logistics.lon = start_lon
    
    # Inyectar dependencias de comunicación
    twin.mqtt_client = MQTTHandler(broker=broker_url, log_callback=log_callback)
    twin.https_client = HTTPSHandler(base_url="http://localhost:8000")
    twin.p2p_mesh = P2PMeshHandler(port=5005, log_callback=log_callback) # Todos usan el mismo puerto UDP para broadcast
    
    # Encender módulos de red
    twin.mqtt_client.connect()
    twin.p2p_mesh.start()
    
    # Arrancar simulación del gemelo
    twin.start()
    return twin

if __name__ == "__main__":
    broker = "localhost" # Asumimos mosquitto corriendo localmente o un broker simulado
    print("Iniciando Simulación de Ambulancias...\n")
    
    amb_1 = launch_ambulance("AMB-001", 40.4168, -3.7038, broker) # Madrid Centro
    amb_2 = launch_ambulance("AMB-002", 40.4170, -3.7040, broker) # Muy cerca de AMB-1
    amb_3 = launch_ambulance("AMB-003", 40.4500, -3.6900, broker) # Más alejada
    
    # Darles un destino para que empiecen a moverse
    amb_1.logistics.set_destination(40.4800, -3.6500)
    amb_2.logistics.set_destination(40.4800, -3.6500)
    amb_3.logistics.set_destination(40.4100, -3.7000)
    
    try:
        while True:
            # Menu básico para inyectar fallos interactivo o scripts guiados
            print("\n--- Control de Mando ---")
            print("1. Inyectar tráfico (AMB-001 y AMB-002 pararán, simulando atasco)")
            print("2. Inyectar fallo de paciente (AMB-003 bajada de oxígeno)")
            print("3. Inyectar fallo mecánico (AMB-001 pinchazo)")
            print("4. Mostrar vecinos P2P detectados por AMB-001")
            print("0. Salir")
            
            cmd = input("Comando: ")
            
            if cmd == "1":
                amb_1.inject_incident("logistics", "traffic_jam")
                amb_2.inject_incident("logistics", "traffic_jam")
            elif cmd == "2":
                amb_3.inject_incident("vitals", "drop_oxygen")
            elif cmd == "3":
                amb_1.inject_incident("mechanical", "flat_tire")
            elif cmd == "4":
                peers = amb_1.p2p_mesh.get_active_peers()
                print(f"Vecinos P2P activos vistos por AMB-001: {peers}")
            elif cmd == "0":
                break
            
            time.sleep(1)

    except KeyboardInterrupt:
        pass
        
    print("Apagando simulación...")
    amb_1.stop()
    amb_2.stop()
    amb_3.stop()
    amb_1.p2p_mesh.stop()
    amb_2.p2p_mesh.stop()
    amb_3.p2p_mesh.stop()
