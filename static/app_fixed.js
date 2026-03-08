// Fixed version of app.js with better error handling and debugging
const socket = io();

// State
let simState = {
    ambulances: {},
    emergencies: {},
    pois: [],
    jams: [],
    is_simulating: false,
    speed_multiplier: 1,
    system_stats: {},
    timestamp: null,
    broadcast_id: 0
};

// Debug mode
const DEBUG = true;

// Leaflet Map Setup
const map = L.map('tactical-map').setView([40.4500, -3.6800], 13);
L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager_labels_under/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20
}).addTo(map);

// Marker References dictionaries
const markerRefs = {
    ambulances: {},
    emergencies: {},
    pois: {},
    jams: {}
};

const activeRoutes = {}; // Stores L.polyline layers for each ambulance ID
const routeCache = {};   // Stores raw GeoJSON coordinate arrays to prevent duplicate fetches

// Statistics and metrics
let statsHistory = {
    ambulancesCount: [],
    emergenciesCount: [],
    responseTimes: [],
    broadcastIds: [],
    timestamps: []
};

// Chart instances
let statsChart = null;

// Utility functions
function formatTime(date) {
    const hours = date.getHours().toString().padStart(2, '0');
    const minutes = date.getMinutes().toString().padStart(2, '0');
    const seconds = date.getSeconds().toString().padStart(2, '0');
    return `${hours}:${minutes}:${seconds}`;
}

function clearMap() {
    // Limpiar todos los marcadores
    Object.values(markerRefs.ambulances).forEach(marker => map.removeLayer(marker));
    Object.values(markerRefs.emergencies).forEach(marker => map.removeLayer(marker));
    Object.values(markerRefs.pois).forEach(marker => map.removeLayer(marker));
    Object.values(markerRefs.jams).forEach(marker => {
        map.removeLayer(marker);
        if (marker._circle) {
            map.removeLayer(marker._circle);
        }
    });
    
    // Limpiar referencias
    markerRefs.ambulances = {};
    markerRefs.emergencies = {};
    markerRefs.pois = {};
    markerRefs.jams = {};
    
    // Limpiar rutas
    Object.values(activeRoutes).forEach(route => map.removeLayer(route));
    Object.keys(activeRoutes).forEach(id => delete activeRoutes[id]);
    
    // Limpiar caché de rutas
    Object.keys(routeCache).forEach(key => delete routeCache[key]);
    
    // Limpiar referencias de destino en marcadores
    Object.values(markerRefs.ambulances).forEach(marker => {
        marker._currentDestKey = null;
        marker._routeCoords = null;
    });
    
    addTerminalLog('[MAPA] Todos los elementos del mapa eliminados.');
}

// -------------------------------------------------------------
// Drawing Logic (State sync based)
// -------------------------------------------------------------
function updateMap() {
    if (DEBUG) console.log('updateMap called, ambulances:', Object.keys(simState.ambulances).length);
    
    // 1. Ambulances
    const amIds = Object.keys(simState.ambulances);
    
    // Remove stale ones
    Object.keys(markerRefs.ambulances).forEach(id => {
        if (!amIds.includes(id)) {
            map.removeLayer(markerRefs.ambulances[id]);
            delete markerRefs.ambulances[id];
            
            // Remove associated route
            if (activeRoutes[id]) {
                map.removeLayer(activeRoutes[id]);
                delete activeRoutes[id];
            }
        }
    });
    
    // Add or update
    amIds.forEach(id => {
        const amb = simState.ambulances[id];
        if (!amb || !amb.logistics) return;
        
        const lat = amb.logistics.latitude;
        const lon = amb.logistics.longitude;
        if (!lat || !lon) return;

        const ms = amb.logistics.mission_status;
        const hasPatient = amb.vitals?.has_patient || false;
        
        let colorClass = 'marker-amb-active';
        let markerText = '🚑';
        
        if (ms === "IN_USE") {
            colorClass = 'marker-amb-in-use';
            markerText = hasPatient ? '🏥' : '🚨';
        } else if (ms === "INACTIVE") {
            colorClass = 'marker-amb-inactive';
            markerText = '🛑';
        } else if (ms === "REFUELING") {
            colorClass = 'marker-amb-refueling';
            markerText = '⛽';
        } else if (ms === "MAINTENANCE") {
            colorClass = 'marker-amb-maintenance';
            markerText = '🔧';
        }

        const html = `<div class="${colorClass} w-full h-full rounded-full flex items-center justify-center text-[10px] font-bold text-white shadow-lg">${markerText}</div>`;
        const icon = L.divIcon({ 
            className: `custom-div-icon ${colorClass}`, 
            html: html, 
            iconSize: [28, 28], 
            iconAnchor: [14, 14] 
        });

        if (!markerRefs.ambulances[id]) {
            markerRefs.ambulances[id] = L.marker([lat, lon], { icon }).addTo(map);
            markerRefs.ambulances[id].bindTooltip(
                `${id}<br>${amb.logistics.action_message || "Esperando órdenes"}`,
                { 
                    permanent: false, 
                    direction: 'right', 
                    offset: [15, 0], 
                    className: 'bg-white/90 border border-slate-300 shadow font-bold text-[10px] rounded px-1 !p-0 !m-0', 
                    opacity: 0.9 
                }
            );
            
            // Add click event for details
            markerRefs.ambulances[id].on('click', () => {
                openAmbulanceDetails(id);
            });
        } else {
            markerRefs.ambulances[id].setLatLng([lat, lon]);
            markerRefs.ambulances[id].setIcon(icon);
            
            // Update tooltip
            markerRefs.ambulances[id].setTooltipContent(
                `${id}<br>${amb.logistics.action_message || "Esperando órdenes"}`
            );
        }

        // Route visualization
        const destType = amb.logistics.destination_type;
        let showLines = false;
        let routeColor = '#94a3b8'; // Slate base

        if (destType === 'EMERGENCY') {
            showLines = document.getElementById('chk-route-em')?.checked ?? true;
            routeColor = '#ef4444'; // Red
        } else if (destType === 'HOSPITAL') {
            showLines = document.getElementById('chk-route-hosp')?.checked ?? true;
            routeColor = '#10b981'; // Green
        } else if (destType === 'GAS_STATION') {
            showLines = document.getElementById('chk-route-gas')?.checked ?? true;
            routeColor = '#f59e0b'; // Amber
        } else if (destType === 'BASE') {
            showLines = document.getElementById('chk-route-base')?.checked ?? true;
            routeColor = '#3b82f6'; // Blue
        }

        if (showLines && amb.logistics.has_destination && amb.logistics.destination_lat && amb.logistics.destination_lon) {
            const destKey = `${amb.logistics.destination_lat.toFixed(5)},${amb.logistics.destination_lon.toFixed(5)}`;
            const styleObj = { 
                color: routeColor, 
                weight: 5, 
                opacity: 0.7, 
                dashArray: '10, 10',
                className: 'route-glow' 
            };

            // Fetch geometry ONCE per exact destination
            if (markerRefs.ambulances[id]._currentDestKey !== destKey) {
                markerRefs.ambulances[id]._currentDestKey = destKey;
                markerRefs.ambulances[id]._routeCoords = null; // clear existing array

                if (activeRoutes[id]) {
                    map.removeLayer(activeRoutes[id]);
                    delete activeRoutes[id];
                }

                if (routeCache[destKey]) {
                    markerRefs.ambulances[id]._routeCoords = routeCache[destKey];
                } else {
                    fetch(`/api/route/${id}`)
                        .then(r => r.json())
                        .then(data => {
                            if (data.route && data.route.length > 0) {
                                const coords = data.route;
                                routeCache[destKey] = coords;
                                if (markerRefs.ambulances[id]._currentDestKey === destKey) {
                                    markerRefs.ambulances[id]._routeCoords = coords;
                                }
                            }
                        }).catch(e => console.error("Offline Route Error:", e));
                }
            }

            // Continuous Frame Update: Slice coordinates by `route_step` to simulate vanishing path
            if (markerRefs.ambulances[id]._routeCoords) {
                const step = amb.logistics.route_step || 0;
                let sliced = markerRefs.ambulances[id]._routeCoords.slice(step);

                if (sliced.length > 0) {
                    let latlngs = sliced.map(c => [c[0], c[1]]);
                    latlngs.unshift([lat, lon]); // Hook visually to the current ambulance position

                    if (activeRoutes[id]) {
                        activeRoutes[id].setLatLngs(latlngs);
                        activeRoutes[id].setStyle(styleObj);
                    } else {
                        activeRoutes[id] = L.polyline(latlngs, styleObj).addTo(map);
                    }
                } else if (activeRoutes[id]) {
                    map.removeLayer(activeRoutes[id]);
                    delete activeRoutes[id];
                }
            }

        } else {
            // No destination or lines disabled, remove active route for this ambulance
            if (activeRoutes[id]) {
                map.removeLayer(activeRoutes[id]);
                delete activeRoutes[id];
            }
            markerRefs.ambulances[id]._currentDestKey = null;
            markerRefs.ambulances[id]._routeCoords = null;
        }
    });

    // 2. Emergencies
    const emIds = Object.keys(simState.emergencies);
    Object.keys(markerRefs.emergencies).forEach(id => {
        if (!emIds.includes(id)) {
            map.removeLayer(markerRefs.emergencies[id]);
            delete markerRefs.emergencies[id];
        }
    });
    emIds.forEach(id => {
        const em = simState.emergencies[id];
        if (!em) return;

        let cClass = 'marker-em-initiated';
        let iconText = '🚨';
        if (em.status === 'PROCESSING') {
            cClass = 'marker-em-processing';
            iconText = '🔄';
        } else if (em.status === 'TRANSPORTING') {
            cClass = 'marker-em-transporting';
            iconText = '🏥';
        } else if (em.status === 'RESOLVED') {
            cClass = 'marker-em-resolved';
            iconText = '✅';
        } else if (em.status === 'ON_SCENE') {
            cClass = 'marker-em-onscene';
            iconText = '⚕️';
        }

        // Si la simulación está detenida, no añadir animaciones
        const animationClass = simState.is_simulating ? '' : 'no-animation';
        const icon = L.divIcon({ 
            className: `custom-div-icon ${cClass} ${animationClass} rounded-full flex items-center justify-center text-[14px] text-white shadow-lg w-full h-full`, 
            html: iconText, 
            iconSize: [24, 24], 
            iconAnchor: [12, 12] 
        });

        if (!markerRefs.emergencies[id]) {
            markerRefs.emergencies[id] = L.marker([em.lat, em.lon], { icon }).addTo(map);
            markerRefs.emergencies[id].bindTooltip(
                `🚨 Emergencia ${id}<br>Estado: ${em.status}<br>Gravedad: ${em.severity || 'MEDIUM'}`,
                { permanent: false, direction: 'top' }
            );
        } else {
            markerRefs.emergencies[id].setLatLng([em.lat, em.lon]);
            markerRefs.emergencies[id].setIcon(icon);
            markerRefs.emergencies[id].setTooltipContent(
                `🚨 Emergencia ${id}<br>Estado: ${em.status}<br>Gravedad: ${em.severity || 'MEDIUM'}`
            );
        }
    });

    // 3. POIs
    const poiKeys = simState.pois.map(p => `${p.lat},${p.lon}`);
    Object.keys(markerRefs.pois).forEach(k => {
        if (!poiKeys.includes(k)) {
            map.removeLayer(markerRefs.pois[k]);
            delete markerRefs.pois[k];
        }
    });
    simState.pois.forEach(poi => {
        const key = `${poi.lat},${poi.lon}`;
        if (!markerRefs.pois[key]) {
            const isHosp = poi.type === 'HOSPITAL';
            const cClass = isHosp ? 'marker-poi-hospital' : 'marker-poi-gas';
            const symbol = isHosp ? '🏥' : '⛽';
            const name = poi.name ? `<br>${poi.name}` : '';
            const icon = L.divIcon({ 
                className: `custom-div-icon ${cClass} flex items-center justify-center text-[14px] shadow-lg w-full h-full`, 
                html: symbol, 
                iconSize: [30, 30], 
                iconAnchor: [15, 15] 
            });
            markerRefs.pois[key] = L.marker([poi.lat, poi.lon], { icon }).addTo(map);
            markerRefs.pois[key].bindTooltip(
                `${symbol} ${isHosp ? 'Hospital' : 'Gasolinera'}${name}`,
                { permanent: false, direction: 'top' }
            );
        }
    });

    // 4. Jams
    const jamKeys = simState.jams.map(j => `${j.lat},${j.lon}`);
    Object.keys(markerRefs.jams).forEach(k => {
        if (!jamKeys.includes(k)) {
            map.removeLayer(markerRefs.jams[k]);
            delete markerRefs.jams[k];
        }
    });
    simState.jams.forEach(jam => {
        const key = `${jam.lat},${jam.lon}`;
        if (!markerRefs.jams[key]) {
            const icon = L.divIcon({ 
                className: `custom-div-icon marker-jam flex items-center justify-center text-white shadow-lg w-full h-full`, 
                html: '⚠️', 
                iconSize: [40, 40], 
                iconAnchor: [20, 20] 
            });
            markerRefs.jams[key] = L.marker([jam.lat, jam.lon], { icon }).addTo(map);
            markerRefs.jams[key].bindTooltip(
                `⚠️ Atasco<br>Causa: ${jam.cause || 'congestion'}<br>Severidad: ${(jam.severity * 100).toFixed(0)}%`,
                { permanent: false, direction: 'top' }
            );
            
            // Add circle for jam radius
            if (jam.radius) {
                const circle = L.circle([jam.lat, jam.lon], {
                    radius: jam.radius * 111320, // Convert degrees to meters (approximate)
                    color: '#ef4444',
                    fillColor: '#fecaca',
                    fillOpacity: 0.2,
                    weight: 2
                }).addTo(map);
                markerRefs.jams[key]._circle = circle;
            }
        } else if (markerRefs.jams[key]._circle && jam.radius) {
            // Update circle radius if exists
            markerRefs.jams[key]._circle.setRadius(jam.radius * 111320);
        }
    });
}

