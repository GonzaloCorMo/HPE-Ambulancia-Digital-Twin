const socket = io();

// State
let simState = {
    ambulances: {},
    emergencies: {},
    pois: [],
    jams: [],
    is_simulating: false,
    speed_multiplier: 1
};

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

// -------------------------------------------------------------
// Drawing Logic (State sync based)
// -------------------------------------------------------------
function updateMap() {
    // 1. Ambulances
    const amIds = Object.keys(simState.ambulances);
    // Remove stale ones
    Object.keys(markerRefs.ambulances).forEach(id => {
        if (!amIds.includes(id)) {
            map.removeLayer(markerRefs.ambulances[id]);
            delete markerRefs.ambulances[id];
        }
    });
    // Add or update
    amIds.forEach(id => {
        const amb = simState.ambulances[id];
        const lat = amb.logistics.latitude;
        const lon = amb.logistics.longitude;
        if (!lat || !lon) return;

        const ms = amb.logistics.mission_status;
        const colorClass = ms === "ACTIVE" ? 'marker-amb-active' : (ms === "IN_USE" ? 'marker-amb-active' : 'marker-amb-inactive');

        const html = `<div class="${colorClass} w-full h-full rounded-full flex items-center justify-center text-[10px] font-bold text-white shadow-lg">🚑</div>`;
        const icon = L.divIcon({ className: `custom-div-icon ${colorClass}`, html: html, iconSize: [28, 28], iconAnchor: [14, 14] });

        if (!markerRefs.ambulances[id]) {
            markerRefs.ambulances[id] = L.marker([lat, lon], { icon }).addTo(map);
            markerRefs.ambulances[id].bindTooltip(id, { permanent: true, direction: 'right', offset: [15, 0], className: 'bg-white/90 border border-slate-300 shadow font-bold text-[10px] rounded px-1 !p-0 !m-0', opacity: 1 });
        } else {
            markerRefs.ambulances[id].setLatLng([lat, lon]);
            markerRefs.ambulances[id].setIcon(icon);
        }

        // OSRM Real Routing Logic (Only if toggled)
        const destType = amb.logistics.destination_type;
        let showLines = false;
        let routeColor = '#94a3b8'; // Slate base

        if (destType === 'EMERGENCY') {
            showLines = document.getElementById('chk-route-em') ? document.getElementById('chk-route-em').checked : true;
            routeColor = '#ef4444'; // Red
        } else if (destType === 'HOSPITAL') {
            showLines = document.getElementById('chk-route-hosp') ? document.getElementById('chk-route-hosp').checked : true;
            routeColor = '#10b981'; // Green
        } else if (destType === 'GAS_STATION') {
            showLines = document.getElementById('chk-route-gas') ? document.getElementById('chk-route-gas').checked : true;
            routeColor = '#f59e0b'; // Amber
        }

        if (showLines && amb.logistics.has_destination && amb.logistics.destination_lat && amb.logistics.destination_lon) {
            const destKey = `${amb.logistics.destination_lat.toFixed(5)},${amb.logistics.destination_lon.toFixed(5)}`;
            const styleObj = { color: routeColor, weight: 5, opacity: 0.9, className: 'route-glow' };

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
                                const coords = data.route; // backend sends [lat, lon] natively now
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
                    let latlngs = sliced.map(c => [c[0], c[1]]); // Backend sends [lat, lon], Leaflet needs [lat, lon]
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

        let cClass = 'marker-em-initiated';
        if (em.status === 'PROCESSING') cClass = 'marker-em-processing';
        else if (em.status === 'TRANSPORTING') cClass = 'marker-em-transporting';
        else if (em.status === 'RESOLVED') cClass = 'marker-em-inactive';

        const icon = L.divIcon({ className: `custom-div-icon ${cClass} rounded-full flex items-center justify-center text-[14px] text-white shadow-lg w-full h-full`, html: '🚨', iconSize: [24, 24], iconAnchor: [12, 12] });

        if (!markerRefs.emergencies[id]) {
            markerRefs.emergencies[id] = L.marker([em.lat, em.lon], { icon }).addTo(map);
        } else {
            markerRefs.emergencies[id].setLatLng([em.lat, em.lon]);
            markerRefs.emergencies[id].setIcon(icon);
        }
    });

    // 3. POIs
    // Re-drawing blindly is quick enough for few POIs, but doing optimal syncing:
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
            const icon = L.divIcon({ className: `custom-div-icon ${cClass} flex items-center justify-center text-[14px] shadow-lg w-full h-full`, html: symbol, iconSize: [30, 30], iconAnchor: [15, 15] });
            markerRefs.pois[key] = L.marker([poi.lat, poi.lon], { icon }).addTo(map);
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
            const icon = L.divIcon({ className: `custom-div-icon marker-jam flex items-center justify-center text-white shadow-lg w-full h-full`, html: '⚠️', iconSize: [40, 40], iconAnchor: [20, 20] });
            markerRefs.jams[key] = L.marker([jam.lat, jam.lon], { icon }).addTo(map);
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

socket.on('connect', () => {
    connStatus.innerHTML = '<span class="w-3 h-3 rounded-full bg-emerald-500 mr-2 shadow-[0_0_8px_#10B981]"></span> Conectado';
    connStatus.className = 'flex items-center text-sm font-semibold text-emerald-600';
});

socket.on('disconnect', () => {
    connStatus.innerHTML = '<span class="w-3 h-3 rounded-full bg-red-500 mr-2 animate-pulse"></span> Offline';
    connStatus.className = 'flex items-center text-sm font-semibold text-red-500';
});

socket.on('log', (data) => {
    const t = new Date().toLocaleTimeString('es-ES', { hour12: false });
    terminalLogs.textContent += `[${t}] ${data.msg}\n`;
    terminalLogs.scrollTop = terminalLogs.scrollHeight;

    // Prevent giant memory consumption
    if (terminalLogs.textContent.length > 10000) {
        terminalLogs.textContent = terminalLogs.textContent.substring(5000);
    }
});

socket.on('sim_state', (state) => {
    simState = state;

    // Update Control State softly only if different to prevent UI stutter
    if (state.is_simulating && btnPlay.textContent.trim() !== "⏸️ PAUSAR") {
        btnPlay.textContent = "⏸️ PAUSAR";
        btnPlay.className = "flex-1 bg-amber-100 hover:bg-amber-200 text-amber-700 font-bold py-2 px-4 rounded transition border border-amber-200 shadow-sm";
    } else if (!state.is_simulating && btnPlay.textContent.trim() !== "▶️ INICIAR") {
        btnPlay.textContent = "▶️ INICIAR";
        btnPlay.className = "flex-1 bg-emerald-100 hover:bg-emerald-200 text-emerald-700 font-bold py-2 px-4 rounded transition border border-emerald-200 shadow-sm";
    }

    speedLabel.innerText = `${state.speed_multiplier}x`;
    sliderSpeed.value = state.speed_multiplier;

    updateFleetUI();
    updateMap(); // Call the Leaflet re-sync
});

function updateFleetUI() {
    // Collect existing keys to remove dead ones, and add/update others
    const currentDomIds = Array.from(fleetContainer.children).map(c => c.dataset.amId);
    const stateAmIds = Object.keys(simState.ambulances);

    // Remove deleted
    currentDomIds.filter(id => !stateAmIds.includes(id)).forEach(id => {
        const el = document.getElementById(`card-${id}`);
        if (el) el.remove();
    });

    // Add or Update
    stateAmIds.forEach(amId => {
        const amb = simState.ambulances[amId];
        const v = amb.vitals; const m = amb.mechanical; const l = amb.logistics;

        const ms = l.mission_status;
        const colorTitle = ms === "ACTIVE" ? 'text-emerald-500' : (ms === "IN_USE" ? 'text-blue-500' : 'text-amber-500');

        let card = document.getElementById(`card-${amId}`);
        if (!card) {
            // Create
            card = document.createElement('div');
            card.id = `card-${amId}`;
            card.dataset.amId = amId;
            card.className = "p-3 rounded-lg border cursor-pointer hover:shadow-md transition-shadow bg-slate-50 border-slate-200 hover:border-blue-300";

            card.innerHTML = `
                <div class="flex items-center justify-between mb-2">
                    <span class="font-bold cursor-pointer hover:underline text-lg uppercase title-tag ${colorTitle}">🚑 ${amId}</span>
                </div>
                <div class="grid grid-cols-2 gap-x-2 gap-y-1 text-[11px] font-mono">
                    <div class="text-blue-600 truncate tag-vit"></div>
                    <div class="text-emerald-600 truncate tag-mech"></div>
                    <div class="text-purple-600 truncate tag-log"></div>
                    <div class="text-amber-600 truncate tag-net"></div>
                </div>
            `;
            // Modal hooking
            card.querySelector('.title-tag').addEventListener('click', (e) => {
                e.preventDefault();
                openModal(amId);
            });
            fleetContainer.appendChild(card);
        } else {
            // Update Title color
            const titleEl = card.querySelector('.title-tag');
            titleEl.className = `font-bold cursor-pointer hover:underline text-lg uppercase title-tag ${colorTitle}`;
        }

        // Update strings
        const vStr = `♥ ${v.heart_rate} bpm | O2: ${v.oxygen_level}% | ${v.patient_status}`;
        const mStr = `⛽ ${m.fuel_level}% | Temp: ${m.engine_temperature}C`;
        const actionStr = l.action_message || "Esperando órdenes";

        card.querySelector('.tag-vit').textContent = vStr;
        card.querySelector('.tag-mech').textContent = mStr;

        // Re-purpose the bottom slots for the new Action Message and Logistics
        card.querySelector('.tag-log').innerHTML = `<span class="font-bold text-slate-700">Vel:</span> ${Math.round(l.speed)} km/h`;
        card.querySelector('.tag-net').innerHTML = `<span class="px-2 py-[2px] rounded-full bg-slate-200 text-slate-700 font-bold text-[10px]">${actionStr}</span>`;
    });
}

// -------------------------------------------------------------
// Controls & API REST Calls
// -------------------------------------------------------------
function postJson(url, data) {
    fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
    }).catch(e => console.error(`Error on ${url}:`, e));
}

