@echo off
echo ========================================================
echo   Simulador de Gemelos Digitales de Ambulancias
echo   Versión Mejorada - Repostaje 100%% y Acciones Rápidas
echo ========================================================
echo.

echo [1/4] Iniciando Broker MQTT Local...
start "Broker MQTT" cmd /k "python local_broker.py"

echo Esperando a que el broker este listo (3 segundos)...
timeout /t 3 /nobreak > nul
echo.

echo [2/4] Iniciando Servidor de la Centralita...
start "Centralita Dashboard" cmd /k "python central\server.py"

echo Esperando a que la centralita este lista (4 segundos)...
timeout /t 4 /nobreak > nul
echo.

echo [3/4] Iniciando Servidor Web FastAPI (Backend)...
start "Gemelos Ambulancias (Web)" cmd /k "python app.py"

echo Esperando despliegue web (5 segundos)...
timeout /t 5 /nobreak > nul

echo [4/4] Abriendo Dashboards en navegador...
start http://localhost:5000
start http://localhost:5000/backup_dashboard
echo.

echo Verificando servicios...
echo - MQTT Broker: http://localhost:1883 (si está activo)
echo - Centralita API: http://localhost:8000/api/backups/health
echo - Dashboard Principal: http://localhost:5000
echo - Dashboard de Respaldo: http://localhost:5000/backup_dashboard
echo.

echo ========================================================
echo  ¡Todos los servicios iniciados en ventanas separadas!
echo.
echo  IMPORTANTE:
echo  1. El Dashboard Principal tiene controles de simulador mejorados
echo  2. El Dashboard de Respaldo muestra estado cuando fallan comunicaciones
echo  3. Las ambulancias ahora se repostan exactamente al 100%%
echo  4. Usa las acciones rápidas para inyectar incidentes y tratamientos
echo ========================================================
echo.
echo Presiona cualquier tecla para cerrar esta ventana...
pause > nul