// -------------------------------------------------------------
// UI Updates & Sockets
// -------------------------------------------------------------
const fleetContainer = document.getElementById('fleet-container');
const btnPlay = document.getElementById('btn-play');
const speedLabel = document.getElementById('speed-label');
const sliderSpeed = document.getElementById('slider-speed');
const terminalLogs = document.getElementById('terminal-logs');
const connStatus = document.getElementById('connection-status');
const statsContainer = document.getElementById('stats-container');

// Add debug connection state
let connectionAttempts = 0;
let lastStateTime = null;

socket.on('connect', () => {
    connectionAttempts++;
    connStatus.innerHTML = '<span class="w-3 h-3 rounded-full bg-emerald-500 mr-2 shadow-[0_0_8px_#10B981] animate-pulse"></span> Conectado';
    connStatus.className = 'flex items-center text-sm font-semibold text-emerald-600';
    addTerminalLog(`[SISTEMA] ✅ Conectado al servidor de simulación (intento ${connectionAttempts})`);
    addTerminalLog('[SISTEMA] Esperando actualizaciones de estado...');
    
    // Request initial state
    setTimeout(() => {
        fetch('/api/health')
            .then(r => r.json())
            .then(data => {
                addTerminalLog(`[API] Estado del servidor: ${data.engine_running ? 'corriendo' : 'detenido'}, ambulancias: ${data.ambulances_count}`);
            })
            .catch(e => {
                addTerminalLog(`[ERROR] No se pudo obtener estado inicial: ${e.message}`);
            });
    }, 1000);
});

socket.on('connect_error', (error) => {
    addTerminalLog(`[ERROR] Error de conexión WebSocket: ${error.message}`);
});

socket.on('disconnect', (reason) => {
    connStatus.innerHTML = '<span class="w-3 h-3 rounded-full bg-red-500 mr-2 animate-pulse"></span> Offline';
    connStatus.className = 'flex items-center text-sm font-semibold text-red-500';
    addTerminalLog(`[SISTEMA] ❌ Desconectado del servidor: ${reason}`);
});

socket.on('log', (data) => {
    if (data.messages && Array.isArray(data.messages)) {
        data.messages.forEach(msg => {
            addTerminalLog(msg);
        });
    } else if (data.msg) {
        addTerminalLog(data.msg);
    }
});

socket.on('sim_state', (state) => {
    lastStateTime = Date.now();
    simState = state;
    
    if (DEBUG) {
        console.log('Received sim_state:', {
            ambulances: Object.keys(state.ambulances).length,
            emergencies: Object.keys(state.emergencies).length,
            is_simulating: state.is_simulating,
            broadcast_id: state.broadcast_id
        });
    }
    
    // Update statistics
    updateStatistics(state);
    
    // Update Control State
    const playBtnText = btnPlay?.textContent?.trim() || '';
    if (state.is_simulating && playBtnText !== "⏸️ PAUSAR") {
        btnPlay.textContent = "⏸️ PAUSAR";
        btnPlay.className = "flex-1 bg-amber-100 hover:bg-amber-200 text-amber-700 font-bold py-2 px-4 rounded transition border border-amber-200 shadow-sm";
    } else if (!state.is_simulating && playBtnText !== "▶️ INICIAR") {
        btnPlay.textContent = "▶️ INICIAR";
        btnPlay.className = "flex-1 bg-emerald-100 hover:bg-emerald-200 text-emerald-700 font-bold py-2 px-4 rounded transition border border-emerald-200 shadow-sm";
    }

    if (speedLabel) speedLabel.innerText = `${state.speed_multiplier}x`;
    if (sliderSpeed) sliderSpeed.value = state.speed_multiplier;

    updateFleetUI();
    updateMap();
    updateEmergenciesUI();
    
    // Update timestamp if available
    if (state.timestamp) {
        const timeEl = document.getElementById('current-time');
        if (timeEl) {
            try {
                const date = new Date(state.timestamp);
                timeEl.textContent = date.toLocaleTimeString('es-ES');
            } catch (e) {
                // Ignore date parsing errors
            }
        }
    }
    
    // Hide loading overlay if it's visible
    const loadingOverlay = document.getElementById('loading-overlay');
    if (loadingOverlay && !loadingOverlay.classList.contains('hidden')) {
        setTimeout(() => {
            loadingOverlay.classList.add('hidden');
        }, 500);
    }
});

// Monitor for state updates
setInterval(() => {
    if (lastStateTime && Date.now() - lastStateTime > 10000) {
        // No state updates for 10 seconds
        if (connStatus.textContent.includes('Conectado')) {
            addTerminalLog('[ADVERTENCIA] No se han recibido actualizaciones de estado en 10 segundos');
        }
    }
}, 10000);

function addTerminalLog(message) {
    if (!terminalLogs) return;
    
    const t = formatTime(new Date());
    terminalLogs.textContent += `[${t}] ${message}\n`;
    terminalLogs.scrollTop = terminalLogs.scrollHeight;

    // Prevent giant memory consumption
    if (terminalLogs.textContent.length > 10000) {
        terminalLogs.textContent = terminalLogs.textContent.substring(5000);
    }
}

