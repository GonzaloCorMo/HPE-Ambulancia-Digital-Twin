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

// Map Constants for Madrid bounded box
const MIN_LAT = 40.4000, MAX_LAT = 40.5000;
const MIN_LON = -3.7500, MAX_LON = -3.6000;

// Canvas Setup
const canvas = document.getElementById('tactical-map');
const ctx = canvas.getContext('2d');
let cw = 0, ch = 0;

function resizeCanvas() {
    // High DPI Canvas support
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * window.devicePixelRatio;
    canvas.height = rect.height * window.devicePixelRatio;
    cw = canvas.width;
    ch = canvas.height;
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    cw /= window.devicePixelRatio;
    ch /= window.devicePixelRatio;
}

window.addEventListener('resize', resizeCanvas);
resizeCanvas(); // Initial call

// Coordinate math
function coordToPixel(lat, lon) {
    const x = (lon - MIN_LON) / (MAX_LON - MIN_LON) * cw;
    const y = ch - ((lat - MIN_LAT) / (MAX_LAT - MIN_LAT) * ch);
    return { x, y };
}

function pixelToCoord(px, py) {
    const lon = (px / cw) * (MAX_LON - MIN_LON) + MIN_LON;
    const lat = MAX_LAT - (py / ch) * (MAX_LAT - MIN_LAT);
    return { lat, lon };
}

// -------------------------------------------------------------
// Drawing Loop
// -------------------------------------------------------------
function drawLoop() {
    ctx.clearRect(0, 0, cw, ch);

    // 1. Grid
    ctx.strokeStyle = '#E2E8F0'; // Slate 200
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    for (let i = 0; i < cw; i += 40) { ctx.moveTo(i, 0); ctx.lineTo(i, ch); }
    for (let i = 0; i < ch; i += 40) { ctx.moveTo(0, i); ctx.lineTo(cw, i); }
    ctx.stroke();
    ctx.setLineDash([]); // Reset

    // 2. Highways (Predictive connecting between all POIS/JAMS < 300px dist)
    const showLines = document.getElementById('chk-lines') ? document.getElementById('chk-lines').checked : true;
    if (showLines) {
        const nodes = [...simState.pois.map(p => coordToPixel(p.lat, p.lon)), ...simState.jams.map(j => coordToPixel(j.lat, j.lon))];
        ctx.strokeStyle = '#94A3B8'; // Slate 400
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (let i = 0; i < nodes.length; i++) {
            for (let j = i + 1; j < nodes.length; j++) {
                const dx = nodes[i].x - nodes[j].x;
                const dy = nodes[i].y - nodes[j].y;
                if (Math.sqrt(dx * dx + dy * dy) < 300) {
                    ctx.moveTo(nodes[i].x, nodes[i].y);
                    ctx.lineTo(nodes[j].x, nodes[j].y);
                }
            }
        }
        ctx.stroke();
    }

    // 3. Jams
    simState.jams.forEach(jam => {
        const { x, y } = coordToPixel(jam.lat, jam.lon);
        // Area
        ctx.fillStyle = 'rgba(254, 205, 211, 0.5)'; // Rose 200 light
        ctx.strokeStyle = '#DC2626';
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(x, y, 30, 0, Math.PI * 2); ctx.fill(); ctx.stroke();

        ctx.fillStyle = '#FFF';
        ctx.beginPath(); ctx.arc(x, y, 12, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = '#DC2626';
        ctx.font = '14px Arial'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText('⚠️', x, y);
    });

    // 4. POIs
    simState.pois.forEach(poi => {
        const { x, y } = coordToPixel(poi.lat, poi.lon);
        const isHosp = poi.type === 'HOSPITAL';
        const color = isHosp ? '#2563EB' : '#F59E0B';
        const symbol = isHosp ? '🏥' : '⛽';

        // Glow dashed outline
        ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.arc(x, y, 20, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);

        ctx.fillStyle = '#F8FAFC'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(x, y, 16, 0, Math.PI * 2); ctx.fill(); ctx.stroke();

        ctx.fillStyle = '#FFF';
        ctx.beginPath(); ctx.arc(x, y, 10, 0, Math.PI * 2); ctx.fill();
        ctx.font = '12px "Segoe UI Emoji", Arial'; ctx.fillText(symbol, x, y);
    });

    // 5. Emergencies
    Object.values(simState.emergencies).forEach(em => {
        const { x, y } = coordToPixel(em.lat, em.lon);
        ctx.fillStyle = '#FFF'; ctx.strokeStyle = '#DC2626'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(x, y, 12, 0, Math.PI * 2); ctx.fill(); ctx.stroke();

        let symbol = '🚨';
        if (em.status === 'PROCESSING') { symbol = '✚'; ctx.fillStyle = '#DC2626'; }
        if (em.status === 'RESOLVED') { symbol = '🤕'; ctx.fillStyle = '#F59E0B'; }

        ctx.font = '16px "Segoe UI Emoji"'; ctx.fillText(symbol, x, y);
    });

    // 6. Ambulances
    Object.values(simState.ambulances).forEach(amb => {
        const lat = amb.logistics.latitude;
        const lon = amb.logistics.longitude;
        if (!lat || !lon) return;
        const { x, y } = coordToPixel(lat, lon);

        const ms = amb.logistics.mission_status;
        const color = ms === "ACTIVE" ? '#10B981' : (ms === "IN_USE" ? '#2563EB' : '#F59E0B');

        ctx.fillStyle = color; ctx.strokeStyle = '#FFFFFF'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(x, y, 11, 0, Math.PI * 2); ctx.fill(); ctx.stroke();

        // ID Tag
        ctx.fillStyle = '#FFFFFF'; ctx.strokeStyle = '#E2E8F0'; ctx.lineWidth = 1;
        ctx.fillRect(x - 24, y - 26, 48, 14); ctx.strokeRect(x - 24, y - 26, 48, 14);

        ctx.fillStyle = '#0F172A';
        ctx.font = 'bold 9px Arial'; ctx.fillText(amb.ambulance_id, x, y - 19);
    });

    requestAnimationFrame(drawLoop);
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
        const mStr = `⛽ ${m.fuel_level}% | Temp: ${m.engine_temperature}C | ${m.status}`;
        const lStr = `📍 ${l.speed} km/h | Mis: ${l.mission_status}`;
        // Pseudo logic for networks based on simulator state since we removed standard socket p2p strings from engine
        const pStr = `📡 MQTT/P2P OK`;

        card.querySelector('.tag-vit').textContent = vStr;
        card.querySelector('.tag-mech').textContent = mStr;
        card.querySelector('.tag-log').textContent = lStr;
        card.querySelector('.tag-net').textContent = pStr;
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

canvas.addEventListener('dblclick', (e) => {
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const { lat, lon } = pixelToCoord(x, y);
    postJson('/api/spawn', { type: getDrawMode(), lat, lon });
});

canvas.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const { lat, lon } = pixelToCoord(x, y);
    postJson('/api/delete', { lat, lon });
});

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

// Start loop
requestAnimationFrame(drawLoop);