btnPlay.addEventListener('click', () => { postJson('/api/control/toggle', {}); });
document.getElementById('btn-clear').addEventListener('click', () => { postJson('/api/control/clear', {}); });

sliderSpeed.addEventListener('input', (e) => {
    postJson('/api/control/speed', { multiplier: parseInt(e.target.value) });
});

['chk-mqtt', 'chk-p2p', 'chk-http'].forEach(id => {
    document.getElementById(id).addEventListener('change', () => {
        postJson('/api/network', {
            mqtt: document.getElementById('chk-mqtt').checked,
            p2p: document.getElementById('chk-p2p').checked,
            http: document.getElementById('chk-http').checked
        });
    });
});

// -------------------------------------------------------------
// Mouse Canvas Interaction
// -------------------------------------------------------------
function getDrawMode() {
    return document.querySelector('input[name="drawMode"]:checked').value;
}

// Visual radio selector logic
document.querySelectorAll('input[name="drawMode"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
        document.querySelectorAll('.radio-mode').forEach(lbl => lbl.classList.remove('active'));
        e.target.parentElement.classList.add('active');
    });
});

map.on('click', function (e) {
    if (getDrawMode() === 'PAN') return;
    postJson('/api/spawn', { type: getDrawMode(), lat: e.latlng.lat, lon: e.latlng.lng });
});

map.on('contextmenu', function (e) {
    if (getDrawMode() === 'PAN') return;
    postJson('/api/delete', { lat: e.latlng.lat, lon: e.latlng.lng });
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
                }
            })
            .catch(e => console.error("Nominatim Search Error:", e));
    });

    inputCitySearch.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') btnSearchCity.click();
    });
}

// -------------------------------------------------------------
// Telemetry Modal logic
// -------------------------------------------------------------
const modal = document.getElementById('telemetry-modal');
const modalTitle = document.getElementById('modal-title');
const modalJson = document.getElementById('modal-json');
let modalRefreshInterval = null;

function openModal(amId) {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    modalTitle.textContent = `Telemetría Bruta - ${amId}`;

    // Refresh JSON every second
    modalRefreshInterval = setInterval(() => {
        if (simState.ambulances[amId]) {
            modalJson.textContent = JSON.stringify(simState.ambulances[amId], null, 4);
        } else {
            modalJson.textContent = "Unidad no encontrada / Desmantelada.";
        }
    }, 1000);
}

document.getElementById('btn-close-modal').addEventListener('click', () => {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    clearInterval(modalRefreshInterval);
});