function updateAllStats(state) {
    const stats = state.system_stats || {};
    
    // Update header stats
    const statsAmbulancesEl = document.getElementById('stats-ambulances');
    const statsEmergenciesEl = document.getElementById('stats-emergencies');
    const statsResolvedEl = document.getElementById('stats-resolved');
    
    if (statsAmbulancesEl) statsAmbulancesEl.textContent = Object.keys(state.ambulances).length;
    if (statsEmergenciesEl) statsEmergenciesEl.textContent = Object.keys(state.emergencies).length;
    if (statsResolvedEl) statsResolvedEl.textContent = stats.emergencies_handled || 0;
    
    // Update side panel stats
    const statNetworksEl = document.getElementById('stat-networks');
    const statResponseTimeEl = document.getElementById('stat-response-time');
    const statHealthEl = document.getElementById('stat-health');
    const healthBarEl = document.getElementById('health-bar');
    
    if (statNetworksEl) {
        const networkStatus = stats.network_status || { mqtt: false, p2p: false, http: false };
        const activeNetworks = [networkStatus.mqtt, networkStatus.p2p, networkStatus.http].filter(Boolean).length;
        statNetworksEl.textContent = `${activeNetworks}/3`;
        
        // Update network checkboxes to match actual status
        const mqttCheckbox = document.getElementById('chk-mqtt');
        const p2pCheckbox = document.getElementById('chk-p2p');
        const httpCheckbox = document.getElementById('chk-http');
        
        if (mqttCheckbox && mqttCheckbox.checked !== networkStatus.mqtt) {
            mqttCheckbox.checked = networkStatus.mqtt;
        }
        if (p2pCheckbox && p2pCheckbox.checked !== networkStatus.p2p) {
            p2pCheckbox.checked = networkStatus.p2p;
        }
        if (httpCheckbox && httpCheckbox.checked !== networkStatus.http) {
            httpCheckbox.checked = networkStatus.http;
        }
        
        // Update network indicator colors - corrected selectors with better error handling
        const mqttIndicator = document.querySelector('#chk-mqtt')?.closest('label')?.querySelector('.w-3.h-3');
        const p2pIndicator = document.querySelector('#chk-p2p')?.closest('label')?.querySelector('.w-3.h-3');
        const httpIndicator = document.querySelector('#chk-http')?.closest('label')?.querySelector('.w-3.h-3');
        
        if (DEBUG) console.log('Network indicators found:', { mqtt: !!mqttIndicator, p2p: !!p2pIndicator, http: !!httpIndicator });
        
        if (mqttIndicator) {
            mqttIndicator.className = `w-3 h-3 rounded-full ${networkStatus.mqtt ? 'bg-emerald-500' : 'bg-red-500'}`;
        } else if (DEBUG) console.warn('MQTT indicator not found');
        if (p2pIndicator) {
            p2pIndicator.className = `w-3 h-3 rounded-full ${networkStatus.p2p ? 'bg-blue-500' : 'bg-red-500'}`;
        } else if (DEBUG) console.warn('P2P indicator not found');
        if (httpIndicator) {
            httpIndicator.className = `w-3 h-3 rounded-full ${networkStatus.http ? 'bg-purple-500' : 'bg-red-500'}`;
        } else if (DEBUG) console.warn('HTTP indicator not found');
        
        // Debug log
        if (DEBUG) console.log('Network status updated:', networkStatus);
    }
    
    if (statResponseTimeEl) statResponseTimeEl.textContent = `${stats.average_response_time_min || '0.0'} min`;
    if (statHealthEl) statHealthEl.textContent = '100%';
    if (healthBarEl) healthBarEl.style.width = '100%';
    
    // Update fleet stats
    const fleetCountEl = document.getElementById('fleet-count');
    const fleetActiveEl = document.getElementById('fleet-active');
    const fleetInUseEl = document.getElementById('fleet-in-use');
    const fleetTotalEl = document.getElementById('fleet-total');
    
    if (fleetCountEl) fleetCountEl.textContent = Object.keys(state.ambulances).length;
    
    let activeCount = 0;
    let inUseCount = 0;
    
    Object.values(state.ambulances).forEach(amb => {
        const ms = amb.logistics?.mission_status;
        if (ms === "ACTIVE" || ms === "INACTIVE") activeCount++;
        if (ms === "IN_USE") inUseCount++;
    });
    
    if (fleetActiveEl) fleetActiveEl.textContent = activeCount;
    if (fleetInUseEl) fleetInUseEl.textContent = inUseCount;
    if (fleetTotalEl) fleetTotalEl.textContent = Object.keys(state.ambulances).length;
    
    // Update simulation status
    const simStatusEl = document.getElementById('sim-status');
    if (simStatusEl) {
        if (state.is_simulating) {
            simStatusEl.textContent = "EJECUTANDO";
            simStatusEl.className = "text-xs font-bold px-2 py-1 rounded bg-emerald-100 text-emerald-700";
        } else {
            simStatusEl.textContent = "DETENIDA";
            simStatusEl.className = "text-xs font-bold px-2 py-1 rounded bg-slate-200 text-slate-700";
        }
    }
    
    // Update emergencies count
    const emergenciesCountEl = document.getElementById('emergencies-count');
    if (emergenciesCountEl) emergenciesCountEl.textContent = Object.keys(state.emergencies).length;
}

function updateStatistics(state) {
    // Store history for charts
    const now = Date.now();
    statsHistory.ambulancesCount.push({ x: now, y: Object.keys(state.ambulances).length });
    statsHistory.emergenciesCount.push({ x: now, y: Object.keys(state.emergencies).length });
    statsHistory.broadcastIds.push({ x: now, y: state.broadcast_id || 0 });
    statsHistory.timestamps.push(now);
    
    // Keep only last 100 data points
    const maxHistory = 100;
    if (statsHistory.ambulancesCount.length > maxHistory) {
        statsHistory.ambulancesCount.shift();
        statsHistory.emergenciesCount.shift();
        statsHistory.broadcastIds.shift();
        statsHistory.timestamps.shift();
    }
    
    // Update all stats UI
    updateAllStats(state);
    
    // Update stats display if container exists
    if (statsContainer) {
        const stats = state.system_stats || {};
        statsContainer.innerHTML = `
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div class="bg-white p-3 rounded-lg border border-slate-200 shadow-sm">
                    <div class="text-sm text-slate-500">Ambulancias</div>
                    <div class="text-2xl font-bold text-blue-600">${Object.keys(state.ambulances).length}</div>
                </div>
                <div class="bg-white p-3 rounded-lg border border-slate-200 shadow-sm">
                    <div class="text-sm text-slate-500">Emergencias</div>
                    <div class="text-2xl font-bold text-red-600">${Object.keys(state.emergencies).length}</div>
                </div>
                <div class="bg-white p-3 rounded-lg border border-slate-200 shadow-sm">
                    <div class="text-sm text-slate-500">Tiempo Respuesta</div>
                    <div class="text-2xl font-bold text-emerald-600">${stats.average_response_time_min || '0.0'} min</div>
                </div>
                <div class="bg-white p-3 rounded-lg border border-slate-200 shadow-sm">
                    <div class="text-sm text-slate-500">Resueltas</div>
                    <div class="text-2xl font-bold text-purple-600">${stats.emergencies_handled || 0}</div>
                </div>
            </div>
        `;
    }
    
    // Update charts if initialized
    if (statsChart) {
        statsChart.update();
    }
}

function updateFleetUI() {
    if (!fleetContainer) {
        if (DEBUG) console.error('fleetContainer not found!');
        return;
    }
    
    if (DEBUG) console.log('updateFleetUI called with ambulances:', Object.keys(simState.ambulances));
    
    // Collect existing keys to remove dead ones, and add/update others
    const currentDomIds = Array.from(fleetContainer.children)
        .map(c => c.dataset.amId)
        .filter(id => id); // Filter out undefined
    
    const stateAmIds = Object.keys(simState.ambulances);
    
    if (DEBUG) console.log('Current DOM IDs:', currentDomIds, 'State ambulance IDs:', stateAmIds);

    // Remove placeholder div (no data-am-id) if there are ambulances to show
    if (stateAmIds.length > 0) {
        Array.from(fleetContainer.children).forEach(child => {
            if (!child.dataset.amId) child.remove();
        });
    }

    // Remove deleted
    currentDomIds.filter(id => !stateAmIds.includes(id)).forEach(id => {
        const el = document.getElementById(`card-${id}`);
        if (el) {
            if (DEBUG) console.log('Removing ambulance card:', id);
            el.remove();
        }
    });

    // Add or Update
    stateAmIds.forEach(amId => {
        const amb = simState.ambulances[amId];
        if (!amb) {
            if (DEBUG) console.warn('Ambulance data missing for:', amId);
            return;
        }
        
        const v = amb.vitals || {};
        const m = amb.mechanical || {};
        const l = amb.logistics || {};
        
        if (DEBUG) console.log('Processing ambulance:', amId, 'logistics:', l);

        const ms = l.mission_status || "ACTIVE";
        const hasPatient = v.has_patient || false;
        
        let colorTitle = 'text-emerald-500';
        let statusBadge = '🟢 ACTIVA';
        
        if (ms === "IN_USE") {
            colorTitle = 'text-blue-500';
            statusBadge = hasPatient ? '🏥 TRANSPORTE' : '🚨 EN CAMINO';
        } else if (ms === "INACTIVE") {
            colorTitle = 'text-slate-500';
            statusBadge = '🛑 INACTIVA';
        } else if (ms === "REFUELING") {
            colorTitle = 'text-amber-500';
            statusBadge = '⛽ REPOSTANDO';
        } else if (ms === "MAINTENANCE") {
            colorTitle = 'text-red-500';
            statusBadge = '🔧 MANTENIMIENTO';
        }
        
        if (DEBUG) console.log(`Ambulance ${amId}: mission_status=${ms}, colorTitle=${colorTitle}`);

        let card = document.getElementById(`card-${amId}`);
        if (!card) {
            // Create
            card = document.createElement('div');
            card.id = `card-${amId}`;
            card.dataset.amId = amId;
            card.className = "p-3 rounded-lg border cursor-pointer hover:shadow-md transition-shadow bg-white border-slate-200 hover:border-blue-300";

            card.innerHTML = `
                <div class="flex items-center justify-between mb-2">
                    <span class="font-bold cursor-pointer hover:underline text-lg uppercase title-tag ${colorTitle}">🚑 ${amId}</span>
                    <span class="text-xs font-bold px-2 py-1 rounded-full ${colorTitle.replace('text-', 'bg-').replace('500', '100')} ${colorTitle}">${statusBadge}</span>
                </div>
                <div class="grid grid-cols-2 gap-x-2 gap-y-1 text-xs">
                    <div class="text-blue-600 truncate tag-vit">
                        <span class="font-semibold">Paciente:</span> ${hasPatient ? 'CRÍTICO' : 'NO'}
                    </div>
                    <div class="text-emerald-600 truncate tag-mech">
                        <span class="font-semibold">Combustible:</span> ${m.fuel_level || 0}%
                    </div>
                    <div class="text-purple-600 truncate tag-log">
                        <span class="font-semibold">Velocidad:</span> ${Math.round(l.speed || 0)} km/h
                    </div>
                    <div class="text-amber-600 truncate tag-net">
                        <span class="font-semibold">Destino:</span> ${l.destination_type || 'NONE'}
                    </div>
                </div>
                <div class="mt-2 text-xs text-slate-500 truncate">
                    ${l.action_message || "Esperando órdenes"}
                </div>
            `;
            
            // Modal hooking: open full telemetry modal on card/title click
            const titleEl = card.querySelector('.title-tag');
            if (titleEl) {
                titleEl.addEventListener('click', (e) => {
                    e.preventDefault();
                    openTelemetryModal(amId);
                });
            }
            
            // Card click for full telemetry
            card.addEventListener('click', (e) => {
                if (!e.target.closest('.title-tag')) {
                    openTelemetryModal(amId);
                }
            });
            
            fleetContainer.appendChild(card);
        } else {
            // Update Title color and status
            const titleEl = card.querySelector('.title-tag');
            if (titleEl) {
                titleEl.className = `font-bold cursor-pointer hover:underline text-lg uppercase title-tag ${colorTitle}`;
            }
            
            // Update status badge
            const statusEl = card.querySelector('.text-xs.font-bold');
            if (statusEl) {
                statusEl.textContent = statusBadge;
                statusEl.className = `text-xs font-bold px-2 py-1 rounded-full ${colorTitle.replace('text-', 'bg-').replace('500', '100')} ${colorTitle}`;
            }

            // Update strings
            const tagVit = card.querySelector('.tag-vit');
            const tagMech = card.querySelector('.tag-mech');
            const tagLog = card.querySelector('.tag-log');
            const tagNet = card.querySelector('.tag-net');
            
            if (tagVit) tagVit.innerHTML = `<span class="font-semibold">Paciente:</span> ${hasPatient ? 'CRÍTICO' : 'NO'}`;
            if (tagMech) tagMech.innerHTML = `<span class="font-semibold">Combustible:</span> ${m.fuel_level || 0}%`;
            if (tagLog) tagLog.innerHTML = `<span class="font-semibold">Velocidad:</span> ${Math.round(l.speed || 0)} km/h`;
            if (tagNet) tagNet.innerHTML = `<span class="font-semibold">Destino:</span> ${l.destination_type || 'NONE'}`;
            
            // Update action message
            const actionEl = card.querySelector('.mt-2.text-xs.text-slate-500');
            if (actionEl) {
                actionEl.textContent = l.action_message || "Esperando órdenes";
            }
        }
    });
    
    // Show placeholder if no ambulances
    if (stateAmIds.length === 0 && fleetContainer.children.length === 0) {
        fleetContainer.innerHTML = `
            <div class="text-center py-10 text-slate-400">
                <i class="fas fa-ambulance text-3xl mb-3"></i>
                <p class="text-sm font-medium">No hay ambulancias desplegadas</p>
                <p class="text-xs mt-1">Haz clic en el mapa para añadir una</p>
            </div>
        `;
    }
}

