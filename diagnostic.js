#!/usr/bin/env node
/**
 * Diagnostic script to check system status and fix issues
 */

const http = require('http');
const https = require('https');

const ENDPOINTS = [
    { url: 'http://localhost:5000/api/health', name: 'Main Dashboard API' },
    { url: 'http://localhost:5000/backup_dashboard', name: 'Backup Dashboard' },
    { url: 'http://localhost:8000/api/backups/health', name: 'Central Server API' },
    { url: 'http://localhost:1883', name: 'MQTT Broker', checkMqtt: true },
];

const CHECK_INTERVAL = 2000; // 2 seconds
const MAX_RETRIES = 10;

async function checkEndpoint(endpoint) {
    return new Promise((resolve) => {
        const req = http.request(endpoint.url, { method: 'GET', timeout: 5000 }, (res) => {
            let data = '';
            res.on('data', (chunk) => data += chunk);
            res.on('end', () => {
                resolve({
                    name: endpoint.name,
                    url: endpoint.url,
                    status: 'UP',
                    code: res.statusCode,
                    message: `HTTP ${res.statusCode}`
                });
            });
        });
        
        req.on('error', (err) => {
            resolve({
                name: endpoint.name,
                url: endpoint.url,
                status: 'DOWN',
                code: 0,
                message: err.message
            });
        });
        
        req.on('timeout', () => {
            req.destroy();
            resolve({
                name: endpoint.name,
                url: endpoint.url,
                status: 'TIMEOUT',
                code: 0,
                message: 'Request timeout'
            });
        });
        
        req.end();
    });
}

async function runDiagnostics() {
    console.log('🚑 HPE Ambulance Digital Twin - Diagnostic Tool');
    console.log('=' .repeat(50));
    console.log('\nChecking system components...\n');
    
    let allUp = true;
    
    for (const endpoint of ENDPOINTS) {
        const result = await checkEndpoint(endpoint);
        const statusIcon = result.status === 'UP' ? '✅' : '❌';
        
        console.log(`${statusIcon} ${result.name}`);
        console.log(`   URL: ${result.url}`);
        console.log(`   Status: ${result.status} (${result.message})`);
        console.log();
        
        if (result.status !== 'UP') {
            allUp = false;
        }
    }
    
    if (!allUp) {
        console.log('\n⚠️  Some components are not responding. Here are the troubleshooting steps:');
        console.log('\n1. Make sure all services are running:');
        console.log('   - MQTT Broker (python local_broker.py)');
        console.log('   - Central Server (python central/server.py)');
        console.log('   - Main Dashboard (python app.py)');
        console.log('\n2. Check the run_scenario.bat file for correct timing');
        console.log('\n3. Verify ports are not in use:');
        console.log('   - Port 5000: Main Dashboard');
        console.log('   - Port 8000: Central Server');
        console.log('   - Port 1883: MQTT Broker');
        console.log('\n4. Common issues:');
        console.log('   - Python dependencies not installed (run: pip install -r requirements.txt)');
        console.log('   - Services starting too quickly (increase timeouts in run_scenario.bat)');
        console.log('   - Firewall blocking ports');
    } else {
        console.log('🎉 All systems are operational!');
        console.log('\nAccess URLs:');
        console.log('   - Main Dashboard: http://localhost:5000');
        console.log('   - Backup Dashboard: http://localhost:5000/backup_dashboard');
        console.log('   - Central Server API: http://localhost:8000/api/backups/health');
    }
    
    // Check frontend issues
    console.log('\n' + '=' .repeat(50));
    console.log('Frontend Issues Analysis:');
    console.log('\nCommon problems with "No hay ambulancias desplegadas":');
    console.log('1. WebSocket connection not established');
    console.log('2. State not being broadcast from server');
    console.log('3. JavaScript errors in console');
    console.log('\nTo debug:');
    console.log('1. Open browser developer tools (F12)');
    console.log('2. Check Console tab for errors');
    console.log('3. Check Network tab for WebSocket connection');
    console.log('4. Verify sim_state events are being received');
}

// Run diagnostics
runDiagnostics().catch(console.error);