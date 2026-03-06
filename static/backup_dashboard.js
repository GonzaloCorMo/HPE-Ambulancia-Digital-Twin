// Backup Dashboard JavaScript
// Sistema de monitorización de backups HTTPS cuando MQTT/P2P fallan

// ============================================================================
// CONFIGURACIÓN Y ESTADO
// ============================================================================

const CONFIG = {
    SERVER_URL: 'http://localhost:5000',
    REFRESH_INTERVAL: 5000, // 5 segundos
    BACKUP_PAGE_SIZE: 10,
    MAX_BACKUP_HISTORY: 100,
    CHART_UPDATE_INTERVAL: 10000, // 10 segundos
    SOCKET_ENABLED: false // Por ahora usamos polling HTTP
};

let STATE = {
    // Datos de backups
    backups: [],
    filteredBackups: [],
    backupStats: {
        total: 0,
        last24h: 0,
        ambulanceCount: 0,
        dataSize: 0
    },
    
    // Estado de comunicaciones
    communicationStatus: {
        mqtt: false,
        p2p: false,
        https: true
    },
    
    // Filtros activos
    activeFilters: {
        ambulance: '',
        dataType: '',
        dateStart: '',
        dateEnd: '',
        search: ''
    },
    
    // Paginación
    pagination: {
        currentPage: 1,
        totalPages: 1,
        totalItems: 0,
        startItem: 0,
        endItem: 0
    },
    
    // Gráficos
    charts: {
        backupTimeline: null,
        fuelLevel: null,
        patientStatus: null
    },
    
    // Tiempo real
    realtime: {
        activeBackups: 0,
        ratePerMinute: 0,
        lastBackupTime: null,
        log: []
    },
    
    // Estado del sistema
    systemHealth: {
        dataAvailability: 100,
        dataIntegrity: 100,
        latency: 0
    }
};

// ============================================================================
// FUNCIONES DE UTILIDAD
// ============================================================================

function formatDateTime(timestamp) {
    if (!timestamp) return '--:--:--';
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString('es-ES', { 
        hour: '2-digit', 
        minute: '2-digit', 
        second: '2-digit' 
    });
}

function formatDate(timestamp) {
    if (!timestamp) return '--/--/--';
    const date = new Date(timestamp * 1000);
    return date.toLocaleDateString('es-ES', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
    });
}

function formatElapsedTime(timestamp) {
    if (!timestamp) return 'Nunca';
    const now = Date.now() / 1000;
    const diff = now - timestamp;
    
    if (diff < 60) return 'Hace unos segundos';
    if (diff < 3600) return `Hace ${Math.floor(diff / 60)} minutos`;
    if (diff < 86400) return `Hace ${Math.floor(diff / 3600)} horas`;
    return `Hace ${Math.floor(diff / 86400)} días`;
}

function bytesToSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function addRealtimeLog(message, type = 'info') {
    const timestamp = formatDateTime(Date.now() / 1000);
    const logEntry = {
        timestamp,
        message,
        type
    };
    
    STATE.realtime.log.unshift(logEntry);
    if (STATE.realtime.log.length > 20) {
        STATE.realtime.log.pop();
    }
    
    updateRealtimeLogDisplay();
}

function updateRealtimeLogDisplay() {
    const logContainer = document.getElementById('realtime-log');
    if (!logContainer) return;
    
    let html = '';
    STATE.realtime.log.forEach(entry => {
        let icon = '📝';
        let color = 'text-slate-600';
        
        if (entry.type === 'success') {
            icon = '✅';
            color = 'text-emerald-600';
        } else if (entry.type === 'warning') {
            icon = '⚠️';
            color = 'text-amber-600';
        } else if (entry.type === 'error') {
            icon = '❌';
            color = 'text-red-600';
        }
        
        html += `<div class="${color}">${icon} [${entry.timestamp}] ${entry.message}</div>`;
    });
    
    logContainer.innerHTML = html || '<div class="text-slate-500">Esperando actividad...</div>';
}

// ============================================================================
// FUNCIONES DE CONEXIÓN HTTP
// ============================================================================