function updateEmergenciesUI() {
    const container = document.getElementById('emergencies-container');
    if (!container) return;
    
    const emergencies = simState.emergencies;
    const emergencyIds = Object.keys(emergencies);
    
    // Si no hay emergencias, mostrar mensaje de placeholder
    if (emergencyIds.length === 0) {
        container.innerHTML = `
            <div class="text-center py-10 text-slate-400">
                <i class="fas fa-exclamation-circle text-3xl mb-3"></i>
                <p class="text-sm font-medium">No hay urgencias activas</p>
                <p class="text-xs mt-1">Crea una urgencia en el mapa</p>
            </div>
        `;
        return;
    }
    
    // Ordenar por tiempo de creación (más recientes primero)
    const sortedEmergencies = emergencyIds.sort((a, b) => {
        return (emergencies[b].created_at || 0) - (emergencies[a].created_at || 0);
    });
    
    let html = '';
    
    sortedEmergencies.forEach(emId => {
        const em = emergencies[emId];
        
        // Determinar color según severidad
        let severityColor = 'bg-red-100 text-red-700';
        let severityIcon = '🚨';
        if (em.severity === 'LOW') {
            severityColor = 'bg-amber-100 text-amber-700';
            severityIcon = '⚠️';
        } else if (em.severity === 'MEDIUM') {
            severityColor = 'bg-orange-100 text-orange-700';
            severityIcon = '🚨';
        } else if (em.severity === 'HIGH') {
            severityColor = 'bg-red-100 text-red-700';
            severityIcon = '🔥';
        } else if (em.severity === 'CRITICAL') {
            severityColor = 'bg-purple-100 text-purple-700';
            severityIcon = '💀';
        }
        
        // Determinar estado
        let statusText = em.status || 'INITIATED';
        let statusColor = 'bg-slate-100 text-slate-700';
        if (em.status === 'PROCESSING') {
            statusColor = 'bg-blue-100 text-blue-700';
        } else if (em.status === 'TRANSPORTING') {
            statusColor = 'bg-emerald-100 text-emerald-700';
        } else if (em.status === 'RESOLVED') {
            statusColor = 'bg-green-100 text-green-700';
        } else if (em.status === 'ON_SCENE') {
            statusColor = 'bg-purple-100 text-purple-700';
        }
        
        // Calcular tiempo transcurrido
        const elapsedTime = em.created_at ? Math.floor((Date.now()/1000 - em.created_at) / 60) : 0;
        const elapsedText = elapsedTime > 0 ? `${elapsedTime} min` : 'Reciente';
        
        html += `
            <div class="bg-white rounded-lg border border-slate-200 p-3 hover:shadow-sm transition-shadow" data-em-id="${emId}">
                <div class="flex justify-between items-start mb-2">
                    <div>
                        <div class="flex items-center space-x-2">
                            <span class="text-lg">${severityIcon}</span>
                            <span class="font-bold text-slate-800">Urgencia ${emId.substring(0, 8)}</span>
                        </div>
                        <div class="text-xs text-slate-500 mt-1">
                            <i class="fas fa-clock mr-1"></i> ${elapsedText} | 
                            <i class="fas fa-map-marker-alt ml-2 mr-1"></i> ${em.lat?.toFixed(4)}, ${em.lon?.toFixed(4)}
                        </div>
                    </div>
                    <div>
                        <span class="text-xs font-bold px-2 py-1 rounded-full ${severityColor}">${em.severity || 'MEDIUM'}</span>
                        <span class="text-xs font-bold px-2 py-1 rounded-full ${statusColor} mt-1 block">${statusText}</span>
                    </div>
                </div>
                ${em.assigned_ambulance ? `
                <div class="text-xs text-slate-600 mt-2">
                    <i class="fas fa-ambulance mr-1"></i> Asignada: ${em.assigned_ambulance}
                </div>
                ` : ''}
                <div class="text-xs text-slate-500 mt-2 flex justify-between">
                    <span>ID: ${emId}</span>
                    <button class="text-blue-600 hover:text-blue-800 font-medium" onclick="focusEmergency('${emId}')">
                        <i class="fas fa-search-location mr-1"></i> Ver en mapa
                    </button>
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
}

function focusEmergency(emergencyId) {
    const em = simState.emergencies[emergencyId];
    if (em && em.lat && em.lon) {
        map.flyTo([em.lat, em.lon], 16, { duration: 1 });
        addTerminalLog(`[MAPA] Centrando en urgencia ${emergencyId.substring(0, 8)}`);
        
        // Resaltar marcador si existe
        if (markerRefs.emergencies[emergencyId]) {
            markerRefs.emergencies[emergencyId].openPopup();
            // Animación temporal
            const marker = markerRefs.emergencies[emergencyId];
            const originalIcon = marker.getIcon();
            const pulseIcon = L.divIcon({
                ...originalIcon.options,
                className: originalIcon.options.className + ' animate-pulse border-4 border-yellow-400'
            });
            marker.setIcon(pulseIcon);
            setTimeout(() => marker.setIcon(originalIcon), 2000);
        }
    }
}

// -------------------------------------------------------------
// Controls & API REST Calls
// -------------------------------------------------------------
function postJson(url, data) {
    if (DEBUG) console.log(`POST ${url}:`, data);
    return fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
    })
    .then(response => {
        if (DEBUG) console.log(`Response status from ${url}:`, response.status);
        return response.json();
    })
    .then(json => {
        if (DEBUG) console.log(`Response data from ${url}:`, json);
        return json;
    })
    .catch(e => {
        console.error(`Error on ${url}:`, e);
        addTerminalLog(`[ERROR] Fallo en petición a ${url}: ${e.message}`);
        return { error: e.message };
    });
}

if (btnPlay) {
    btnPlay.addEventListener('click', () => { 
        postJson('/api/control/toggle', {}); 
        addTerminalLog('[CONTROL] Alternando estado de simulación...');
    });
}

const btnClear = document.getElementById('btn-clear');
if (btnClear) {
    btnClear.addEventListener('click', () => { 
        if (confirm('¿Estás seguro de que quieres limpiar todo el escenario? Esto eliminará todas las ambulancias, emergencias y POIs.')) {
            postJson('/api/control/clear', {}); 
            addTerminalLog('[CONTROL] Limpiando escenario...');
        }
    });
}

const btnAutoSim = document.getElementById('btn-auto-sim');
if (btnAutoSim) {
    btnAutoSim.addEventListener('click', () => {
        if (!confirm('¿Iniciar simulación autónoma?\n\nSe generarán emergencias y atascos de forma automática.\nRequiere que haya un preset cargado con hospitales y ambulancias.\n\nSi no has cargado un escenario, selecciona un preset primero.')) return;
        btnAutoSim.disabled = true;
        btnAutoSim.textContent = '⏳ Iniciando...';
        addTerminalLog('[AUTO-SIM] Solicitando simulación autónoma al servidor...');
        postJson('/api/auto_simulation', {})
            .then(data => {
                if (data.status === 'started') {
                    addTerminalLog('[AUTO-SIM] 🤖 Simulación autónoma iniciada.');
                    if (data.message) addTerminalLog(`[AUTO-SIM] ${data.message}`);
                } else if (data.status === 'error') {
                    addTerminalLog(`[AUTO-SIM] ⚠️ ${data.message}`);
                }
            })
            .catch(e => {
                addTerminalLog(`[ERROR] No se pudo iniciar la simulación autónoma: ${e.message}`);
            })
            .finally(() => {
                btnAutoSim.disabled = false;
                btnAutoSim.innerHTML = '<i class="fas fa-robot"></i><span>🤖 SIMULACIÓN AUTÓNOMA</span>';
            });
    });
}

// Preset multi-select state
const selectedPresets = new Set();

function updatePresetDropdownLabel() {
    const label = document.getElementById('preset-dropdown-label');
    const badge = document.getElementById('preset-count-badge');
    if (!label) return;
    if (selectedPresets.size === 0) {
        label.textContent = '-- Seleccionar Presets --';
        badge?.classList.add('hidden');
    } else if (selectedPresets.size === 1) {
        const key = [...selectedPresets][0];
        const opt = document.querySelector(`#preset-dropdown-panel [data-key="${key}"] span.preset-name`);
        label.textContent = opt ? opt.textContent : key;
        badge?.classList.add('hidden');
    } else {
        label.textContent = `${selectedPresets.size} presets seleccionados`;
        if (badge) { badge.textContent = selectedPresets.size; badge.classList.remove('hidden'); }
    }
}

// Preset loader
const btnLoadPreset = document.getElementById('btn-load-preset');
if (btnLoadPreset) {
    btnLoadPreset.addEventListener('click', () => {
        if (selectedPresets.size === 0) {
            addTerminalLog('[SISTEMA] Selecciona al menos un preset del desplegable.');
            return;
        }
        const names = [...selectedPresets];
        const namesStr = names.join(', ');
        if (!confirm(`¿Cargar preset(s): "${namesStr}"?\n\nSe limpiará el escenario actual y se cargará la infraestructura seleccionada.`)) return;
        btnLoadPreset.disabled = true;
        addTerminalLog(`[PRESET] Cargando presets: ${namesStr}...`);
        const payload = names.length === 1
            ? { name: names[0] }
            : { names, clear_first: true };
        const url = names.length === 1 ? '/api/preset' : '/api/presets/load_multi';
        postJson(url, payload)
            .then(data => {
                if (data.status === 'loaded') {
                    addTerminalLog(`[PRESET] ✅ ${data.message}`);
                    if (data.ambulances) addTerminalLog(`[PRESET] ${data.ambulances} ambulancias desplegadas.`);
                }
            })
            .catch(e => addTerminalLog(`[ERROR] No se pudo cargar el preset: ${e.message}`))
            .finally(() => { btnLoadPreset.disabled = false; });
    });
}

if (sliderSpeed) {
    sliderSpeed.addEventListener('input', (e) => {
        postJson('/api/control/speed', { multiplier: parseInt(e.target.value) });
        addTerminalLog(`[CONTROL] Velocidad ajustada a ${e.target.value}x`);
    });
}

// Severity (event frequency) slider
const sliderSeverity = document.getElementById('slider-severity');
const severityLabel = document.getElementById('severity-label');
if (sliderSeverity) {
    // Convert slider integer 1-50 to float multiplier 0.1-5.0
    function sliderToSeverity(v) { return Math.round(v / 10 * 10) / 10; }
    sliderSeverity.addEventListener('input', (e) => {
        const mult = sliderToSeverity(parseInt(e.target.value));
        if (severityLabel) severityLabel.textContent = `${mult.toFixed(1)}x`;
        postJson('/api/control/severity', { multiplier: mult })
            .then(() => addTerminalLog(`[CONTROL] Severidad de eventos ajustada a ${mult.toFixed(1)}x`));
    });
    // Set initial label
    const initMult = sliderToSeverity(parseInt(sliderSeverity.value));
    if (severityLabel) severityLabel.textContent = `${initMult.toFixed(1)}x`;
}

// Network toggles
['chk-mqtt', 'chk-p2p', 'chk-http'].forEach(id => {
    const element = document.getElementById(id);
    if (element) {
        element.addEventListener('change', () => {
            const mqttEnabled = document.getElementById('chk-mqtt')?.checked ?? true;
            const p2pEnabled = document.getElementById('chk-p2p')?.checked ?? true;
            const httpEnabled = document.getElementById('chk-http')?.checked ?? true;
            
            postJson('/api/network', {
                mqtt: mqttEnabled,
                p2p: p2pEnabled,
                http: httpEnabled
            });
            
            addTerminalLog(`[RED] Configuración actualizada: MQTT=${mqttEnabled ? 'ON' : 'OFF'}, P2P=${p2pEnabled ? 'ON' : 'OFF'}, HTTP=${httpEnabled ? 'ON' : 'OFF'}`);
        });
    }
});

// Route toggles
['chk-route-em', 'chk-route-hosp', 'chk-route-gas', 'chk-route-base'].forEach(id => {
    const element = document.getElementById(id);
    if (element) {
        element.addEventListener('change', () => {
            addTerminalLog(`[VISUAL] Rutas ${id.split('-')[2]} ${element.checked ? 'activadas' : 'desactivadas'}`);
        });
    }
});

// -------------------------------------------------------------
// Mouse Canvas Interaction
// -------------------------------------------------------------
function getDrawMode() {
    const selected = document.querySelector('input[name="drawMode"]:checked');
    return selected ? selected.value : 'PAN';
}

// Visual radio selector logic
document.querySelectorAll('input[name="drawMode"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
        document.querySelectorAll('.radio-mode').forEach(lbl => lbl.classList.remove('active', 'bg-blue-100', 'text-blue-700'));
        e.target.parentElement.classList.add('active', 'bg-blue-100', 'text-blue-700');
        
        // Update map cursor
        const mapDiv = document.getElementById('tactical-map');
        if (mapDiv) {
            if (e.target.value === 'PAN') {
                mapDiv.style.cursor = 'grab';
            } else {
                mapDiv.style.cursor = 'crosshair';
            }
        }
        
        addTerminalLog(`[MODO] Cambiado a modo: ${e.target.value}`);
    });
});

