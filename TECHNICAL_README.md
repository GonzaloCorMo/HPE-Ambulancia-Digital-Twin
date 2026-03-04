# Technical Documentation - Ambulance Digital Twin Architecture

## System Overview
This project implements a distributed IoT simulation architecture of Digital Twins representing state-of-the-art ambulances. It uses multi-protocol fallback mechanisms to ensure high availability of emergency data.

## Architecture & Modules

The system is structured into four main domains:

### 1. Telemetry Engines (`telemetry/`)
These act as simulated sensors running continuously.
- `mechanical.py`: Decrements fuel/battery over time and calculates tire pressure wear. Allows fault injection (e.g., flat tire raises temperature).
- `vitals.py`: Introduces slight random fluctuations (`random.uniform`) to maintain realistic BPM/Oxygen levels, reacting dynamically to injected incidents (e.g., cardiac arrest).
- `logistics.py`: Simple trigonometry-based movement calculating latitude/longitude heading towards a destination at synthetic speeds.

### 2. Digital Twin Orchestrator (`twin/ambulance.py`)
The `AmbulanceTwin` class is a Threaded entity running a 1Hz loop (`dt = 1.0s`). At every tick, it:
1. Steps the telemetry engines.
2. Aggregates the data into a unified JSON state.
3. Defers network broadcasting to the Communication Handlers.

### 3. Communications Layer (`comms/`)
Provides three resilient tiers of communication:
- **Tier 1 (Real-time MQTT)**: Uses `paho-mqtt`. Non-blocking publish on topic `ambulance/<ID>/state`. Highly optimized for stream processing.
- **Tier 2 (Traceability HTTPS)**: Uses `requests`. Dedicated threaded POST requests carrying aggregated state slices every 10 seconds to a FastAPI central receiver server. Built for guaranteeing historical data integrity.
- **Tier 3 (Mesh UDP Broadcast)**: Uses raw Python Sockets `socket.SO_BROADCAST`. If the MQTT broker connection is lost, it broadcasts the payload directly on UDP `5005` to any `veth`/`wlan` listening peers on the local subnet to prevent data isolation.

### 4. Headquarter Server (`central/server.py`)
- Built on `FastAPI`.
- Contains a threaded `paho.mqtt` client subscribed to `ambulance/+/state` to process sub-second states.
- Exposes REST endpoints to append the bulk traceability chunks incoming from the HTTPS layer.
- Implements rudimentary algorithmic logistics analytics: Calculates relative Euclidean distances and velocity differentials between connected nodes to extrapolate "Traffic Jam" alerts.

---

## Running the Simulation

**1. Install Dependencies**
```bash
pip install -r requirements.txt
pip install amqtt
```

**2. Start the Communication Infrastructure**
We need an MQTT Broker. If you don't have Mosquitto, use the simulated python broker:
```bash
python local_broker.py
```

**3. Start the Headquarters Server**
In a new terminal:
```bash
python central/server.py
```

**4. Start the Twins**
In a new terminal:
```bash
python main.py
```

`main.py` is the main simulation runner that spawns 3 threaded digital twins. The user interface allows injecting interactive disruptive events (traffic jams, vital drops, mechanical failures) to observe how the twins and the Headquarter react in real-time.