async function fetchBackupData() {
    try {
        showLoading();
        
        // 1. Obtener lista de backups (POST porque el endpoint espera un cuerpo con filtros)
        const response = await fetch(`${CONFIG.SERVER_URL}/api/backups/list`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}) // Cuerpo vacío para obtener todos los backups
        });
        if (!response.ok) {
            console.error('Backup list response:', response.status, response.statusText);
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        
        // 2. Actualizar estado
        STATE.backups = data.backups || [];
        STATE.backupStats.total = STATE.backups.length;
        STATE.backupStats.dataSize = calculateTotalDataSize(STATE.backups);
        
        // 3. Actualizar estadísticas de 24h
        update24hStats();
        
        // 4. Actualizar lista de ambulancias para filtros
        updateAmbulanceFilter();
        
        // 5. Aplicar filtros actuales
        applyFilters();
        
        // 6. Actualizar estado de comunicaciones
        await checkCommunicationStatus();
        
        // 7. Actualizar gráficos
        updateCharts();
        
        // 8. Actualizar UI
        updateBackupTable();
        updateStatisticsDisplay();
        updateCommunicationStatusDisplay();
        updateSystemHealthDisplay();
        updateCriticalAlerts();
        
        addRealtimeLog(`Datos de backups actualizados: ${STATE.backups.length} registros`, 'success');
        
    } catch (error) {
        console.error('Error fetching backup data:', error);
        addRealtimeLog(`Error al obtener backups: ${error.message}`, 'error');
        
        // Intentar fallback a endpoint GET si POST falla
        if (error.message.includes('405')) {
            addRealtimeLog('Intentando método alternativo (GET) para obtener backups...', 'warning');
            try {
                const response = await fetch(`${CONFIG.SERVER_URL}/api/backups/list`);
                if (response.ok) {
                    const data = await response.json();
                    STATE.backups = data.backups || [];
                    STATE.backupStats.total = STATE.backups.length;
                    STATE.backupStats.dataSize = calculateTotalDataSize(STATE.backups);
                    update24hStats();
                    updateAmbulanceFilter();
                    applyFilters();
                    updateBackupTable();
                    updateStatisticsDisplay();
                    addRealtimeLog('Backups obtenidos con método alternativo', 'success');
                }
            } catch (fallbackError) {
                console.error('Fallback también falló:', fallbackError);
            }
        } else {
            showAlert('Error de Conexión', 'No se pudo conectar con el servidor de backups. Verifica que el servidor HTTPS esté ejecutándose.', 'error');
        }
    } finally {
        hideLoading();
    }
}

async function checkCommunicationStatus() {
    try {
        // Intentar conectar a MQTT (simulado)
        const mqttResponse = await fetch(`${CONFIG.SERVER_URL}/api/state`);
        if (mqttResponse.ok) {
            STATE.communicationStatus.mqtt = true;
        } else {
            STATE.communicationStatus.mqtt = false;
        }
        
        // Por ahora, simulamos que P2P está caído cuando MQTT está caído
        STATE.communicationStatus.p2p = STATE.communicationStatus.mqtt;
        
        // HTTPS siempre está activo si llegamos aquí
        STATE.communicationStatus.https = true;
        
        // Actualizar contador de backups
        STATE.realtime.activeBackups = STATE.backups.length;
        STATE.realtime.lastBackupTime = STATE.backups.length > 0 
            ? STATE.backups[0].timestamp 
            : null;
            
        // Calcular tasa de recepción (backups por minuto en última hora)
        calculateReceptionRate();
        
    } catch (error) {
        console.error('Error checking communication status:', error);
        STATE.communicationStatus.mqtt = false;
        STATE.communicationStatus.p2p = false;
        STATE.communicationStatus.https = false;
    }
}

function calculateTotalDataSize(backups) {
    // Estimación aproximada: cada backup ~2KB
    return backups.length * 2048;
}

function update24hStats() {
    const now = Date.now() / 1000;
    const twentyFourHoursAgo = now - (24 * 3600);
    
    STATE.backupStats.last24h = STATE.backups.filter(b => b.timestamp > twentyFourHoursAgo).length;
    
    // Contar ambulancias únicas en las últimas 24h
    const ambulanceIds = new Set();
    STATE.backups
        .filter(b => b.timestamp > twentyFourHoursAgo && b.ambulance_id)
        .forEach(b => ambulanceIds.add(b.ambulance_id));
    
    STATE.backupStats.ambulanceCount = ambulanceIds.size;
}

function calculateReceptionRate() {
    const oneHourAgo = Date.now() / 1000 - 3600;
    const recentBackups = STATE.backups.filter(b => b.timestamp > oneHourAgo);
    STATE.realtime.ratePerMinute = recentBackups.length > 0 
        ? Math.round(recentBackups.length / 60 * 10) / 10 
        : 0;
}

// ============================================================================
// FILTRADO Y PAGINACIÓN
// ============================================================================

function updateAmbulanceFilter() {
    const select = document.getElementById('filter-ambulance');
    if (!select) return;
    
    // Obtener ambulancias únicas
    const ambulanceIds = new Set();
    STATE.backups.forEach(b => {
        if (b.ambulance_id) ambulanceIds.add(b.ambulance_id);
    });
    
    // Guardar selección actual
    const currentValue = select.value;
    
    // Actualizar opciones
    select.innerHTML = '<option value="">Todas las ambulancias</option>';
    ambulanceIds.forEach(id => {
        const option = document.createElement('option');
        option.value = id;
        option.textContent = id;
        select.appendChild(option);
    });
    
    // Restaurar selección si existe
    if (currentValue && ambulanceIds.has(currentValue)) {
        select.value = currentValue;
    }
}