map.on('click', function (e) {
    if (getDrawMode() === 'PAN') return;
    
    const mode = getDrawMode();
    let payload = { type: mode, lat: e.latlng.lat, lon: e.latlng.lng };
    
    // Add extra data based on mode
    if (mode === 'EMERGENCY') {
        const severity = prompt('Gravedad de emergencia (LOW, MEDIUM, HIGH, CRITICAL):', 'MEDIUM');
        if (severity) payload.severity = severity.toUpperCase();
    } else if (mode === 'HOSPITAL' || mode === 'GAS_STATION') {
        const name = prompt('Nombre del POI (opcional):', '');
        if (name) payload.name = name;
    } else if (mode === 'JAM') {
        const radius = prompt('Radio del atasco (en grados, default 0.005):', '0.005');
        if (radius) payload.radius = parseFloat(radius);
    }
    
    postJson('/api/spawn', payload);
    addTerminalLog(`[CREACIÓN] ${mode} creado en (${e.latlng.lat.toFixed(4)}, ${e.latlng.lng.toFixed(4)})`);
});

map.on('contextmenu', function (e) {
    // Right-click always attempts deletion regardless of current draw mode
    e.originalEvent.preventDefault();
    
    postJson('/api/delete', { lat: e.latlng.lat, lon: e.latlng.lng })
        .then(data => {
            if (data.status === 'deleted') {
                addTerminalLog(`[ELIMINACIÓN] ${data.type} eliminado cerca de (${e.latlng.lat.toFixed(4)}, ${e.latlng.lng.toFixed(4)})`);
            } else {
                addTerminalLog(`[MAPA] No se encontró entidad en (${e.latlng.lat.toFixed(4)}, ${e.latlng.lng.toFixed(4)})`);
            }
        })
        .catch(err => addTerminalLog(`[ERROR] Fallo al eliminar: ${err.message}`));
    return false;
});

// City Search Logic
const btnSearchCity = document.getElementById('btn-search-city');
const inputCitySearch = document.getElementById('city-search');

if (btnSearchCity && inputCitySearch) {
    btnSearchCity.addEventListener('click', () => {
        const city = inputCitySearch.value.trim();
        if (!city) return;

        fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(city)}`)
            .then(r => r.json())
            .then(data => {
                if (data && data.length > 0) {
                    const lat = parseFloat(data[0].lat);
                    const lon = parseFloat(data[0].lon);
                    map.flyTo([lat, lon], 13, { duration: 1.5 });
                    addTerminalLog(`[MAPA] Navegando a: ${city} (${lat.toFixed(4)}, ${lon.toFixed(4)})`);
                } else {
                    addTerminalLog(`[MAPA] Ciudad no encontrada: ${city}`);
                }
            })
            .catch(e => {
                console.error("Nominatim Search Error:", e);
                addTerminalLog(`[ERROR] Búsqueda de ciudad fallida: ${e.message}`);
            });
    });

    inputCitySearch.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') btnSearchCity.click();
    });
}

// -------------------------------------------------------------
// Ambulance Details Modal
// -------------------------------------------------------------
const ambulanceModal = document.getElementById('ambulance-modal');
const ambulanceModalTitle = document.getElementById('ambulance-modal-title');
const ambulanceModalContent = document.getElementById('ambulance-modal-content');

function openAmbulanceDetails(ambulanceId) {
    if (!ambulanceId || !simState.ambulances[ambulanceId]) {
        addTerminalLog(`[ERROR] Ambulancia ${ambulanceId} no encontrada`);
        return;
    }
    
    const amb = simState.ambulances[ambulanceId];
    const v = amb.vitals || {};
    const m = amb.mechanical || {};
    const l = amb.logistics || {};
    
    ambulanceModalTitle.textContent = `🚑 ${ambulanceId} - Detalles`;
    
    // Create detailed content
    let content = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="bg-slate-50 p-4 rounded-lg">
                <h4 class="font-bold text-blue-600 mb-2">📊 Estado General</h4>
                <div class="space-y-1 text-sm">
                    <div><span class="font-semibold">Estado Misión:</span> <span class="px-2 py-1 rounded bg-blue-100 text-blue-700 text-xs">${l.mission_status || 'ACTIVE'}</span></div>
                    <div><span class="font-semibold">Mensaje:</span> ${l.action_message || 'Esperando órdenes'}</div>
                    <div><span class="font-semibold">Posición:</span> ${l.latitude?.toFixed(4) || 'N/A'}, ${l.longitude?.toFixed(4) || 'N/A'}</div>
                    <div><span class="font-semibold">Velocidad:</span> ${Math.round(l.speed || 0)} km/h</div>
                    <div><span class="font-semibold">Dirección:</span> ${Math.round(l.heading || 0)}°</div>
                </div>
            </div>
            
            <div class="bg-slate-50 p-4 rounded-lg">
                <h4 class="font-bold text-red-600 mb-2">❤️ Constantes Vitales</h4>
                <div class="space-y-1 text-sm">
                    <div><span class="font-semibold">Paciente:</span> ${v.has_patient ? 'PRESENTE' : 'AUSENTE'}</div>
                    <div><span class="font-semibold">Estado:</span> ${v.patient_status || 'ESTABLE'}</div>
                    <div><span class="font-semibold">Ritmo Cardiaco:</span> ${v.heart_rate || 0} bpm</div>
                    <div><span class="font-semibold">Oxígeno:</span> ${v.oxygen_level || 0}%</div>
                    <div><span class="font-semibold">Temperatura:</span> ${v.body_temperature || 0}°C</div>
                </div>
            </div>
            
            <div class="bg-slate-50 p-4 rounded-lg">
                <h4 class="font-bold text-emerald-600 mb-2">🔧 Estado Mecánico</h4>
                <div class="space-y-1 text-sm">
                    <div><span class="font-semibold">Combustible:</span> ${m.fuel_level || 0}%</div>
                    <div><span class="font-semibold">Temperatura Motor:</span> ${m.engine_temperature || 0}°C</div>
                    <div><span class="font-semibold">Presión Neumáticos:</span> ${m.tire_pressure || 0} PSI</div>
                    <div><span class="font-semibold">Estado Batería:</span> ${m.battery_health || 0}%</div>
                    <div><span class="font-semibold">Kilometraje:</span> ${m.mileage_km || 0} km</div>
                </div>
            </div>
            
            <div class="bg-slate-50 p-4 rounded-lg">
                <h4 class="font-bold text-purple-600 mb-2">🗺️ Navegación</h4>
                <div class="space-y-1 text-sm">
                    <div><span class="font-semibold">Destino:</span> ${l.destination_type || 'NINGUNO'}</div>
                    <div><span class="font-semibold">Coordenadas Destino:</span> ${l.destination_lat?.toFixed(4) || 'N/A'}, ${l.destination_lon?.toFixed(4) || 'N/A'}</div>
                    <div><span class="font-semibold">Progreso Ruta:</span> ${l.route_step || 0}/${l.route_total_steps || 0}</div>
                    <div><span class="font-semibold">Distancia Total:</span> ${l.total_distance_km?.toFixed(2) || 0} km</div>
                    <div><span class="font-semibold">Estado Tráfico:</span> ${l.traffic_status || 'CLEAR'}</div>
                </div>
            </div>
        </div>
        
        <div class="mt-4">
            <h4 class="font-bold text-amber-600 mb-2">⚡ Acciones Rápidas</h4>
            <div class="flex flex-wrap gap-2">
                <button onclick="sendAmbulanceAction('${ambulanceId}', 'hospital')" class="px-3 py-1 bg-emerald-100 hover:bg-emerald-200 text-emerald-700 rounded text-sm transition">🏥 Enviar a Hospital</button>
                <button onclick="sendAmbulanceAction('${ambulanceId}', 'emergency')" class="px-3 py-1 bg-red-100 hover:bg-red-200 text-red-700 rounded text-sm transition">🚨 Asignar Emergencia</button>
                <button onclick="sendAmbulanceAction('${ambulanceId}', 'refuel')" class="px-3 py-1 bg-amber-100 hover:bg-amber-200 text-amber-700 rounded text-sm transition">⛽ Enviar a Gasolinera</button>
                <button onclick="sendAmbulanceAction('${ambulanceId}', 'maintenance')" class="px-3 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded text-sm transition">🔧 Solicitar Mantenimiento</button>
                <button onclick="sendAmbulanceAction('${ambulanceId}', 'base')" class="px-3 py-1 bg-blue-100 hover:bg-blue-200 text-blue-700 rounded text-sm transition">🏠 Enviar a Base</button>
            </div>
            <p class="text-xs text-slate-500 mt-2">Nota: Hospital y Gasolinera requieren POIs creados en el mapa</p>
        </div>
        
        <div class="mt-4 text-xs text-slate-500">
            <p>ID: ${ambulanceId} | Última actualización: ${new Date().toLocaleTimeString()}</p>
        </div>
    `;
    
    ambulanceModalContent.innerHTML = content;
    ambulanceModal.classList.remove('hidden');
    ambulanceModal.classList.add('flex');
}

function sendAmbulanceAction(ambulanceId, action) {
    let payload = { ambulance_id: ambulanceId, command: action };
    let message = '';
    
    switch(action) {
        case 'hospital':
            payload.command = 'hospital';
            message = `Enviando ${ambulanceId} al hospital más cercano`;
            break;
        case 'emergency':
            payload.command = 'emergency';
            message = `Asignando emergencia a ${ambulanceId}`;
            break;
        case 'refuel':
            payload.command = 'refuel';
            message = `Enviando ${ambulanceId} a repostar`;
            break;
        case 'maintenance':
            payload.command = 'maintenance';
            message = `Solicitando mantenimiento para ${ambulanceId}`;
            break;
        default:
            addTerminalLog(`[ERROR] Acción no soportada: ${action}`);
            return;
    }
    
    // Usar el nuevo endpoint /api/ambulance/command
    postJson('/api/ambulance/command', payload)
        .then(response => {
            if (response.error) {
                addTerminalLog(`[ERROR] Fallo en acción: ${response.error}`);
            } else {
                addTerminalLog(`[ACCION] ${message}`);
            }
        })
        .catch(e => {
            addTerminalLog(`[ERROR] Fallo en petición: ${e.message}`);
        });
    
    closeAmbulanceModal();
}

function closeAmbulanceModal() {
    ambulanceModal.classList.add('hidden');
    ambulanceModal.classList.remove('flex');
}

// Close modal buttons
document.getElementById('btn-close-ambulance-modal')?.addEventListener('click', closeAmbulanceModal);
document.getElementById('ambulance-modal')?.addEventListener('click', (e) => {
    if (e.target.id === 'ambulance-modal') {
        closeAmbulanceModal();
    }
});

// -------------------------------------------------------------
// Telemetry Modal - Visualización detallada de telemetría
// -------------------------------------------------------------
let currentTelemetryAmbId = null;
let _telemetryRefreshInterval = null;

const telemetryModal = document.getElementById('telemetry-modal');

function openTelemetryModal(ambulanceId) {
    if (!ambulanceId || !simState.ambulances[ambulanceId]) {
        addTerminalLog(`[ERROR] Ambulancia ${ambulanceId} no encontrada`);
        return;
    }
    currentTelemetryAmbId = ambulanceId;
    const titleEl = document.getElementById('modal-title');
    if (titleEl) titleEl.textContent = `Telemetría – ${ambulanceId}`;

    _refreshTelemetryModal();

    telemetryModal.classList.remove('hidden');
    telemetryModal.classList.add('flex');

    if (_telemetryRefreshInterval) clearInterval(_telemetryRefreshInterval);
    _telemetryRefreshInterval = setInterval(() => {
        if (currentTelemetryAmbId && simState.ambulances[currentTelemetryAmbId]) {
            _refreshTelemetryModal();
        }
    }, 500);
}

function closeTelemetryModal() {
    telemetryModal.classList.add('hidden');
    telemetryModal.classList.remove('flex');
    if (_telemetryRefreshInterval) {
        clearInterval(_telemetryRefreshInterval);
        _telemetryRefreshInterval = null;
    }
    currentTelemetryAmbId = null;
}

function _refreshTelemetryModal() {
    if (!currentTelemetryAmbId) return;
    const amb = simState.ambulances[currentTelemetryAmbId];
    if (!amb) return;
    const v = amb.vitals || {};
    const m = amb.mechanical || {};
    const l = amb.logistics || {};

    // --- Constantes Vitales ---
    const hr = v.heart_rate || 0;
    const elHr = document.getElementById('modal-heart-rate');
    if (elHr) elHr.textContent = (v.has_patient && hr > 0) ? hr : '--';
    const elHrT = document.getElementById('modal-heart-rate-trend');
    if (elHrT) elHrT.textContent = (v.has_patient && hr > 0) ? `${hr} BPM` : '-- BPM';

    const bp = v.blood_pressure || '0/0';
    const elBp = document.getElementById('modal-blood-pressure');
    if (elBp) elBp.textContent = v.has_patient ? bp : '--/--';
    const elMap = document.getElementById('modal-map');
    if (elMap) elMap.textContent = v.has_patient ? `MAP: ${v.mean_arterial_pressure ?? '--'} mmHg` : 'MAP: -- mmHg';

    const spo2 = v.oxygen_level ?? 0;
    const elO2 = document.getElementById('modal-oxygen');
    if (elO2) elO2.textContent = v.has_patient ? `${spo2}%` : '--%';

    const bodyTemp = v.body_temperature ?? 0;
    const elTemp = document.getElementById('modal-temperature');
    if (elTemp) elTemp.textContent = v.has_patient ? `${bodyTemp}°C` : '--°C';

    // Estado paciente badge
    const psEl = document.getElementById('modal-patient-status');
    if (psEl) {
        const ps = v.patient_status || 'NONE';
        const psColors = {
            'STABLE':   'bg-emerald-100 text-emerald-700',
            'CRITICAL': 'bg-red-100 text-red-700',
            'INJURED':  'bg-amber-100 text-amber-700',
            'DECEASED': 'bg-slate-200 text-slate-600',
            'NONE':     'bg-slate-100 text-slate-500'
        };
        psEl.textContent = v.has_patient ? ps : 'SIN PACIENTE';
        psEl.className = `px-3 py-1 rounded-full text-xs font-bold ${psColors[ps] || psColors['NONE']}`;
    }

    const elEcg = document.getElementById('modal-ecg');
    if (elEcg) elEcg.textContent = v.has_patient ? (v.ecg_rhythm || '--') : '--';
    const elGcs = document.getElementById('modal-gcs');
    if (elGcs) elGcs.textContent = v.has_patient ? (v.glasgow_coma_scale ?? '--') : '--';
    const elPain = document.getElementById('modal-pain');
    if (elPain) elPain.textContent = v.has_patient ? (v.pain_level ?? '--') : '--';

    // --- Estado Mecánico ---
    const fuel = m.fuel_level ?? 0;
    const elFuelPct = document.getElementById('modal-fuel-percent');
    if (elFuelPct) elFuelPct.textContent = `${fuel.toFixed(1)}%`;
    const elFuelBar = document.getElementById('modal-fuel-bar');
    if (elFuelBar) {
        elFuelBar.style.width = `${Math.max(0, Math.min(100, fuel))}%`;
        elFuelBar.className = `h-2.5 rounded-full ${fuel < 20 ? 'bg-red-500' : fuel < 40 ? 'bg-amber-400' : 'bg-amber-500'}`;
    }
    const elFuelDist = document.getElementById('modal-fuel-distance');
    if (elFuelDist) elFuelDist.textContent = `Distancia restante: ~${Math.round((fuel / 100) * 600)} km`;

    const battery = m.battery_level ?? 0;
    const elBatPct = document.getElementById('modal-battery-percent');
    if (elBatPct) elBatPct.textContent = `${battery.toFixed(1)}%`;
    const elBatBar = document.getElementById('modal-battery-bar');
    if (elBatBar) {
        elBatBar.style.width = `${Math.max(0, Math.min(100, battery))}%`;
        elBatBar.className = `h-2.5 rounded-full ${battery < 20 ? 'bg-red-500' : 'bg-emerald-500'}`;
    }
    const elVolt = document.getElementById('modal-battery-voltage');
    if (elVolt) elVolt.textContent = `Voltaje: ${(m.alternator_voltage ?? 0).toFixed(1)} V`;

    // Neumáticos
    const tires = m.tire_pressure || [0, 0, 0, 0];
    ['modal-tire-fl','modal-tire-fr','modal-tire-rl','modal-tire-rr'].forEach((id, i) => {
        const el = document.getElementById(id);
        if (!el) return;
        const psi = tires[i] ?? 0;
        el.textContent = psi.toFixed(1);
        el.className = `text-xl font-bold ${
            psi < 25 ? 'text-red-600' : psi < 30 ? 'text-amber-500' : 'text-slate-800'
        }`;
    });

    // Temperatura motor
    const engT = m.engine_temperature ?? 0;
    const elEngT = document.getElementById('modal-engine-temp');
    if (elEngT) elEngT.textContent = engT.toFixed(1);
    const elEngTs = document.getElementById('modal-engine-temp-status');
    if (elEngTs) {
        elEngTs.textContent = engT > 110 ? '⚠️ Sobrecalentamiento' : engT > 100 ? 'Caliente' : 'Normal';
        elEngTs.className = `text-xs ${ engT > 110 ? 'text-red-500' : engT > 100 ? 'text-amber-500' : 'text-red-500' }`;
    }

    // Temperatura transmisión
    const transT = m.transmission_temperature ?? 0;
    const elTransT = document.getElementById('modal-trans-temp');
    if (elTransT) elTransT.textContent = transT.toFixed(1);
    const elTransTs = document.getElementById('modal-trans-temp-status');
    if (elTransTs) {
        elTransTs.textContent = transT > 110 ? '⚠️ Alta' : 'Normal';
        elTransTs.className = `text-xs ${ transT > 110 ? 'text-red-500' : 'text-blue-500' }`;
    }

    // JSON raw data
    const elJson = document.getElementById('modal-json');
    if (elJson) {
        elJson.textContent = JSON.stringify({ vitals: v, mechanical: m, logistics: l }, null, 2);
    }
}

// Cerrar telemetry modal
document.getElementById('btn-close-modal')?.addEventListener('click', closeTelemetryModal);
telemetryModal?.addEventListener('click', (e) => {
    if (e.target === telemetryModal) closeTelemetryModal();
});

// Botones de tratamiento
telemetryModal?.addEventListener('click', (e) => {
    const btn = e.target.closest('.modal-treatment-btn');
    if (btn && currentTelemetryAmbId) {
        const treatment = btn.dataset.treatment;
        postJson('/api/incident/inject', {
            ambulance_id: currentTelemetryAmbId,
            category: 'vitals',
            incident_type: treatment
        }).then(() => addTerminalLog(`[TRATAMIENTO] ${treatment} aplicado a ${currentTelemetryAmbId}`));
    }

    const incBtn = e.target.closest('.modal-incident-btn');
    if (incBtn && currentTelemetryAmbId) {
        const category = incBtn.dataset.category;
        const incident = incBtn.dataset.incident;
        postJson('/api/incident/inject', {
            ambulance_id: currentTelemetryAmbId,
            category,
            incident_type: incident
        }).then(() => addTerminalLog(`[INCIDENTE] ${incident} inyectado en ${currentTelemetryAmbId}`));
    }
});

// Botones de mantenimiento
document.getElementById('modal-refuel-btn')?.addEventListener('click', () => {
    if (!currentTelemetryAmbId) return;
    postJson('/api/ambulance/command', { ambulance_id: currentTelemetryAmbId, command: 'refuel' })
        .then(() => addTerminalLog(`[ACCIÓN] ${currentTelemetryAmbId} enviada a repostar`));
});
document.getElementById('modal-maintenance-btn')?.addEventListener('click', () => {
    if (!currentTelemetryAmbId) return;
    postJson('/api/ambulance/command', { ambulance_id: currentTelemetryAmbId, command: 'maintenance' })
        .then(() => addTerminalLog(`[ACCIÓN] ${currentTelemetryAmbId} enviada a mantenimiento`));
});

// -------------------------------------------------------------
// Statistics Chart Initialization
// -------------------------------------------------------------
function initCharts() {
    const ctx = document.getElementById('stats-chart');
    if (!ctx) return;
    
    // Load Chart.js if not loaded
    if (typeof Chart === 'undefined') {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/chart.js';
        script.onload = initCharts;
        document.head.appendChild(script);
        return;
    }
    
    statsChart = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [
                {
                    label: 'Ambulancias',
                    data: statsHistory.ambulancesCount,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    tension: 0.4,
                    fill: true
                },
                {
                    label: 'Emergencias',
                    data: statsHistory.emergenciesCount,
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    tension: 0.4,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${context.parsed.y}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'second',
                        displayFormats: {
                            second: 'HH:mm:ss'
                        }
                    },
                    title: {
                        display: true,
                        text: 'Tiempo'
                    }
                },
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Cantidad'
                    }
                }
            }
        }
    });
}