function applyFilters() {
    let filtered = [...STATE.backups];
    
    // Filtro por ambulancia
    if (STATE.activeFilters.ambulance) {
        filtered = filtered.filter(b => b.ambulance_id === STATE.activeFilters.ambulance);
    }
    
    // Filtro por tipo de dato
    if (STATE.activeFilters.dataType) {
        filtered = filtered.filter(b => {
            if (!b.critical_data) return false;
            
            const data = b.critical_data;
            switch(STATE.activeFilters.dataType) {
                case 'position': return data.position !== undefined;
                case 'patient': return data.patient_status !== undefined;
                case 'fuel': return data.fuel_level !== undefined;
                case 'mechanical': return data.mechanical_status !== undefined;
                default: return true;
            }
        });
    }
    
    // Filtro por fecha
    if (STATE.activeFilters.dateStart) {
        const startDate = new Date(STATE.activeFilters.dateStart).getTime() / 1000;
        filtered = filtered.filter(b => b.timestamp >= startDate);
    }
    
    if (STATE.activeFilters.dateEnd) {
        const endDate = new Date(STATE.activeFilters.dateEnd + 'T23:59:59').getTime() / 1000;
        filtered = filtered.filter(b => b.timestamp <= endDate);
    }
    
    // Filtro por búsqueda
    if (STATE.activeFilters.search) {
        const searchLower = STATE.activeFilters.search.toLowerCase();
        filtered = filtered.filter(b => {
            return (
                (b.ambulance_id && b.ambulance_id.toLowerCase().includes(searchLower)) ||
                (b.id && b.id.toLowerCase().includes(searchLower)) ||
                (b.critical_data && JSON.stringify(b.critical_data).toLowerCase().includes(searchLower))
            );
        });
    }
    
    STATE.filteredBackups = filtered;
    updatePagination();
}

function updatePagination() {
    const totalItems = STATE.filteredBackups.length;
    const totalPages = Math.ceil(totalItems / CONFIG.BACKUP_PAGE_SIZE);
    
    STATE.pagination = {
        currentPage: Math.min(STATE.pagination.currentPage, totalPages || 1),
        totalPages: totalPages || 1,
        totalItems,
        startItem: 0,
        endItem: 0
    };
    
    if (totalItems > 0) {
        STATE.pagination.startItem = (STATE.pagination.currentPage - 1) * CONFIG.BACKUP_PAGE_SIZE;
        STATE.pagination.endItem = Math.min(
            STATE.pagination.startItem + CONFIG.BACKUP_PAGE_SIZE,
            totalItems
        );
    }
    
    updatePaginationDisplay();
}

function updatePaginationDisplay() {
    document.getElementById('pagination-start').textContent = STATE.pagination.startItem + 1;
    document.getElementById('pagination-end').textContent = STATE.pagination.endItem;
    document.getElementById('pagination-total').textContent = STATE.pagination.totalItems;
    
    const prevBtn = document.getElementById('btn-prev-page');
    const nextBtn = document.getElementById('btn-next-page');
    const numbersContainer = document.getElementById('pagination-numbers');
    
    if (prevBtn) prevBtn.disabled = STATE.pagination.currentPage <= 1;
    if (nextBtn) nextBtn.disabled = STATE.pagination.currentPage >= STATE.pagination.totalPages;
    
    // Actualizar números de página
    if (numbersContainer) {
        numbersContainer.innerHTML = '';
        const maxPagesToShow = 5;
        let startPage = Math.max(1, STATE.pagination.currentPage - Math.floor(maxPagesToShow / 2));
        let endPage = Math.min(STATE.pagination.totalPages, startPage + maxPagesToShow - 1);
        
        if (endPage - startPage + 1 < maxPagesToShow) {
            startPage = Math.max(1, endPage - maxPagesToShow + 1);
        }
        
        for (let i = startPage; i <= endPage; i++) {
            const button = document.createElement('button');
            button.textContent = i;
            button.className = `px-3 py-1 rounded-lg transition ${
                i === STATE.pagination.currentPage 
                    ? 'bg-blue-600 text-white' 
                    : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
            }`;
            button.addEventListener('click', () => {
                STATE.pagination.currentPage = i;
                applyFilters();
                updateBackupTable();
                updatePaginationDisplay();
            });
            numbersContainer.appendChild(button);
        }
    }
}

// ============================================================================
// ACTUALIZACIÓN DE LA INTERFAZ
// ============================================================================