// -------------------------------------------------------------
// Keyboard Shortcuts
// -------------------------------------------------------------
document.addEventListener('keydown', (e) => {
    // Toggle simulation with Space
    if (e.code === 'Space' && !e.target.matches('input, textarea')) {
        e.preventDefault();
        btnPlay?.click();
    }
    
    // Clear with Escape
    if (e.code === 'Escape' && !e.target.matches('input, textarea')) {
        const panRadio = document.querySelector('input[value="PAN"]');
        if (panRadio) {
            panRadio.checked = true;
            document.querySelectorAll('.radio-mode').forEach(lbl => lbl.classList.remove('active', 'bg-blue-100', 'text-blue-700'));
            panRadio.parentElement.classList.add('active', 'bg-blue-100', 'text-blue-700');
            addTerminalLog('[MODO] Cambiado a modo PAN (Desplazamiento)');
        }
    }
});

// -------------------------------------------------------------
// Quick Actions Event Listeners
// -------------------------------------------------------------
function setupQuickActions() {
    if (DEBUG) console.log('Setting up quick actions...');
    
    // Debug: Log all quick action buttons
    const quickActionButtons = [
        'btn-quick-emergency', 'btn-quick-ambulance', 'btn-quick-hospital',
        'btn-quick-gas', 'btn-quick-incident', 'btn-quick-traffic',
        'btn-quick-communication', 'btn-quick-weather', 'btn-quick-backup-dashboard'
    ];
    quickActionButtons.forEach(id => {
        const btn = document.getElementById(id);
        console.log(`Quick action button ${id}: ${btn ? 'FOUND' : 'NOT FOUND'}`);
    });
    
    // Get center of map for quick actions
    function getMapCenter() {
        const center = map.getCenter();
        return { lat: center.lat, lon: center.lng };
    }
    
    // Quick Emergency
    const btnQuickEmergency = document.getElementById('btn-quick-emergency');
    if (btnQuickEmergency) {
        if (DEBUG) console.log('Found btn-quick-emergency');
        btnQuickEmergency.addEventListener('click', () => {
            const center = getMapCenter();
            postJson('/api/spawn', {
                type: 'EMERGENCY',
                lat: center.lat,
                lon: center.lon,
                severity: 'MEDIUM'
            });
            addTerminalLog(`[ACCIÓN RÁPIDA] Emergencia creada en centro del mapa`);
        });
    } else {
        if (DEBUG) console.error('btn-quick-emergency not found!');
    }
    
    // Quick Ambulance
    const btnQuickAmbulance = document.getElementById('btn-quick-ambulance');
    if (btnQuickAmbulance) {
        if (DEBUG) console.log('Found btn-quick-ambulance');
        btnQuickAmbulance.addEventListener('click', () => {
            const center = getMapCenter();
            postJson('/api/spawn', {
                type: 'AMBULANCE',
                lat: center.lat,
                lon: center.lon
            });
            addTerminalLog(`[ACCIÓN RÁPIDA] Ambulancia creada en centro del mapa`);
        });
    } else {
        if (DEBUG) console.error('btn-quick-ambulance not found!');
    }
    
    // Quick Hospital
    const btnQuickHospital = document.getElementById('btn-quick-hospital');
    if (btnQuickHospital) {
        btnQuickHospital.addEventListener('click', () => {
            const center = getMapCenter();
            postJson('/api/spawn', {
                type: 'HOSPITAL',
                lat: center.lat,
                lon: center.lon,
                name: 'Hospital Central'
            });
            addTerminalLog(`[ACCIÓN RÁPIDA] Hospital creado en centro del mapa`);
        });
    }
    
    // Quick Gas Station
    const btnQuickGas = document.getElementById('btn-quick-gas');
    if (btnQuickGas) {
        btnQuickGas.addEventListener('click', () => {
            const center = getMapCenter();
            postJson('/api/spawn', {
                type: 'GAS_STATION',
                lat: center.lat,
                lon: center.lon,
                name: 'Gasolinera Central'
            });
            addTerminalLog(`[ACCIÓN RÁPIDA] Gasolinera creada en centro del mapa`);
        });
    }
    
    // Quick Incident
    const btnQuickIncident = document.getElementById('btn-quick-incident');
    if (btnQuickIncident) {
        btnQuickIncident.addEventListener('click', () => {
            const ambulanceIds = Object.keys(simState.ambulances);
            if (ambulanceIds.length > 0) {
                const randomAmbulance = ambulanceIds[Math.floor(Math.random() * ambulanceIds.length)];
                postJson('/api/incident/inject', {
                    ambulance_id: randomAmbulance,
                    category: 'mechanical',
                    incident_type: 'flat_tire'
                });
                addTerminalLog(`[ACCIÓN RÁPIDA] Incidente inyectado en ${randomAmbulance}`);
            } else {
                addTerminalLog(`[ERROR] No hay ambulancias para inyectar incidente`);
            }
        });
    }
    
    // Quick Traffic Jam
    const btnQuickTraffic = document.getElementById('btn-quick-traffic');
    if (btnQuickTraffic) {
        btnQuickTraffic.addEventListener('click', () => {
            const center = getMapCenter();
            postJson('/api/spawn', {
                type: 'JAM',
                lat: center.lat,
                lon: center.lon,
                radius: 0.005
            });
            addTerminalLog(`[ACCIÓN RÁPIDA] Atasco creado en centro del mapa`);
        });
    }
    
    // Quick Communication
    const btnQuickCommunication = document.getElementById('btn-quick-communication');
    if (btnQuickCommunication) {
        btnQuickCommunication.addEventListener('click', () => {
            const mqttEnabled = document.getElementById('chk-mqtt')?.checked ?? true;
            const p2pEnabled = document.getElementById('chk-p2p')?.checked ?? true;
            const httpEnabled = document.getElementById('chk-http')?.checked ?? true;
            
            // Toggle all networks
            const newMqtt = !mqttEnabled;
            const newP2p = !p2pEnabled;
            const newHttp = !httpEnabled;
            
            postJson('/api/network', {
                mqtt: newMqtt,
                p2p: newP2p,
                http: newHttp
            });
            
            addTerminalLog(`[ACCIÓN RÁPIDA] Redes alternadas: MQTT=${newMqtt ? 'ON' : 'OFF'}, P2P=${newP2p ? 'ON' : 'OFF'}, HTTP=${newHttp ? 'ON' : 'OFF'}`);
        });
    }
    
    // Quick Weather (simulate weather effect)
    const btnQuickWeather = document.getElementById('btn-quick-weather');
    if (btnQuickWeather) {
        btnQuickWeather.addEventListener('click', () => {
            // Simulate weather effect by creating multiple jams
            const center = getMapCenter();
            for (let i = 0; i < 3; i++) {
                const offsetLat = center.lat + (Math.random() - 0.5) * 0.01;
                const offsetLon = center.lon + (Math.random() - 0.5) * 0.01;
                postJson('/api/spawn', {
                    type: 'JAM',
                    lat: offsetLat,
                    lon: offsetLon,
                    radius: 0.003,
                    severity: 0.7,
                    cause: 'bad_weather'
                });
            }
            addTerminalLog(`[ACCIÓN RÁPIDA] Efecto de mal tiempo simulado`);
        });
    }
    
    // Quick Backup Dashboard
    const btnQuickBackupDashboard = document.getElementById('btn-quick-backup-dashboard');
    if (btnQuickBackupDashboard) {
        btnQuickBackupDashboard.addEventListener('click', () => {
            window.open('/backup_dashboard', '_blank');
            addTerminalLog(`[ACCIÓN RÁPIDA] Abriendo dashboard de backups`);
        });
    }
}

// -------------------------------------------------------------
// Initialize
// -------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    // Initialize radio button visual state
    document.querySelectorAll('.radio-mode').forEach(lbl => {
        if (lbl.querySelector('input')?.checked) {
            lbl.classList.add('active', 'bg-blue-100', 'text-blue-700');
        }
    });
    
    // Initialize charts
    initCharts();
    
    // Setup quick actions
    setupQuickActions();
    
    // Populate preset selector (multi-select dropdown) from API
    fetch('/api/presets')
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .then(data => {
            if (!data.presets) return;
            const panel = document.getElementById('preset-dropdown-panel');
            if (!panel) return;
            const FLAG_MAP = {
                madrid: '\uD83C\uDDEA\uD83C\uDDF8',
                barcelona: '\uD83C\uDDEA\uD83C\uDDF8',
                sevilla: '\uD83C\uDDEA\uD83C\uDDF8',
                valencia: '\uD83C\uDDEA\uD83C\uDDF8',
                cdmx: '\uD83C\uDDF2\uD83C\uDDFD',
                guadalajara: '\uD83C\uDDF2\uD83C\uDDFD',
                monterrey: '\uD83C\uDDF2\uD83C\uDDFD',
                bogota: '\uD83C\uDDE8\uD83C\uDDF4',
                medellin: '\uD83C\uDDE8\uD83C\uDDF4',
                cali: '\uD83C\uDDE8\uD83C\uDDF4',
            };
            panel.innerHTML = '';
            Object.entries(data.presets).forEach(([key, info]) => {
                const flag = FLAG_MAP[key] || '\uD83C\uDF0D';
                const item = document.createElement('label');
                item.dataset.key = key;
                item.className = 'flex items-center gap-2 px-3 py-2 hover:bg-blue-50 cursor-pointer text-sm text-slate-700';
                item.innerHTML = `
                    <input type="checkbox" value="${key}" class="preset-checkbox w-4 h-4 accent-blue-600 rounded">
                    <span class="preset-name">${flag} ${info.name}</span>
                    <span class="ml-auto text-xs text-slate-400">${info.ambulances} 🚑 · ${info.hospitals} 🏥</span>
                `;
                item.querySelector('input').addEventListener('change', (ev) => {
                    if (ev.target.checked) selectedPresets.add(key); else selectedPresets.delete(key);
                    updatePresetDropdownLabel();
                });
                panel.appendChild(item);
            });
        })
        .catch(() => {
            // Fallback static option
            const panel = document.getElementById('preset-dropdown-panel');
            if (panel && panel.children.length === 0) {
                const item = document.createElement('label');
                item.dataset.key = 'madrid';
                item.className = 'flex items-center gap-2 px-3 py-2 hover:bg-blue-50 cursor-pointer text-sm text-slate-700';
                item.innerHTML = '<input type="checkbox" value="madrid" class="preset-checkbox w-4 h-4 accent-blue-600 rounded"><span class="preset-name">\uD83C\uDDEA\uD83C\uDDF8 Madrid</span>';
                item.querySelector('input').addEventListener('change', (ev) => {
                    if (ev.target.checked) selectedPresets.add('madrid'); else selectedPresets.delete('madrid');
                    updatePresetDropdownLabel();
                });
                panel.appendChild(item);
            }
        });

    // Toggle dropdown open/close
    const ddToggle = document.getElementById('preset-dropdown-toggle');
    const ddPanel = document.getElementById('preset-dropdown-panel');
    const ddArrow = document.getElementById('preset-dropdown-arrow');
    if (ddToggle && ddPanel) {
        ddToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = !ddPanel.classList.contains('hidden');
            ddPanel.classList.toggle('hidden', isOpen);
            ddArrow?.classList.toggle('rotate-180', !isOpen);
        });
        // Close when clicking outside
        document.addEventListener('click', (e) => {
            if (!document.getElementById('preset-dropdown-container')?.contains(e.target)) {
                ddPanel.classList.add('hidden');
                ddArrow?.classList.remove('rotate-180');
            }
        });
    }

    // Add initial log
    addTerminalLog('[SISTEMA] Centro de Control Digital Twin inicializado');
    addTerminalLog('[SISTEMA] Esperando conexión con servidor...');
    
    // Set initial map cursor
    const mapDiv = document.getElementById('tactical-map');
    if (mapDiv) mapDiv.style.cursor = 'grab';
    
    // Test API connectivity
    setTimeout(() => {
        fetch('/api/health')
            .then(r => {
                if (r.ok) return r.json();
                throw new Error(`HTTP ${r.status}`);
            })
            .then(data => {
                addTerminalLog(`[SISTEMA] Servidor API disponible: ${data.ambulances_count} ambulancias`);
            })
            .catch(e => {
                addTerminalLog(`[ERROR] No se puede conectar con el servidor API: ${e.message}`);
            });
    }, 2000);
});

// Make functions available globally for HTML onclick handlers
window.openAmbulanceDetails = openAmbulanceDetails;
window.sendAmbulanceAction = sendAmbulanceAction;
window.closeAmbulanceModal = closeAmbulanceModal;
window.focusEmergency = focusEmergency;

// Export for debugging
window.debugState = () => {
    console.log('Current state:', {
        ambulances: simState.ambulances,
        emergencies: simState.emergencies,
        is_simulating: simState.is_simulating,
        socket: socket.connected ? 'connected' : 'disconnected'
    });
    return simState;
};