function updateBackupTable() {
    const tbody = document.getElementById('backup-table-body');
    if (!tbody) return;
    
    if (STATE.filteredBackups.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="px-4 py-8 text-center text-slate-400">
                    <i class="fas fa-database text-2xl mb-2"></i>
                    <p>No se encontraron backups</p>
                    <p class="text-xs mt-1">Ajusta los filtros o espera a que lleguen backups</p>
                </td>
            </tr>
        `;
        return;
    }
    
    const pageBackups = STATE.filteredBackups.slice(
        STATE.pagination.startItem,
        STATE.pagination.endItem
    );
    
    let html = '';
    pageBackups.forEach((backup, index) => {
        const data = backup.critical_data || {};
        
        // Determinar tipo de dato principal
        let dataType = 'Mixto';
        let dataTypeColor = 'bg-blue-100 text-blue-700';
        
        if (data.position && !data.patient_status && !data.fuel_level) {
            dataType = 'Posición';
            dataTypeColor = 'bg-emerald-100 text-emerald-700';
        } else if (data.patient_status) {
            dataType = 'Paciente';
            dataTypeColor = 'bg-red-100 text-red-700';
        } else if (data.fuel_level) {
            dataType = 'Combustible';
            dataTypeColor = 'bg-amber-100 text-amber-700';
        } else if (data.mechanical_status) {
            dataType = 'Mecánico';
            dataTypeColor = 'bg-purple-100 text-purple-700';
        }
        
        // Determinar estado
        let status = 'OK';
        let statusColor = 'bg-emerald-100 text-emerald-700';
        
        if (data.fuel_level < 20) {
            status = 'BAJO COMBUSTIBLE';
            statusColor = 'bg-amber-100 text-amber-700';
        }
        if (data.patient_status === 'CRITICAL') {
            status = 'PACIENTE CRÍTICO';
            statusColor = 'bg-red-100 text-red-700';
        }
        
        html += `
            <tr class="hover:bg-slate-50 transition-colors">
                <td class="px-4 py-3 text-sm text-slate-700">
                    ${backup.id || `backup-${index + STATE.pagination.startItem}`}
                </td>
                <td class="px-4 py-3">
                    <div class="flex items-center">
                        <i class="fas fa-ambulance mr-2 text-blue-500"></i>
                        <span class="font-medium">${backup.ambulance_id || 'Desconocida'}</span>
                    </div>
                </td>
                <td class="px-4 py-3 text-sm">
                    <div class="font-medium">${formatDateTime(backup.timestamp)}</div>
                    <div class="text-xs text-slate-500">${formatDate(backup.timestamp)}</div>
                </td>
                <td class="px-4 py-3">
                    <span class="text-xs font-bold px-2 py-1 rounded-full ${dataTypeColor}">${dataType}</span>
                </td>
                <td class="px-4 py-3">
                    <span class="text-xs font-bold px-2 py-1 rounded-full ${statusColor}">${status}</span>
                </td>
                <td class="px-4 py-3">
                    <button onclick="openBackupDetail(${index + STATE.pagination.startItem})" 
                            class="px-3 py-1 bg-blue-100 hover:bg-blue-200 text-blue-700 text-xs font-medium rounded-lg transition">
                        <i class="fas fa-eye mr-1"></i> Ver
                    </button>
                </td>
            </tr>
        `;
    });
    
    tbody.innerHTML = html;
}

function updateStatisticsDisplay() {
    // Estadísticas generales
    document.getElementById('stat-total-backups').textContent = STATE.backupStats.total;
    document.getElementById('stat-24h-backups').textContent = STATE.backupStats.last24h;
    document.getElementById('stat-ambulance-count').textContent = STATE.backupStats.ambulanceCount;
    document.getElementById('stat-data-size').textContent = bytesToSize(STATE.backupStats.dataSize);
    
    // Tiempo real
    document.getElementById('realtime-active-backups').textContent = STATE.realtime.activeBackups;
    document.getElementById('realtime-rate').textContent = `${STATE.realtime.ratePerMinute}/min`;
    document.getElementById('realtime-last-backup').textContent = 
        STATE.realtime.lastBackupTime ? formatElapsedTime(STATE.realtime.lastBackupTime) : 'Nunca';
    
    // Conteo de backups HTTPS
    document.getElementById('https-backup-count').textContent = STATE.backupStats.total;
    document.getElementById('https-last-backup').textContent = 
        STATE.realtime.lastBackupTime ? formatDateTime(STATE.realtime.lastBackupTime) : '--:--:--';
}

function updateCommunicationStatusDisplay() {
    // MQTT
    const mqttIndicator = document.getElementById('mqtt-status-indicator');
    const mqttStatus = document.getElementById('mqtt-status-text');
    const mqttLastConnect = document.getElementById('mqtt-last-connect');
    
    if (STATE.communicationStatus.mqtt) {
        mqttIndicator.className = 'w-4 h-4 rounded-full bg-emerald-500 pulse-ring';
        mqttStatus.textContent = 'CONECTADO';
        mqttStatus.className = 'px-3 py-1 rounded-full text-xs font-bold bg-emerald-100 text-emerald-700';
        mqttLastConnect.textContent = formatElapsedTime(Date.now() / 1000);
    } else {
        mqttIndicator.className = 'w-4 h-4 rounded-full bg-red-500 pulse-ring';
        mqttStatus.textContent = 'DESCONECTADO';
        mqttStatus.className = 'px-3 py-1 rounded-full text-xs font-bold bg-red-100 text-red-700';
        mqttLastConnect.textContent = formatElapsedTime(null);
    }
    
    // P2P
    const p2pIndicator = document.getElementById('p2p-status-indicator');
    const p2pStatus = document.getElementById('p2p-status-text');
    const p2pLastTransmission = document.getElementById('p2p-last-transmission');
    
    if (STATE.communicationStatus.p2p) {
        p2pIndicator.className = 'w-4 h-4 rounded-full bg-blue-500 pulse-ring';
        p2pStatus.textContent = 'ACTIVO';
        p2pStatus.className = 'px-3 py-1 rounded-full text-xs font-bold bg-blue-100 text-blue-700';
        p2pLastTransmission.textContent = formatElapsedTime(Date.now() / 1000);
    } else {
        p2pIndicator.className = 'w-4 h-4 rounded-full bg-red-500 pulse-ring';
        p2pStatus.textContent = 'DESCONECTADO';
        p2pStatus.className = 'px-3 py-1 rounded-full text-xs font-bold bg-red-100 text-red-700';
        p2pLastTransmission.textContent = formatElapsedTime(null);
    }
    
    // HTTPS
    const httpsIndicator = document.getElementById('https-status-indicator');
    const httpsStatus = document.getElementById('https-status-text');
    
    httpsIndicator.className = 'w-4 h-4 rounded-full bg-emerald-500';
    httpsStatus.textContent = 'CONECTADO';
    httpsStatus.className = 'px-3 py-1 rounded-full text-xs font-bold bg-emerald-100 text-emerald-700';
    
    // Estado de conexión general
    const connStatus = document.getElementById('connection-status');
    if (connStatus) {
        if (STATE.communicationStatus.https) {
            connStatus.innerHTML = '<span class="w-3 h-3 rounded-full bg-emerald-500 block mr-2"></span> <span>Conectado al servidor HTTPS</span>';
            connStatus.className = 'flex items-center text-sm font-semibold text-emerald-500 bg-emerald-50 px-3 py-1.5 rounded-lg border border-emerald-100';
        } else {
            connStatus.innerHTML = '<span class="w-3 h-3 rounded-full bg-red-500 block mr-2 animate-ping"></span> <span>Sin conexión al servidor</span>';
            connStatus.className = 'flex items-center text-sm font-semibold text-red-500 bg-red-50 px-3 py-1.5 rounded-lg border border-red-100';
        }
    }
}

function updateSystemHealthDisplay() {
    // Barras de salud
    document.getElementById('health-data-availability').textContent = `${STATE.systemHealth.dataAvailability}%`;
    document.getElementById('health-data-bar').style.width = `${STATE.systemHealth.dataAvailability}%`;
    
    document.getElementById('health-data-integrity').textContent = `${STATE.systemHealth.dataIntegrity}%`;
    document.getElementById('health-integrity-bar').style.width = `${STATE.systemHealth.dataIntegrity}%`;
    
    document.getElementById('health-latency').textContent = `${STATE.systemHealth.latency} ms`;
    document.getElementById('health-latency-bar').style.width = 
        STATE.systemHealth.latency < 100 ? '100%' : 
        STATE.systemHealth.latency < 500 ? '70%' : 
        STATE.systemHealth.latency < 1000 ? '40%' : '20%';
    
    // Información del servidor
    document.getElementById('server-url').textContent = CONFIG.SERVER_URL;
    document.getElementById('api-version').textContent = 'v1.0';
    document.getElementById('last-sync-time').textContent = formatDateTime(Date.now() / 1000);
}

function updateCriticalAlerts() {
    const container = document.getElementById('critical-alerts-container');
    if (!container) return;
    
    // Buscar alertas críticas en los últimos backups
    const criticalBackups = STATE.backups.slice(0, 10).filter(backup => {
        const data = backup.critical_data || {};
        return (
            data.fuel_level < 20 ||
            data.patient_status === 'CRITICAL' ||
            (data.mechanical_status && data.mechanical_status.includes('FAIL'))
        );
    });
    
    if (criticalBackups.length === 0) {
        container.innerHTML = `
            <div class="text-center py-4 text-slate-400">
                <i class="fas fa-check-circle text-2xl mb-2"></i>
                <p>No hay alertas críticas</p>
                <p class="text-xs">Todos los sistemas funcionan correctamente</p>
            </div>
        `;
        return;
    }
    
    let html = '';
    criticalBackups.forEach(backup => {
        const data = backup.critical_data || {};
        let alertType = '';
        let alertMessage = '';
        let alertColor = 'bg-amber-100 border-amber-200';
        
        if (data.fuel_level < 20) {
            alertType = '⛽ COMBUSTIBLE BAJO';
            alertMessage = `${backup.ambulance_id || 'Ambulancia'} tiene ${data.fuel_level}% de combustible`;
            alertColor = 'bg-amber-100 border-amber-200';
        } else if (data.patient_status === 'CRITICAL') {
            alertType = '💀 PACIENTE CRÍTICO';
            alertMessage = `${backup.ambulance_id || 'Ambulancia'} transporta paciente en estado crítico`;
            alertColor = 'bg-red-100 border-red-200';
        } else if (data.mechanical_status && data.mechanical_status.includes('FAIL')) {
            alertType = '🔧 FALLO MECÁNICO';
            alertMessage = `${backup.ambulance_id || 'Ambulancia'} reporta fallo: ${data.mechanical_status}`;
            alertColor = 'bg-purple-100 border-purple-200';
        }
        
        if (alertType) {
            html += `
                <div class="p-3 rounded-lg border ${alertColor}">
                    <div class="flex items-center justify-between">
                        <div class="font-bold">${alertType}</div>
                        <div class="text-xs text-slate-500">${formatElapsedTime(backup.timestamp)}</div>
                    </div>
                    <div class="text-sm mt-1">${alertMessage}</div>
                    <div class="text-xs text-slate-500 mt-2">
                        Ambulancia: ${backup.ambulance_id || 'Desconocida'} | 
                        <button onclick="openBackupDetail(${STATE.backups.indexOf(backup)})" 
                                class="text-blue-600 hover:text-blue-800 ml-1">
                            Ver detalles
                        </button>
                    </div>
                </div>
            `;
        }
    });
    
    container.innerHTML = html;
}

// ============================================================================
// GRÁFICOS
// ============================================================================

function initCharts() {
    // Gráfico de línea: Frecuencia de backups
    const timelineCtx = document.getElementById('backup-timeline-chart');
    if (timelineCtx) {
        STATE.charts.backupTimeline = new Chart(timelineCtx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Backups por hora',
                    data: [],
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    }
                },
                scales: {
                    x: {
                        title: {
                            display: true,
                            text: 'Hora'
                        }
                    },
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Número de Backups'
                        }
                    }
                }
            }
        });
    }
    
    // Gráfico de barras: Nivel de combustible por ambulancia
    const fuelCtx = document.getElementById('fuel-level-chart');
    if (fuelCtx) {
        STATE.charts.fuelLevel = new Chart(fuelCtx, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'Combustible (%)',
                    data: [],
                    backgroundColor: '#f59e0b',
                    borderColor: '#d97706',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        title: {
                            display: true,
                            text: 'Porcentaje'
                        }
                    }
                }
            }
        });
    }
    
    // Gráfico de donut: Estado de pacientes
    const patientCtx = document.getElementById('patient-status-chart');
    if (patientCtx) {
        STATE.charts.patientStatus = new Chart(patientCtx, {
            type: 'doughnut',
            data: {
                labels: ['Crítico', 'Grave', 'Estable', 'Sin paciente'],
                datasets: [{
                    data: [0, 0, 0, 0],
                    backgroundColor: [
                        '#ef4444', // Rojo - Crítico
                        '#f97316', // Naranja - Grave
                        '#10b981', // Verde - Estable
                        '#94a3b8'  // Gris - Sin paciente
                    ]
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });
    }
    
    updateCharts();
}

function updateCharts() {
    if (!STATE.backups.length) return;
    
    // Actualizar gráfico de línea: Frecuencia por hora
    if (STATE.charts.backupTimeline) {
        const last24h = STATE.backups.filter(b => {
            return b.timestamp > (Date.now() / 1000 - 24 * 3600);
        });
        
        // Agrupar por hora
        const hourlyData = {};
        last24h.forEach(backup => {
            const hour = new Date(backup.timestamp * 1000).getHours();
            hourlyData[hour] = (hourlyData[hour] || 0) + 1;
        });
        
        const labels = Object.keys(hourlyData).sort((a, b) => a - b).map(h => `${h}:00`);
        const data = Object.keys(hourlyData).sort((a, b) => a - b).map(h => hourlyData[h]);
        
        STATE.charts.backupTimeline.data.labels = labels;
        STATE.charts.backupTimeline.data.datasets[0].data = data;
        STATE.charts.backupTimeline.update();
    }
    
    // Actualizar gráfico de combustible
    if (STATE.charts.fuelLevel) {
        // Obtener último backup por ambulancia
        const latestByAmbulance = {};
        STATE.backups.forEach(backup => {
            if (!backup.ambulance_id || !backup.critical_data?.fuel_level) return;
            
            if (!latestByAmbulance[backup.ambulance_id] || 
                backup.timestamp > latestByAmbulance[backup.ambulance_id].timestamp) {
                latestByAmbulance[backup.ambulance_id] = backup;
            }
        });
        
        const labels = Object.keys(latestByAmbulance).slice(0, 10); // Máximo 10 ambulancias
        const data = labels.map(id => latestByAmbulance[id].critical_data.fuel_level);
        
        STATE.charts.fuelLevel.data.labels = labels;
        STATE.charts.fuelLevel.data.datasets[0].data = data;
        STATE.charts.fuelLevel.update();
    }
    
    // Actualizar gráfico de estado de pacientes
    if (STATE.charts.patientStatus) {
        // Contar estados de paciente en últimos backups
        const patientCounts = {
            critical: 0,
            serious: 0,
            stable: 0,
            none: 0
        };
        
        const recentBackups = STATE.backups.slice(0, 50); // Últimos 50 backups
        
        recentBackups.forEach(backup => {
            const status = backup.critical_data?.patient_status;
            if (!status || status === 'NONE') {
                patientCounts.none++;
            } else if (status === 'CRITICAL') {
                patientCounts.critical++;
            } else if (status === 'SERIOUS') {
                patientCounts.serious++;
            } else {
                patientCounts.stable++;
            }
        });
        
        STATE.charts.patientStatus.data.datasets[0].data = [
            patientCounts.critical,
            patientCounts.serious,
            patientCounts.stable,
            patientCounts.none
        ];
        STATE.charts.patientStatus.update();
    }
}

// ============================================================================
// MODAL DE DETALLES DE BACKUP
// ============================================================================

function openBackupDetail(index) {
    const backup = STATE.filteredBackups[index];
    if (!backup) return;
    
    const modal = document.getElementById('backup-detail-modal');
    const title = document.getElementById('detail-modal-title');
    const detailId = document.getElementById('detail-id');
    const detailAmbulance = document.getElementById('detail-ambulance');
    const detailTimestamp = document.getElementById('detail-timestamp');
    const detailCriticalData = document.getElementById('detail-critical-data');
    const detailFullJson = document.getElementById('detail-full-json');
    
    if (!modal || !title) return;
    
    // Actualizar contenido
    title.textContent = `Backup - ${backup.id || `ID-${index}`}`;
    detailId.textContent = backup.id || `backup-${index}`;
    detailAmbulance.textContent = backup.ambulance_id || 'Desconocida';
    detailTimestamp.textContent = `${formatDateTime(backup.timestamp)} (${formatDate(backup.timestamp)})`;
    
    // Datos críticos formateados
    const criticalData = backup.critical_data || {};
    let criticalHtml = '<div class="space-y-2">';
    
    if (criticalData.position) {
        criticalHtml += `
            <div class="bg-blue-50 p-2 rounded">
                <div class="font-bold text-blue-700">📍 Posición</div>
                <div class="text-sm">Lat: ${criticalData.position.lat?.toFixed(4) || 'N/A'}</div>
                <div class="text-sm">Lon: ${criticalData.position.lon?.toFixed(4) || 'N/A'}</div>
            </div>
        `;
    }
    
    if (criticalData.patient_status) {
        criticalHtml += `
            <div class="bg-red-50 p-2 rounded">
                <div class="font-bold text-red-700">❤️ Paciente</div>
                <div class="text-sm">Estado: ${criticalData.patient_status}</div>
                ${criticalData.heart_rate ? `<div class="text-sm">Ritmo: ${criticalData.heart_rate} BPM</div>` : ''}
                ${criticalData.oxygen_level ? `<div class="text-sm">Oxígeno: ${criticalData.oxygen_level}%</div>` : ''}
            </div>
        `;
    }
    
    if (criticalData.fuel_level !== undefined) {
        criticalHtml += `
            <div class="bg-amber-50 p-2 rounded">
                <div class="font-bold text-amber-700">⛽ Combustible</div>
                <div class="text-sm">Nivel: ${criticalData.fuel_level}%</div>
                ${criticalData.fuel_distance ? `<div class="text-sm">Distancia restante: ${criticalData.fuel_distance} km</div>` : ''}
            </div>
        `;
    }
    
    if (criticalData.mission_status) {
        criticalHtml += `
            <div class="bg-emerald-50 p-2 rounded">
                <div class="font-bold text-emerald-700">🗺️ Misión</div>
                <div class="text-sm">Estado: ${criticalData.mission_status}</div>
                ${criticalData.destination_type ? `<div class="text-sm">Destino: ${criticalData.destination_type}</div>` : ''}
            </div>
        `;
    }
    
    criticalHtml += '</div>';
    detailCriticalData.innerHTML = criticalHtml;
    
    // JSON completo
    detailFullJson.textContent = JSON.stringify(backup, null, 2);
    
    // Mostrar modal
    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function closeBackupDetailModal() {
    const modal = document.getElementById('backup-detail-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

// ============================================================================
// ACCIONES RÁPIDAS
// ============================================================================

async function sendTestBackup() {
    try {
        showLoading();
        addRealtimeLog('Enviando backup de prueba...', 'info');
        
        const testBackup = {
            ambulance_id: `TEST-${Date.now().toString().slice(-6)}`,
            timestamp: Date.now() / 1000,
            critical_data: {
                position: {
                    lat: 40.4168 + (Math.random() - 0.5) * 0.1,
                    lon: -3.7038 + (Math.random() - 0.5) * 0.1
                },
                patient_status: Math.random() > 0.5 ? 'STABLE' : 'CRITICAL',
                fuel_level: Math.floor(Math.random() * 100),
                mission_status: 'ACTIVE',
                heart_rate: Math.floor(60 + Math.random() * 40),
                oxygen_level: Math.floor(90 + Math.random() * 10)
            }
        };
        
        const response = await fetch(`${CONFIG.SERVER_URL}/api/backup_state`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(testBackup)
        });
        
        if (response.ok) {
            addRealtimeLog('Backup de prueba enviado correctamente', 'success');
            showAlert('Backup de Prueba', 'Backup enviado correctamente al servidor.', 'success');
            
            // Refrescar datos después de un momento
            setTimeout(fetchBackupData, 1000);
        } else {
            throw new Error(`HTTP ${response.status}`);
        }
        
    } catch (error) {
        console.error('Error sending test backup:', error);
        addRealtimeLog(`Error al enviar backup de prueba: ${error.message}`, 'error');
        showAlert('Error', 'No se pudo enviar el backup de prueba. Verifica la conexión al servidor.', 'error');
    } finally {
        hideLoading();
    }
}

function simulateMqttFailure() {
    STATE.communicationStatus.mqtt = false;
    STATE.communicationStatus.p2p = false;
    STATE.communicationStatus.https = true;
    
    updateCommunicationStatusDisplay();
    addRealtimeLog('Simulación de fallo MQTT/P2P activada', 'warning');
    showAlert('Fallo Simulado', 'Se ha simulado un fallo en las comunicaciones MQTT y P2P. Solo HTTPS permanece activo.', 'warning');
}

function exportBackupsToJSON() {
    const dataStr = JSON.stringify(STATE.backups, null, 2);
    const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
    
    const exportFileDefaultName = `ambulance-backups-${new Date().toISOString().slice(0,10)}.json`;
    
    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();
    
    addRealtimeLog('Backups exportados a JSON', 'success');
    showAlert('Exportación Exitosa', 'Los backups han sido exportados a un archivo JSON.', 'success');
}

// ============================================================================
// MANEJO DE INTERFAZ
// ============================================================================

function showLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.classList.remove('hidden');
}

function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.classList.add('hidden');
}

function showAlert(title, message, type = 'info') {
    const modal = document.getElementById('alert-modal');
    const alertTitle = document.getElementById('alert-title');
    const alertMessage = document.getElementById('alert-message');
    const alertIcon = document.getElementById('alert-icon');
    
    if (!modal || !alertTitle) return;
    
    // Configurar según tipo
    let icon = 'fas fa-info-circle';
    let iconColor = 'bg-blue-100 text-blue-600';
    
    if (type === 'success') {
        icon = 'fas fa-check-circle';
        iconColor = 'bg-emerald-100 text-emerald-600';
    } else if (type === 'warning') {
        icon = 'fas fa-exclamation-triangle';
        iconColor = 'bg-amber-100 text-amber-600';
    } else if (type === 'error') {
        icon = 'fas fa-times-circle';
        iconColor = 'bg-red-100 text-red-600';
    }
    
    // Actualizar contenido
    alertTitle.textContent = title;
    alertMessage.textContent = message;
    alertIcon.innerHTML = `<i class="${icon} text-xl"></i>`;
    alertIcon.className = `p-3 rounded-full ${iconColor}`;
    
    // Mostrar modal
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    
    // Auto-ocultar después de 5 segundos
    setTimeout(() => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }, 5000);
}

// ============================================================================
// INICIALIZACIÓN Y EVENT LISTENERS
// ============================================================================

function initEventListeners() {
    // Filtros
    document.getElementById('filter-ambulance')?.addEventListener('change', (e) => {
        STATE.activeFilters.ambulance = e.target.value;
        applyFilters();
        updateBackupTable();
    });
    
    document.getElementById('filter-data-type')?.addEventListener('change', (e) => {
        STATE.activeFilters.dataType = e.target.value;
        applyFilters();
        updateBackupTable();
    });
    
    document.getElementById('filter-date-start')?.addEventListener('change', (e) => {
        STATE.activeFilters.dateStart = e.target.value;
        applyFilters();
        updateBackupTable();
    });
    
    document.getElementById('filter-date-end')?.addEventListener('change', (e) => {
        STATE.activeFilters.dateEnd = e.target.value;
        applyFilters();
        updateBackupTable();
    });
    
    // Búsqueda
    document.getElementById('btn-search-backup')?.addEventListener('click', () => {
        const searchInput = document.getElementById('backup-search');
        if (searchInput) {
            STATE.activeFilters.search = searchInput.value;
            applyFilters();
            updateBackupTable();
        }
    });
    
    document.getElementById('backup-search')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            STATE.activeFilters.search = e.target.value;
            applyFilters();
            updateBackupTable();
        }
    });
    
    // Paginación
    document.getElementById('btn-prev-page')?.addEventListener('click', () => {
        if (STATE.pagination.currentPage > 1) {
            STATE.pagination.currentPage--;
            applyFilters();
            updateBackupTable();
            updatePaginationDisplay();
        }
    });
    
    document.getElementById('btn-next-page')?.addEventListener('click', () => {
        if (STATE.pagination.currentPage < STATE.pagination.totalPages) {
            STATE.pagination.currentPage++;
            applyFilters();
            updateBackupTable();
            updatePaginationDisplay();
        }
    });
    
    // Acciones rápidas
    document.getElementById('btn-refresh-backups')?.addEventListener('click', fetchBackupData);
    document.getElementById('btn-send-test-backup')?.addEventListener('click', sendTestBackup);
    document.getElementById('btn-simulate-mqtt-failure')?.addEventListener('click', simulateMqttFailure);
    document.getElementById('btn-export-backups')?.addEventListener('click', exportBackupsToJSON);
    document.getElementById('btn-export-json')?.addEventListener('click', exportBackupsToJSON);
    
    // Cerrar modales
    document.getElementById('btn-close-detail-modal')?.addEventListener('click', closeBackupDetailModal);
    document.getElementById('btn-close-detail')?.addEventListener('click', closeBackupDetailModal);
    document.getElementById('alert-dismiss')?.addEventListener('click', () => {
        document.getElementById('alert-modal').classList.add('hidden');
    });
    
    // Cerrar modal al hacer clic fuera
    document.getElementById('backup-detail-modal')?.addEventListener('click', (e) => {
        if (e.target.id === 'backup-detail-modal') {
            closeBackupDetailModal();
        }
    });
    
    document.getElementById('alert-modal')?.addEventListener('click', (e) => {
        if (e.target.id === 'alert-modal') {
            e.target.classList.add('hidden');
        }
    });
}

function initializeDashboard() {
    console.log('Inicializando Dashboard de Backups...');
    
    // Inicializar gráficos
    initCharts();
    
    // Configurar event listeners
    initEventListeners();
    
    // Cargar datos iniciales
    fetchBackupData();
    
    // Configurar actualización periódica
    setInterval(fetchBackupData, CONFIG.REFRESH_INTERVAL);
    setInterval(updateCharts, CONFIG.CHART_UPDATE_INTERVAL);
    
    // Actualizar logs en tiempo real
    setInterval(() => {
        updateCriticalAlerts();
        updateRealtimeLogDisplay();
    }, 2000);
    
    // Ocultar loading overlay
    setTimeout(hideLoading, 1000);
    
    addRealtimeLog('Dashboard de backups inicializado', 'success');
}

// ============================================================================
// INICIALIZACIÓN AL CARGAR LA PÁGINA
// ============================================================================

document.addEventListener('DOMContentLoaded', initializeDashboard);

// Exportar funciones globales
window.openBackupDetail = openBackupDetail;
window.closeBackupDetailModal = closeBackupDetailModal;
window.fetchBackupData = fetchBackupData;
window.sendTestBackup = sendTestBackup;
window.simulateMqttFailure = simulateMqttFailure;
window.exportBackupsToJSON = exportBackupsToJSON;